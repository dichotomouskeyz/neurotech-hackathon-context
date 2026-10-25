"""Turn live BFI, BVI, and contact quality into a CQ-gated stress label.

The stress label is the relative rise in forehead blood flow and blood volume
against each camera's median during the resting baseline. Optical heart rate
is estimated from the BFI pulse for a side panel. It is never an input to the label.

Comparison, for research. During baseline, and only while contact quality is
at least 0.50, each camera stores its own samples. Its baseline is the median
of those samples. The rise is (current 1 s median - that baseline) / baseline.
An unweighted mean of every camera lets flat cameras pull the index down.
After the first second of the hold, the gate ranks cameras by their rise over
that second and keeps up to four whose rise is at least 3%, when at least two
clear that floor. The index is the median of those cameras' rises, so one
spiked camera does not set the alert. If fewer than two cameras clear 3%,
the index is the median rise of every eligible camera and the tile says all
cameras. Nothing is added on top of the measured rise. Alert when that index
stays at or above 10% for 0.8 s and contact is still good.

``challenge_done`` and ``perfusion_returned`` are what calibration waits on.
The hold can end once elevation has lasted, with contact good enough to score.
``perfusion_returned`` is forehead BFI back under 5% and contact still at
least 0.50, held for ``settle_hold_s``, during recovery. That ends calibration.
It does not unlock the task. ``settled`` is the work-phase gate staying open
for that same hold. Bad contact cannot return or settle. The stress label
stays secondary. ``TaskController`` decides whether the work step advances,
eases, breaks, or coaches a breath from BFI, BVI, and tau.

For research. This is not a diagnosis.
"""

from __future__ import annotations

import math
from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from typing import Any

from features.pulse_hr import estimate_optical_hr
from features.recovery_gate import BFI_RECOVERED_BELOW, TaskController, TaskView
from features.stress_index import StressResult, StressTracker

STRESS_HOLD_S = 0.8
SETTLE_HOLD_S = 2.0
# Below the 10% alert so a hold that comes back near baseline can continue,
# while a rise that is still almost at the alert line does not count as settled.
SETTLE_INDEX = 0.05
SMOOTH_S = 1.0
STRESS_EVERY_S = 0.25
HR_EVERY_S = 1.0
HR_WINDOW_S = 12.0
# Rank cameras after this much of the hold, then keep that set through recovery.
SELECT_AFTER_S = 1.0
TOP_N = 4
MIN_MOVERS = 2
# Cameras under this relative rise are treated as silent and are not used to
# amplify the index. Fewer than MIN_MOVERS above the floor: score every
# eligible camera (no amplification).
RISE_FLOOR = 0.03
MIN_CHANNEL_BASELINE = 0.2
MAX_CHANNEL_CV = 0.50
MIN_CHANNEL_SAMPLES = 5
MIN_HOLD_SAMPLES = 3
BASELINE_CAP = 2400


def _median(values: Sequence[float]) -> float:
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2 == 1:
        return ordered[mid]
    return 0.5 * (ordered[mid - 1] + ordered[mid])


def channel_label(side: str, index: int) -> str:
    """Hardware camera number. Software index 0 is camera 1."""
    return f"{'L' if side == 'left' else 'R'}{index + 1}"


def _cv(values: Sequence[float], center: float) -> float:
    if len(values) < 2 or center <= 0:
        return 0.0
    var = sum((value - center) ** 2 for value in values) / (len(values) - 1)
    return math.sqrt(var) / center


@dataclass(frozen=True)
class ChannelStat:
    key: tuple[str, int]
    baseline: float
    current: float
    cv: float
    n_baseline: int
    n_current: int


def select_responsive(
    stats: Sequence[ChannelStat],
    *,
    top_n: int = TOP_N,
    min_movers: int = MIN_MOVERS,
    rise_floor: float = RISE_FLOOR,
) -> tuple[list[tuple[str, int]], bool]:
    """Cameras that actually moved, plus whether that set is an amplification.

    Returns ``(keys, amplified)``. ``amplified`` is false when fewer than
    ``min_movers`` cameras clear ``rise_floor``; the caller then scores every
    eligible camera instead of a responsive subset.
    """
    eligible: list[tuple[tuple[str, int], float]] = []
    for stat in stats:
        if stat.n_baseline < MIN_CHANNEL_SAMPLES or stat.n_current < MIN_HOLD_SAMPLES:
            continue
        if stat.baseline < MIN_CHANNEL_BASELINE or stat.cv > MAX_CHANNEL_CV:
            continue
        rise = (stat.current - stat.baseline) / stat.baseline
        eligible.append((stat.key, rise))
    if not eligible:
        return [], False
    movers = [item for item in eligible if item[1] >= rise_floor]
    movers.sort(key=lambda item: (-item[1], channel_label(*item[0])))
    if len(movers) < min_movers:
        return [key for key, _rise in eligible], False
    return [key for key, _rise in movers[:top_n]], True


def _camera_values(frame: dict[str, Any]) -> dict[tuple[str, int], float]:
    """Finite, positive samples keyed by ``(side, index)``."""
    found: dict[tuple[str, int], float] = {}
    for side in ("left", "right"):
        for index, raw in enumerate(frame.get(side) or []):
            if raw is None:
                continue
            try:
                value = float(raw)
            except (TypeError, ValueError):
                continue
            if math.isfinite(value) and value > 0:
                found[(side, index)] = value
    return found


@dataclass
class _Channel:
    baseline_values: list[float] = field(default_factory=list)
    hold_values: list[float] = field(default_factory=list)
    recent: deque[tuple[float, float]] = field(default_factory=deque)
    baseline: float | None = None
    cv: float = 0.0


class CameraBook:
    """Per-camera baselines and the responsive subset for one metric."""

    def __init__(self) -> None:
        self.channels: dict[tuple[str, int], _Channel] = {}
        self.selected: list[tuple[str, int]] = []
        self.locked = False
        self.amplified = False
        self._hold_t0: float | None = None

    def reset(self) -> None:
        self.channels.clear()
        self.selected = []
        self.locked = False
        self.amplified = False
        self._hold_t0 = None

    def _chan(self, key: tuple[str, int]) -> _Channel:
        chan = self.channels.get(key)
        if chan is None:
            chan = _Channel()
            self.channels[key] = chan
        return chan

    def observe_baseline(self, values: dict[tuple[str, int], float]) -> None:
        for key, value in values.items():
            chan = self._chan(key)
            chan.baseline_values.append(value)
            extra = len(chan.baseline_values) - BASELINE_CAP
            if extra > 0:
                del chan.baseline_values[:extra]

    def start_hold(self, t: float) -> None:
        self._hold_t0 = t
        self.locked = False
        self.amplified = False
        self.selected = []
        for chan in self.channels.values():
            chan.hold_values.clear()
            chan.recent.clear()
            if len(chan.baseline_values) >= MIN_CHANNEL_SAMPLES:
                chan.baseline = _median(chan.baseline_values)
                chan.cv = _cv(chan.baseline_values, chan.baseline)
            else:
                chan.baseline = None
                chan.cv = 0.0

    def clear_recent(self) -> None:
        """Drop the 1 s smoother so a new phase is not scored on the previous one."""
        for chan in self.channels.values():
            chan.recent.clear()

    def ensure_started(self, t: float) -> None:
        if self._hold_t0 is None:
            self.start_hold(t)

    def observe_hold(
        self,
        t: float,
        values: dict[tuple[str, int], float],
        *,
        select_after_s: float,
    ) -> bool:
        """Record hold samples. Return True on the frame that locks selection."""
        self.ensure_started(t)
        for key, value in values.items():
            chan = self._chan(key)
            chan.hold_values.append(value)
            chan.recent.append((t, value))
            cutoff = t - SMOOTH_S
            while chan.recent and chan.recent[0][0] < cutoff:
                chan.recent.popleft()
        if self.locked or self._hold_t0 is None or t - self._hold_t0 < select_after_s:
            return False
        # Wait until the rank window has more than a single frame, so one
        # spike at the one-second mark cannot choose the cameras.
        if not any(len(chan.hold_values) >= MIN_HOLD_SAMPLES for chan in self.channels.values()):
            return False
        self._lock()
        return True

    def _lock(self) -> None:
        stats: list[ChannelStat] = []
        for key, chan in self.channels.items():
            if chan.baseline is None:
                continue
            stats.append(
                ChannelStat(
                    key,
                    chan.baseline,
                    _median(chan.hold_values) if chan.hold_values else chan.baseline,
                    chan.cv,
                    len(chan.baseline_values),
                    len(chan.hold_values),
                )
            )
        self.selected, self.amplified = select_responsive(stats)
        self.locked = True

    def _live_median(self, chan: _Channel) -> float | None:
        if chan.recent:
            return _median([value for _t, value in chan.recent])
        if chan.hold_values:
            return _median(chan.hold_values)
        return None

    def _keys_in_use(self) -> list[tuple[str, int]]:
        if self.locked and self.selected:
            return list(self.selected)
        keys = []
        for key, chan in self.channels.items():
            if (
                chan.baseline is not None
                and chan.baseline >= MIN_CHANNEL_BASELINE
                and chan.cv <= MAX_CHANNEL_CV
            ):
                keys.append(key)
        return keys

    def live_index(self) -> tuple[float, float | None]:
        """Median relative rise of the cameras in use, and their absolute level."""
        rises: list[float] = []
        absolutes: list[float] = []
        for key in self._keys_in_use():
            chan = self.channels.get(key)
            if chan is None or chan.baseline is None or chan.baseline <= 0:
                continue
            current = self._live_median(chan)
            if current is None:
                continue
            rises.append((current - chan.baseline) / chan.baseline)
            absolutes.append(current)
        if not rises:
            return 0.0, None
        return max(0.0, _median(rises)), _median(absolutes)

    def baseline_absolute(self) -> float | None:
        values = []
        for key in self._keys_in_use():
            chan = self.channels.get(key)
            if chan is not None and chan.baseline is not None and chan.baseline > 0:
                values.append(chan.baseline)
        if not values:
            values = [
                chan.baseline
                for chan in self.channels.values()
                if chan.baseline is not None and chan.baseline > 0
            ]
        return _median(values) if values else None

    def channel_text(self, metric: str) -> str:
        if not self.locked:
            return ""
        if not self.amplified or not self.selected:
            return f"{metric} all cameras"
        names = ", ".join(channel_label(*key) for key in self.selected)
        return f"{metric} {names}"


class LiveGate:
    """Stateful scorer on the dashboard publish path.

    Call ``observe`` with each batch the hub is about to broadcast. Phase and
    session frames update the trackers. BFI, BVI, and CQ frames update the
    label. Returned frames (``stress``, and ``hr`` when a pulse is clear) should
    be published with the batch, not fed back into ``observe``.
    """

    def __init__(
        self,
        *,
        stress_hold_s: float = STRESS_HOLD_S,
        settle_hold_s: float = SETTLE_HOLD_S,
        settle_index: float = SETTLE_INDEX,
        smooth_s: float = SMOOTH_S,
        select_after_s: float = SELECT_AFTER_S,
    ) -> None:
        self.stress_hold_s = stress_hold_s
        self.settle_hold_s = settle_hold_s
        self.settle_index = settle_index
        self.smooth_s = smooth_s
        self.select_after_s = select_after_s
        self.bfi_tracker = StressTracker()
        self.bvi_tracker = StressTracker()
        self.bfi_book = CameraBook()
        self.bvi_book = CameraBook()
        self.phase: str | None = None
        self._session_id: str | None = None
        self._cq: float | None = None
        self._bfi_level: float | None = None
        self._bvi_level: float | None = None
        self._hr_t: deque[float] = deque()
        self._hr_v: deque[float] = deque()
        self._last_t: float | None = None
        self._last_stress_t: float | None = None
        self._last_hr_t: float | None = None
        self._stressed_since: float | None = None
        self._returned_since: float | None = None
        self._settled_since: float | None = None
        self.latest_stress: dict[str, Any] | None = None
        self.task = TaskController()

    def observe(self, frames: list[dict[str, Any]]) -> list[dict[str, Any]]:
        sample_t: float | None = None
        for frame in frames:
            kind = frame.get("type")
            if kind == "session":
                self._on_session(frame)
            elif kind == "phase":
                self._on_phase(frame)
            elif kind == "cq":
                self._on_cq(frame)
            elif kind == "bfi":
                level = self._ingest(self.bfi_book, self.bfi_tracker, frame)
                sample_t = float(frame["t"])
                if level is not None:
                    self._bfi_level = level
                    self._push_hr(sample_t, level)
            elif kind == "bvi":
                level = self._ingest(self.bvi_book, self.bvi_tracker, frame)
                sample_t = float(frame["t"])
                if level is not None:
                    self._bvi_level = level
        if sample_t is None:
            return []
        return self._maybe_emit(sample_t)

    def challenge_done(self, now: float) -> bool:
        """True once hold-phase elevation has lasted ``stress_hold_s``.

        ``now`` is the logger clock. The sustain window uses sample time, which
        is the same clock on a live scan.
        """
        del now
        if self._stressed_since is None or self._last_t is None:
            return False
        return self._last_t - self._stressed_since >= self.stress_hold_s

    def perfusion_returned(self, now: float) -> bool:
        """True once recovery has held BFI back and good contact for ``settle_hold_s``.

        This ends calibration. The work gate can still be shut. A bad contact
        score clears the latch.
        """
        del now
        if self._returned_since is None or self._last_t is None:
            return False
        return self._last_t - self._returned_since >= self.settle_hold_s

    def settled(self, now: float) -> bool:
        """True once the work gate has stayed open for ``settle_hold_s``.

        Open means forehead BFI is back toward baseline and contact is still
        good during work. A bad contact score clears the latch. Calibration
        does not settle, because the gate stays shut until work.
        """
        del now
        if self._settled_since is None or self._last_t is None:
            return False
        return self._last_t - self._settled_since >= self.settle_hold_s

    def tau_s(self) -> float | None:
        """Fitted recovery time constant, or None until a decay fit succeeds."""
        return self._tau()

    def task_snapshot(self) -> TaskView:
        """Latest recovery-gate decision for the phase logger."""
        return self.task.view

    # Incoming frames

    def _on_session(self, frame: dict[str, Any]) -> None:
        sid = frame.get("session_id") if frame.get("active") else None
        if sid != self._session_id:
            self._reset_trackers()
            self._session_id = sid
        phase = frame.get("phase")
        if sid and phase in ("baseline", "hold", "recovery", "work", "end") and phase != self.phase:
            raw_t = frame.get("t")
            t = float(raw_t) if isinstance(raw_t, (int, float)) else 0.0
            self._apply_phase(str(phase), t)

    def _on_phase(self, frame: dict[str, Any]) -> None:
        if frame.get("session_id") != self._session_id:
            return
        self._apply_phase(str(frame["phase"]), float(frame["t"]))

    def _apply_phase(self, phase: str, t: float) -> None:
        if phase == self.phase:
            return
        self.phase = phase
        self._stressed_since = None
        self._returned_since = None
        self._settled_since = None
        self.bfi_tracker.on_phase(phase, t)
        self.bvi_tracker.on_phase(phase, t)
        if phase == "baseline":
            self.task.reset()
        elif phase == "recovery":
            # A previous sit's tau must not coach this recovery. The fit from
            # this recovery is what work may use.
            self.bfi_tracker.last_recovery_result = None
            self.bvi_tracker.last_recovery_result = None
        elif phase == "work":
            # Do not score the first work samples on the last second of recovery.
            self.bfi_book.clear_recent()
            self.bvi_book.clear_recent()
        if phase == "hold":
            self.bfi_book.start_hold(t)
            self.bvi_book.start_hold(t)
        elif phase == "baseline":
            self.bfi_book.locked = False
            self.bvi_book.locked = False
            self.bfi_book.selected = []
            self.bvi_book.selected = []
            self.bfi_book.amplified = False
            self.bvi_book.amplified = False
            self.bfi_book._hold_t0 = None
            self.bvi_book._hold_t0 = None

    def _on_cq(self, frame: dict[str, Any]) -> None:
        vals = []
        for side in ("left", "right"):
            raw = frame.get(side)
            if raw is None:
                continue
            value = float(raw)
            if math.isfinite(value):
                vals.append(value)
        self._cq = min(vals) if vals else None

    def _contact_ok(self) -> bool:
        return self._cq is not None and self._cq >= self.bfi_tracker.cq_threshold

    def _ingest(
        self, book: CameraBook, tracker: StressTracker, frame: dict[str, Any]
    ) -> float | None:
        """Update per-camera state. Return the absolute level fed to the tracker."""
        t = float(frame["t"])
        values = _camera_values(frame)
        if values and self._contact_ok():
            if self.phase == "baseline":
                book.observe_baseline(values)
            elif self.phase in ("hold", "recovery", "work"):
                locked_before = book.locked
                book.observe_hold(t, values, select_after_s=self.select_after_s)
                if book.locked and not locked_before:
                    base = book.baseline_absolute()
                    if base is not None and base > 0:
                        tracker.set_baseline(base)
        # Heart rate needs the per-frame level, not the 1 s selection median.
        if not values:
            return None
        return _median(list(values.values()))

    def _push_hr(self, t: float, mean: float | None) -> None:
        if mean is None:
            return
        if self._hr_t and t <= self._hr_t[-1]:
            return
        self._hr_t.append(t)
        self._hr_v.append(mean)
        cutoff = t - HR_WINDOW_S
        while self._hr_t and self._hr_t[0] < cutoff:
            self._hr_t.popleft()
            self._hr_v.popleft()

    # Scoring

    def _maybe_emit(self, t: float) -> list[dict[str, Any]]:
        self._last_t = t
        out: list[dict[str, Any]] = []
        if self._cq is not None and (
            self._last_stress_t is None or t - self._last_stress_t >= STRESS_EVERY_S
        ):
            frame = self._stress_frame(t)
            if frame is not None:
                out.append(frame)
                self.latest_stress = frame
                self._last_stress_t = t
        hr = self._hr_frame(t)
        if hr is not None:
            out.append(hr)
        return out

    def _stress_frame(self, t: float) -> dict[str, Any] | None:
        if self._cq is None:
            return None
        if self.phase not in ("baseline", "hold", "recovery", "work"):
            self._stressed_since = None
            self._settled_since = None
            view = self.task.update(
                bfi_index=None,
                bvi_index=None,
                cq=self._cq,
                tau_s=None,
                phase=self.phase or "",
            )
            frame = {
                "type": "stress",
                "t": t,
                "index": 0.0,
                "recovery_score": None,
                "alert": False,
                "reason": "baseline_uncalibrated: start baseline to score perfusion",
            }
            _attach_gate(frame, view)
            return frame
        bfi = self._sample(self.bfi_tracker, self.bfi_book, t, self._bfi_level)
        bvi = self._sample(self.bvi_tracker, self.bvi_book, t, self._bvi_level)
        if bfi is None and bvi is None:
            return None
        shown = self._present(bfi, bvi)
        tau = self._tau() if self.phase in ("recovery", "work") else None
        view = self.task.update(
            bfi_index=_metric_index(bfi),
            bvi_index=_metric_index(bvi),
            cq=self._cq,
            tau_s=tau,
            phase=self.phase or "",
        )
        self._latch(t, shown, view.gate_open, _metric_index(bfi))
        frame = shown.to_frame()
        frame["alert_at"] = self.bfi_tracker.alert_threshold
        if self.phase != "baseline":
            channels = self._channel_text()
            if channels:
                frame["channels"] = channels
        if tau is not None:
            frame["tau_s"] = tau
        _attach_gate(frame, view)
        return frame

    def _sample(
        self,
        tracker: StressTracker,
        book: CameraBook,
        t: float,
        level: float | None,
    ) -> StressResult | None:
        if level is None:
            return None
        feed = level
        if self.phase in ("hold", "recovery", "work") and book.locked:
            _rise, absolute = book.live_index()
            if absolute is not None:
                feed = absolute
        raw = tracker.on_sample(t, feed, self._cq)
        if self.phase not in ("hold", "recovery", "work"):
            return raw
        if raw.reason.startswith(("poor_coupling", "invalid_sample")):
            return raw
        index, _absolute = book.live_index()
        base = book.baseline_absolute()
        if base is None and raw.baseline is None:
            return raw
        # The tracker's own index compares one blended level. Scoring uses the
        # median of per-camera rises so flat cameras do not wash the hold out.
        alert = index >= tracker.alert_threshold
        reason = raw.reason
        if reason.startswith("baseline_uncalibrated"):
            reason = "nominal: cameras have a baseline"
        return replace(
            raw,
            index=index,
            alert=alert,
            reason=reason,
            baseline=base if base is not None else raw.baseline,
        )

    def _channel_text(self) -> str:
        parts = [
            text
            for text in (
                self.bfi_book.channel_text("BFI"),
                self.bvi_book.channel_text("BVI"),
            )
            if text
        ]
        return " · ".join(parts)

    def _present(self, bfi: StressResult | None, bvi: StressResult | None) -> StressResult:
        combined = _combine(bfi, bvi, self.bfi_tracker.alert_threshold)
        if self.phase != "baseline":
            return combined
        # Baseline is the resting reference. Keep a poor-contact reason, and
        # do not raise the label before the challenge starts.
        if combined.reason.startswith("poor_coupling"):
            return replace(combined, alert=False)
        if combined.baseline is None:
            reason = "resting baseline: collecting BFI and BVI"
        else:
            reason = "resting baseline"
        return replace(combined, alert=False, reason=reason)

    def _latch(
        self, t: float, shown: StressResult, gate_open: bool, bfi_index: float | None
    ) -> None:
        if self.phase == "hold" and shown.alert:
            if self._stressed_since is None:
                self._stressed_since = t
        else:
            self._stressed_since = None
        # The recovery gate is BFI returned and contact still good. The combined
        # stress index can stay up on blood volume without keeping the gate shut,
        # and a bad contact score cannot leave it open.
        if gate_open:
            if self._settled_since is None:
                self._settled_since = t
        else:
            self._settled_since = None
        # Calibration ends when flow is back, even though the task gate stays
        # shut until work. Blood volume is not part of this check.
        bfi_back = (
            self.phase == "recovery"
            and bfi_index is not None
            and bfi_index < BFI_RECOVERED_BELOW
            and self._contact_ok()
        )
        if bfi_back:
            if self._returned_since is None:
                self._returned_since = t
        elif self.phase == "recovery":
            self._returned_since = None

    def _tau(self) -> float | None:
        for tracker in (self.bfi_tracker, self.bvi_tracker):
            recovery = tracker.last_recovery_result
            if recovery is not None and recovery.ok and recovery.tau_s is not None:
                tau = float(recovery.tau_s)
                if math.isfinite(tau):
                    return tau
        return None

    def _hr_frame(self, t: float) -> dict[str, Any] | None:
        if self._last_hr_t is not None and t - self._last_hr_t < HR_EVERY_S:
            return None
        if len(self._hr_t) < 2 or self._hr_t[-1] - self._hr_t[0] < 8.0:
            return None
        if self._cq is not None and self._cq < self.bfi_tracker.cq_threshold:
            return None
        self._last_hr_t = t
        estimate = estimate_optical_hr(list(self._hr_t), list(self._hr_v))
        if not estimate.ok or estimate.bpm is None:
            return None
        bpm = float(estimate.bpm)
        if not 0.0 < bpm < 300.0:
            return None
        return {"type": "hr", "t": t, "source": "optical", "bpm": bpm}

    def _reset_trackers(self) -> None:
        self.bfi_tracker.reset()
        self.bvi_tracker.reset()
        self.bfi_book.reset()
        self.bvi_book.reset()
        self.phase = None
        self._stressed_since = None
        self._returned_since = None
        self._settled_since = None
        self._last_stress_t = None
        self._last_hr_t = None
        self._bfi_level = None
        self._bvi_level = None
        self._hr_t.clear()
        self._hr_v.clear()
        self.task.reset()


def _metric_index(result: StressResult | None) -> float | None:
    """Relative rise for one metric, or None when the sample cannot be scored.

    Poor contact zeroes the stress index inside the tracker. That zero is not
    a recovered blood-flow trace, so the gate must not treat it as one.
    """
    if result is None or result.baseline is None:
        return None
    if result.reason.startswith(("poor_coupling", "invalid_sample", "baseline_uncalibrated")):
        return None
    return float(result.index)


def _attach_gate(frame: dict[str, Any], view: TaskView) -> None:
    frame["gate"] = "open" if view.gate_open else "locked"
    frame["gate_reason"] = view.reason
    frame["task"] = view.action
    frame["difficulty"] = view.difficulty


def _usable(result: StressResult) -> bool:
    if result.baseline is None:
        return False
    return not result.reason.startswith(
        ("baseline_uncalibrated", "invalid_sample", "poor_coupling")
    )


def _combine(
    bfi: StressResult | None,
    bvi: StressResult | None,
    alert_threshold: float,
) -> StressResult:
    """One label from the two perfusion indexes. Heart rate is not an input."""
    present = [result for result in (bfi, bvi) if result is not None]
    if not present:
        raise ValueError("need a BFI or BVI result")
    lead = present[0]
    if lead.reason.startswith(("poor_coupling", "invalid_sample")):
        return lead
    usable = [result for result in present if _usable(result)]
    if not usable:
        return lead
    index = max(result.index for result in usable)
    alert = any(result.alert for result in usable)
    bits = []
    if bfi is not None and bfi in usable:
        bits.append(f"BFI {bfi.index:.0%}")
    if bvi is not None and bvi in usable:
        bits.append(f"BVI {bvi.index:.0%}")
    detail = ", ".join(bits)
    if alert:
        reason = f"elevated_stress: {detail} >= {alert_threshold:.0%} vs baseline"
    else:
        reason = f"nominal: {detail} < {alert_threshold:.0%} vs baseline"
    recovery = next(
        (result.recovery_score for result in usable if result.recovery_score is not None),
        None,
    )
    top = max(usable, key=lambda result: result.index)
    return replace(top, index=index, alert=alert, reason=reason, recovery_score=recovery)

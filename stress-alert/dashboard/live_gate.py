"""Turn live BFI, BVI, and contact quality into a CQ-gated stress label.

The stress label is the relative rise in forehead blood flow and blood volume
against the session baseline. Optical heart rate is estimated from the BFI
pulse for a side panel. It is never an input to the label.

``challenge_done`` and ``settled`` are what the closed-loop protocol waits on:
stop the breath-hold once elevation holds with good contact, and continue once
perfusion is back near baseline with good contact.

For research. This is not a diagnosis.
"""

from __future__ import annotations

import math
from collections import deque
from collections.abc import Sequence
from dataclasses import replace
from typing import Any

from features.pulse_hr import estimate_optical_hr
from features.stress_index import StressResult, StressTracker

STRESS_HOLD_S = 0.8
SETTLE_HOLD_S = 2.0
SETTLE_INDEX = 0.12
SMOOTH_S = 1.0
STRESS_EVERY_S = 0.25
HR_EVERY_S = 1.0
HR_WINDOW_S = 12.0


def _finite_mean(values: Sequence[float | None]) -> float | None:
    nums = [float(v) for v in values if v is not None and math.isfinite(float(v))]
    if not nums:
        return None
    return sum(nums) / len(nums)


def _median(values: Sequence[float]) -> float:
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2 == 1:
        return ordered[mid]
    return 0.5 * (ordered[mid - 1] + ordered[mid])


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
    ) -> None:
        self.stress_hold_s = stress_hold_s
        self.settle_hold_s = settle_hold_s
        self.settle_index = settle_index
        self.smooth_s = smooth_s
        self.bfi_tracker = StressTracker()
        self.bvi_tracker = StressTracker()
        self.phase: str | None = None
        self._session_id: str | None = None
        self._cq: float | None = None
        self._bfi_level: float | None = None
        self._bvi_level: float | None = None
        self._bfi_smooth: deque[tuple[float, float]] = deque()
        self._bvi_smooth: deque[tuple[float, float]] = deque()
        self._hr_t: deque[float] = deque()
        self._hr_v: deque[float] = deque()
        self._last_t: float | None = None
        self._last_stress_t: float | None = None
        self._last_hr_t: float | None = None
        self._stressed_since: float | None = None
        self._settled_since: float | None = None
        self.latest_stress: dict[str, Any] | None = None

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
                level = self._on_level(self._bfi_smooth, frame)
                if level is not None:
                    self._bfi_level = level
                    self._push_hr(float(frame["t"]), _finite_mean([*_sides(frame)]))
                    sample_t = float(frame["t"])
            elif kind == "bvi":
                level = self._on_level(self._bvi_smooth, frame)
                if level is not None:
                    self._bvi_level = level
                    sample_t = float(frame["t"])
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

    def settled(self, now: float) -> bool:
        """True once recovery is near baseline, with contact still good."""
        del now
        if self._settled_since is None or self._last_t is None:
            return False
        return self._last_t - self._settled_since >= self.settle_hold_s

    # Incoming frames

    def _on_session(self, frame: dict[str, Any]) -> None:
        sid = frame.get("session_id") if frame.get("active") else None
        if sid != self._session_id:
            self._reset_trackers()
            self._session_id = sid

    def _on_phase(self, frame: dict[str, Any]) -> None:
        if frame.get("session_id") != self._session_id:
            return
        phase = str(frame["phase"])
        t = float(frame["t"])
        self.phase = phase
        self._stressed_since = None
        self._settled_since = None
        self.bfi_tracker.on_phase(phase, t)
        self.bvi_tracker.on_phase(phase, t)

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

    def _on_level(self, window: deque[tuple[float, float]], frame: dict[str, Any]) -> float | None:
        mean = _finite_mean([*_sides(frame)])
        if mean is None or mean <= 0:
            return None
        return self._smooth(window, float(frame["t"]), mean)

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

    def _smooth(self, window: deque[tuple[float, float]], t: float, value: float) -> float:
        if window and t < window[-1][0]:
            window.clear()
        window.append((t, value))
        cutoff = t - self.smooth_s
        while window and window[0][0] < cutoff:
            window.popleft()
        return _median([v for _, v in window])

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
        if self.phase not in ("baseline", "hold", "recovery"):
            self._stressed_since = None
            self._settled_since = None
            return {
                "type": "stress",
                "t": t,
                "index": 0.0,
                "recovery_score": None,
                "alert": False,
                "reason": "baseline_uncalibrated: start baseline to score perfusion",
            }
        bfi = self._sample(self.bfi_tracker, t, self._bfi_level)
        bvi = self._sample(self.bvi_tracker, t, self._bvi_level)
        if bfi is None and bvi is None:
            return None
        shown = self._present(bfi, bvi)
        self._latch(t, shown)
        frame = shown.to_frame()
        if self.phase == "recovery":
            tau = self._tau()
            if tau is not None:
                frame["tau_s"] = tau
        return frame

    def _sample(self, tracker: StressTracker, t: float, level: float | None) -> StressResult | None:
        if level is None:
            return None
        return tracker.on_sample(t, level, self._cq)

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

    def _latch(self, t: float, shown: StressResult) -> None:
        if self.phase == "hold" and shown.alert:
            if self._stressed_since is None:
                self._stressed_since = t
        else:
            self._stressed_since = None
        settled = (
            self.phase == "recovery"
            and shown.baseline is not None
            and not shown.alert
            and shown.reason.startswith("nominal")
            and shown.index < self.settle_index
            and shown.cq is not None
            and shown.cq >= self.bfi_tracker.cq_threshold
        )
        if settled:
            if self._settled_since is None:
                self._settled_since = t
        else:
            self._settled_since = None

    def _tau(self) -> float | None:
        for tracker in (self.bfi_tracker, self.bvi_tracker):
            recovery = tracker.last_recovery_result
            if recovery is not None and recovery.ok and recovery.tau_s is not None:
                return float(recovery.tau_s)
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
        self.phase = None
        self._stressed_since = None
        self._settled_since = None
        self._last_stress_t = None
        self._last_hr_t = None
        self._bfi_level = None
        self._bvi_level = None
        self._bfi_smooth.clear()
        self._bvi_smooth.clear()
        self._hr_t.clear()
        self._hr_v.clear()


def _sides(frame: dict[str, Any]) -> list[float | None]:
    return [*frame.get("left", []), *frame.get("right", [])]


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

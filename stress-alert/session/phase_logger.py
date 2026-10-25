"""Session and phase logging for calibration and the work loop.

A session is one sitting with one subject. The breath-hold protocol is
baseline, then hold, then recovery. The closed loop adds ``work`` after that
recovery: calibration learns resting blood flow, and work is where the
recovery gate controls the task. Every phase change is written to
``sessions/<id>/events.csv``, emitted as a ``phase`` frame, and pushed as an LSL
string marker so other recordings can be aligned to it.
"""

import asyncio
import csv
import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

from dashboard import clock

PHASES = ("baseline", "hold", "recovery", "work", "end")
NEXT: dict[str | None, set[str]] = {
    None: {"baseline", "end"},
    "baseline": {"hold", "work", "end"},
    "hold": {"recovery", "end"},
    "recovery": {"work", "baseline", "end"},
    "work": {"baseline", "end"},
    "end": set(),
}
DEFAULT_DURATIONS = {"baseline": 60.0, "hold": 30.0, "recovery": 90.0}
# Long session, the live default. A short baseline sit, no breath-hold unless
# the operator types one, then 20 minutes of work. Demo Mode keeps its own
# short durations. Work can also run with no deadline until the operator ends it.
LONG_BASELINE_S = 20.0
LONG_HOLD_S = 0.0
LONG_RECOVERY_S = 20.0
LONG_WORK_S = 20.0 * 60.0
LONG_WORK_MAX_S = 4.0 * 60.0 * 60.0
# A hold that never clears the alert does not run the full recovery window.
# The countdown uses this same dwell, and the cue says why it is short.
NO_ELEVATION_DWELL_S = 4.0
EVENT_FIELDS = ["t", "wall_time", "session_id", "phase", "source"]

Emit = Callable[[list[dict[str, Any]]], None]


class LoopSignals(Protocol):
    """What the closed loop asks the hemodynamic gate."""

    def challenge_done(self, now: float) -> bool:
        """Elevation versus baseline has held, with contact good enough to score."""

    def settled(self, now: float) -> bool:
        """Work gate has stayed open: BFI returned and contact still good."""

    # Optional. ``perfusion_returned(now)`` is true once calibration recovery
    # has held BFI back with good contact. When it is missing, ``settled`` is
    # used so older fakes still end calibration.
    #
    # Optional. When present, ``task_snapshot()`` returns an object with
    # ``action``, ``difficulty``, ``gate_open``, and ``cue``. The work phase
    # follows it. Calibration does not.


class PhaseError(ValueError):
    """A phase change that the protocol does not allow."""


class MarkerOutlet:
    """LSL string-marker outlet. Becomes a no-op if liblsl is unavailable."""

    def __init__(self, name: str = "stress-alert-phases") -> None:
        try:
            from pylsl import StreamInfo, StreamOutlet, cf_string

            info = StreamInfo(name, "Markers", 1, 0, cf_string, "stress-alert-phase-logger")
            self._outlet = StreamOutlet(info)
            self.error = ""
        except Exception as exc:  # pragma: no cover - depends on liblsl
            self._outlet = None
            self.error = str(exc)

    @property
    def available(self) -> bool:
        return self._outlet is not None

    def push(self, text: str, t: float) -> None:
        if self._outlet is not None:
            self._outlet.push_sample([text], t)


@dataclass
class Session:
    session_id: str
    subject_id: str
    directory: Path
    phase: str | None = None
    phase_t: float | None = None
    events: list[dict[str, Any]] = field(default_factory=list)


class PhaseLogger:
    def __init__(
        self,
        root: Path,
        emit: Emit = lambda frames: None,
        markers: MarkerOutlet | None = None,
        now: Callable[[], float] = clock.now,
    ) -> None:
        self.root = root
        self.emit = emit
        self.markers = markers
        self.now = now
        self.session: Session | None = None
        self.timer_next: str | None = None
        self.timer_ends_t: float | None = None
        self.loop = "off"
        self.loop_cue = ""
        self.gate = "off"
        self.difficulty = 1
        self._timer: asyncio.Task[None] | None = None

    # Sessions

    def start_session(self, subject_id: str, notes: str = "") -> Session:
        if self.session is not None:
            raise PhaseError(f"session {self.session.session_id} is still open")
        subject = re.sub(r"[^A-Za-z0-9_-]+", "-", subject_id.strip()).strip("-") or "anon"
        session_id = f"{datetime.now():%Y%m%d-%H%M%S}_{subject}"
        directory = self.root / session_id
        directory.mkdir(parents=True, exist_ok=False)
        meta = {
            "session_id": session_id,
            "subject_id": subject,
            "notes": notes,
            "started_wall": datetime.now().astimezone().isoformat(timespec="seconds"),
            "started_t": self.now(),
            "clock": clock.NAME,
            "lsl_markers": bool(self.markers and self.markers.available),
        }
        (directory / "meta.json").write_text(json.dumps(meta, indent=2))
        with (directory / "events.csv").open("w", newline="") as handle:
            csv.DictWriter(handle, EVENT_FIELDS).writeheader()
        self.session = Session(session_id, subject, directory)
        self._emit_state()
        return self.session

    def stop_session(self) -> None:
        if self.session is None:
            return
        self.cancel_timer()
        self.loop = "off"
        self.loop_cue = ""
        self.gate = "off"
        self.difficulty = 1
        if self.session.phase != "end":
            self.mark("end", "manual")
        self.session = None
        self._emit_state()

    # Phases

    def mark(self, phase: str, source: str = "manual") -> dict[str, Any]:
        if self.session is None:
            raise PhaseError("start a session first")
        if phase not in PHASES:
            raise PhaseError(f"unknown phase {phase!r}")
        if phase not in NEXT[self.session.phase]:
            raise PhaseError(f"cannot go from {self.session.phase or 'start'} to {phase}")
        if source == "manual":
            self.cancel_timer()
        t = self.now()
        event = {
            "t": t,
            "wall_time": datetime.now().astimezone().isoformat(timespec="milliseconds"),
            "session_id": self.session.session_id,
            "phase": phase,
            "source": source,
        }
        with (self.session.directory / "events.csv").open("a", newline="") as handle:
            csv.DictWriter(handle, EVENT_FIELDS).writerow(event)
        self.session.phase, self.session.phase_t = phase, t
        self.session.events.append(event)
        if self.markers:
            self.markers.push(f"{phase}|{self.session.session_id}|{source}", t)
        frame = {"type": "phase", **{k: event[k] for k in ("t", "session_id", "phase", "source")}}
        self.emit([frame])
        self._emit_state()
        return event

    # Timed protocol

    def start_timer(
        self,
        durations: dict[str, float | None] | None = None,
        cycles: int = 1,
        *,
        closed_loop: bool = False,
        signals: LoopSignals | None = None,
    ) -> None:
        if self.session is None:
            raise PhaseError("start a session first")
        if self.session.phase not in (None, "recovery", "work"):
            raise PhaseError("the timed protocol starts from a new session or after calibration")
        if closed_loop and signals is None:
            raise PhaseError("closed loop needs the hemodynamic gate")
        self.cancel_timer()
        plan = {**DEFAULT_DURATIONS, **(durations or {})}
        if closed_loop:
            assert signals is not None
            # The task step is locked as soon as the loop is armed, before the
            # baseline phase is written. Callers can show that on the response.
            self.gate = "locked"
            self.difficulty = 1
            self._timer = asyncio.get_running_loop().create_task(
                self._run_closed_loop(plan, cycles, signals)
            )
        else:
            self._timer = asyncio.get_running_loop().create_task(self._run(plan, cycles))

    def cancel_timer(self) -> None:
        task = self._timer
        self._timer = None
        cancelled = task is not None and task is not asyncio.current_task()
        if cancelled:
            task.cancel()
            self.loop = "off"
            self.loop_cue = ""
            self.gate = "off"
        pending = self.timer_next is not None
        if pending:
            self.timer_next = self.timer_ends_t = None
        if self.session is not None and (cancelled or pending):
            self._emit_state()

    async def _run(self, plan: dict[str, float | None], cycles: int) -> None:
        phases = [p for p in ("baseline", "hold", "recovery") if float(plan.get(p) or 0) > 0]
        steps = [p for _ in range(cycles) for p in phases]
        if not steps:
            return
        for i, phase in enumerate(steps):
            self.timer_next = steps[i + 1] if i + 1 < len(steps) else "end"
            self.timer_ends_t = self.now() + plan[phase]
            self.mark(phase, "timer")
            await asyncio.sleep(plan[phase])
        self.timer_next = self.timer_ends_t = None
        self._timer = None
        self.mark("end", "timer")

    async def _run_closed_loop(
        self, plan: dict[str, float | None], cycles: int, signals: LoopSignals
    ) -> None:
        """Calibrate, then run the work loop on the recovery gate.

        A baseline sit learns resting forehead BFI. The breath-hold and its
        recovery run only when hold is above zero. The task stays locked
        through calibration. Work is the application and can run for many
        minutes, or until the operator ends it. During work the breath coach
        follows the trailing mean of forehead BFI, not the sample that locks
        the gate. A slow recovery tau coaches too. The hold ends early when
        elevation has lasted and contact is good enough to score. A hold that
        never rises still reaches
        work, and without a task snapshot that work stays locked.
        """
        try:
            # Let a stop that arrived before this task ran cancel it cleanly,
            # before any phase is written.
            await asyncio.sleep(0)
            if self.session is None:
                return
            for cycle in range(cycles):
                if self.session is None:
                    return
                last = cycle + 1 == cycles
                nxt = "end" if last else "baseline"
                self.loop = "baseline"
                self.gate = "locked"
                self.difficulty = 1
                self.loop_cue = (
                    "Calibration. Breathe normally. This learns resting forehead "
                    "blood flow. The task stays locked."
                )
                hold_s = float(plan.get("hold") or 0.0)
                self.timer_next = "hold" if hold_s > 0 else "work"
                self.timer_ends_t = self.now() + float(plan["baseline"])
                self.mark("baseline", "timer")
                await self._wait(float(plan["baseline"]))
                elevated = False
                returned = False
                if hold_s <= 0:
                    # Baseline sit only. The breath-hold is optional proof, not
                    # the session. Work is next, and recovery is skipped because
                    # there is no hold to come back from.
                    self.loop_cue = (
                        "Calibration complete. Resting forehead blood flow is set. "
                        "Work is next. The task stays locked until flow is back "
                        "and contact is good."
                    )
                    self._emit_state()
                else:
                    elevated, returned = await self._run_calibration_hold(plan, signals, hold_s)

                work_raw = plan.get("work", plan.get("continue", 12.0))
                open_ended = work_raw is None
                work_s = None if open_ended else float(work_raw)
                self.timer_next = None if open_ended else nxt
                self.timer_ends_t = None if open_ended else self.now() + work_s
                self.loop = "locked"
                self.gate = "locked"
                if open_ended:
                    self.loop_cue = (
                        "Work. This bout runs until you press End. "
                        "If forehead blood flow leaves the calibrated baseline "
                        "and contact is good, a breath starts on its own. "
                        "The step unlocks when flow is back."
                    )
                else:
                    self.loop_cue = (
                        "Work. Stay with the task. "
                        "If forehead blood flow leaves the calibrated baseline "
                        "and contact is good, a breath starts on its own. "
                        "The step unlocks when flow is back."
                    )
                self.mark("work", "timer")
                # The application follows the gate on every sample, not at the
                # end of the bout. A fake with no snapshot opens only when
                # calibration actually saw a return, so a flat hold cannot
                # invent an unlock.
                opened = elevated and returned
                if self._task_view(signals) is not None:
                    await self._wait_until(work_s, lambda: False, signals, follow=True)
                else:
                    if opened:
                        self.loop = "task"
                        self.gate = "open"
                        self.loop_cue = (
                            "Perfusion-ready. BFI is back and contact is good. Work step is open."
                        )
                        self._emit_state()
                    await self._wait(work_s)
            self.loop = "off"
            self.loop_cue = ""
            self.gate = "off"
            self.timer_next = self.timer_ends_t = None
            self._timer = None
            self.mark("end", "timer")
        except asyncio.CancelledError:
            raise
        except PhaseError:
            return
        finally:
            if self.loop != "off":
                self.loop = "off"
                self.loop_cue = ""
                self.gate = "off"
                if self.session is not None:
                    self._emit_state()

    async def _run_calibration_hold(
        self,
        plan: dict[str, float | None],
        signals: LoopSignals,
        hold_s: float,
    ) -> tuple[bool, bool]:
        """Optional breath-hold and recovery. Returns (elevated, returned)."""
        self.loop = "challenge"
        self.gate = "locked"
        self.loop_cue = "Calibration breath-hold. Setup only. The task stays locked."
        self.timer_next = "recovery"
        self.timer_ends_t = self.now() + hold_s
        self.mark("hold", "timer")
        elevated = await self._wait_until(hold_s, lambda: signals.challenge_done(self.now()))

        returned = False
        recovery_cap = float(plan.get("recovery") or 0.0)
        if elevated:
            # The countdown is the longest calibration recovery can run.
            # It ends sooner once flow is back, contact is good, and a
            # decay fit has produced tau. Tau is never taken from this
            # countdown. If the fit never lands, the window still ends.
            self.loop = "locked"
            self.gate = "locked"
            self.loop_cue = (
                "Calibration. Learning how forehead blood flow returns. The task stays locked."
            )
            self.timer_next = "work"
            self.timer_ends_t = self.now() + recovery_cap
            self.mark("recovery", "timer")
            await self._wait_until(recovery_cap, lambda: self._calibration_ready(signals))
            returned = self._perfusion_returned(signals)
            if not returned:
                self.loop = "locked"
                self.gate = "locked"
                self.loop_cue = (
                    "Calibration ended before BFI returned with good contact. "
                    "The task stays locked."
                )
                self._emit_state()
        else:
            dwell = min(NO_ELEVATION_DWELL_S, recovery_cap)
            self.loop = "locked"
            self.gate = "locked"
            self.loop_cue = (
                "No sustained elevation versus baseline. "
                "The task stays locked. Recovery is short so the timer matches."
            )
            self.timer_next = "work"
            self.timer_ends_t = self.now() + dwell
            self.mark("recovery", "timer")
            await self._wait(dwell)
            self.loop_cue = (
                "Calibration complete. Flow never rose, so the work step "
                "stays locked until BFI moves and returns."
            )
            self._emit_state()
        return elevated, returned

    async def _wait(self, seconds: float | None) -> None:
        await self._wait_until(seconds, lambda: False)

    async def _wait_until(
        self,
        seconds: float | None,
        done: Callable[[], bool],
        signals: LoopSignals | None = None,
        *,
        follow: bool = False,
    ) -> bool:
        """Wait up to ``seconds``, or until cancel when ``seconds`` is None.

        ``follow`` copies the gate's task view onto the session while waiting,
        so a breath can start in the middle of a long work bout.
        """
        if seconds is None:
            deadline = None
        else:
            deadline = asyncio.get_running_loop().time() + max(0.0, seconds)
        last: tuple[Any, ...] | None = None
        while True:
            if follow and signals is not None:
                last = self._maybe_follow(signals, last)
            if done():
                return True
            if deadline is None:
                await asyncio.sleep(0.05)
                continue
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                return False
            await asyncio.sleep(min(0.05, remaining))

    def _perfusion_returned(self, signals: LoopSignals) -> bool:
        fn = getattr(signals, "perfusion_returned", None)
        if fn is not None:
            return bool(fn(self.now()))
        return bool(signals.settled(self.now()))

    def _calibration_ready(self, signals: LoopSignals) -> bool:
        """Flow is back, and a decay fit has tau when the gate can report one."""
        if not self._perfusion_returned(signals):
            return False
        fn = getattr(signals, "tau_s", None)
        if fn is None:
            return True
        tau = fn()
        if isinstance(tau, bool) or not isinstance(tau, (int, float)):
            return False
        return tau == tau and abs(tau) != float("inf")

    def _task_view(self, signals: LoopSignals) -> Any:
        fn = getattr(signals, "task_snapshot", None)
        if fn is None:
            return None
        return fn()

    def _maybe_follow(
        self, signals: LoopSignals, last: tuple[Any, ...] | None
    ) -> tuple[Any, ...] | None:
        view = self._task_view(signals)
        if view is None:
            return last
        signature = (view.action, view.difficulty, view.gate_open, view.cue)
        if signature != last:
            self._apply_task_view(view)
        return signature

    def _apply_task_view(self, view: Any) -> None:
        self.loop = {
            "advance": "task",
            "hold": "task",
            "coach": "coach",
            "ease": "ease",
            "break": "break",
        }.get(view.action, "locked")
        self.loop_cue = view.cue
        self.difficulty = int(view.difficulty)
        self.gate = "open" if view.gate_open else "locked"
        self._emit_state()

    # State

    def state(self) -> dict[str, Any]:
        s = self.session
        return {
            "type": "session",
            "t": self.now(),
            "active": s is not None,
            "session_id": s.session_id if s else None,
            "subject_id": s.subject_id if s else "",
            "phase": s.phase if s else None,
            "phase_t": s.phase_t if s else None,
            "timer_next": self.timer_next,
            "timer_ends_t": self.timer_ends_t,
            "loop": self.loop,
            "loop_cue": self.loop_cue,
            "gate": self.gate,
            "difficulty": self.difficulty,
        }

    def _emit_state(self) -> None:
        self.emit([self.state()])

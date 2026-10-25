"""Session and phase logging for the breath-hold protocol.

A session is one sitting with one subject. Phases run baseline, then hold, then
recovery, and may repeat before ``end``. Every phase change is written to
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

PHASES = ("baseline", "hold", "recovery", "end")
NEXT: dict[str | None, set[str]] = {
    None: {"baseline", "end"},
    "baseline": {"hold", "end"},
    "hold": {"recovery", "end"},
    "recovery": {"baseline", "end"},
    "end": set(),
}
DEFAULT_DURATIONS = {"baseline": 60.0, "hold": 30.0, "recovery": 90.0}
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
        """Recovery gate has stayed open: BFI returned and contact still good."""

    # Optional. When present, ``task_snapshot()`` returns an object with
    # ``action``, ``difficulty``, ``gate_open``, and ``cue``. The loop follows
    # it after a real rise. A hold that never rises does not ask.


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
        durations: dict[str, float] | None = None,
        cycles: int = 1,
        *,
        closed_loop: bool = False,
        signals: LoopSignals | None = None,
    ) -> None:
        if self.session is None:
            raise PhaseError("start a session first")
        if self.session.phase not in (None, "recovery"):
            raise PhaseError("the timed protocol starts from a new session or after recovery")
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

    async def _run(self, plan: dict[str, float], cycles: int) -> None:
        steps = [p for _ in range(cycles) for p in ("baseline", "hold", "recovery")]
        for i, phase in enumerate(steps):
            self.timer_next = steps[i + 1] if i + 1 < len(steps) else "end"
            self.timer_ends_t = self.now() + plan[phase]
            self.mark(phase, "timer")
            await asyncio.sleep(plan[phase])
        self.timer_next = self.timer_ends_t = None
        self._timer = None
        self.mark("end", "timer")

    async def _run_closed_loop(
        self, plan: dict[str, float], cycles: int, signals: LoopSignals
    ) -> None:
        """Baseline, breath-hold, then unlock the task only through the recovery gate.

        The hold ends early when elevation has lasted and contact is good enough
        to score. That locks the next step. Recovery coaches a breath until
        forehead BFI has returned and contact is still good. The task then
        follows BFI, BVI, and tau: advance, ease, break, or breathe. A hold
        that never rises does not pretend the gate unlocked.
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
                    "Breathe normally. This sets the resting blood-flow baseline. "
                    "The task stays locked."
                )
                self.timer_next = "hold"
                self.timer_ends_t = self.now() + plan["baseline"]
                self.mark("baseline", "timer")
                await self._wait(plan["baseline"])

                self.loop = "challenge"
                self.gate = "locked"
                self.loop_cue = (
                    "Hold a gentle breath. The next step stays locked until "
                    "forehead BFI returns and contact is good."
                )
                self.timer_next = "recovery"
                self.timer_ends_t = self.now() + plan["hold"]
                self.mark("hold", "timer")
                elevated = await self._wait_until(
                    plan["hold"], lambda: signals.challenge_done(self.now())
                )

                self.timer_next = nxt
                settled = False
                if elevated:
                    # The countdown is the longest the lock can run. It ends
                    # sooner once the recovery gate stays open.
                    recovery_s = plan["recovery"]
                    self.loop = "locked"
                    self.gate = "locked"
                    self.loop_cue = (
                        "Task locked until forehead BFI returns toward baseline. "
                        "Breathe with the circle."
                    )
                    self.timer_ends_t = self.now() + recovery_s
                    self.mark("recovery", "timer")
                    settled = await self._wait_until(
                        recovery_s,
                        lambda: signals.settled(self.now()),
                        signals,
                        follow=True,
                    )
                    if not settled:
                        self.loop = "locked"
                        self.gate = "locked"
                        self.loop_cue = (
                            "Recovery window ended before BFI returned with good contact. "
                            "The task stays locked."
                        )
                        self._emit_state()
                else:
                    dwell = min(NO_ELEVATION_DWELL_S, plan["recovery"])
                    self.loop = "locked"
                    self.gate = "locked"
                    self.loop_cue = (
                        "No sustained elevation versus baseline. "
                        "The task stays locked. Recovery is short so the timer matches."
                    )
                    self.timer_ends_t = self.now() + dwell
                    self.mark("recovery", "timer")
                    await self._wait(dwell)
                    self.loop_cue = "Hold complete. The task stays locked because flow never rose."
                    self._emit_state()

                continue_s = float(plan.get("continue", 3.0))
                self.timer_next = nxt
                self.timer_ends_t = self.now() + continue_s
                # Only a hold that actually rose, and then cleared the recovery
                # gate, gets a task step. A flat hold does not follow the gate
                # into an unlock.
                opened = elevated and settled
                if opened and self._task_view(signals) is not None:
                    self._maybe_follow(signals, None)
                elif opened:
                    self.loop = "task"
                    self.gate = "open"
                    self.loop_cue = "Perfusion-ready. BFI is back and contact is good. Continue."
                    self._emit_state()
                await self._wait_until(
                    continue_s,
                    lambda: False,
                    signals if opened else None,
                    follow=opened,
                )
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

    async def _wait(self, seconds: float) -> None:
        await self._wait_until(seconds, lambda: False)

    async def _wait_until(
        self,
        seconds: float,
        done: Callable[[], bool],
        signals: LoopSignals | None = None,
        *,
        follow: bool = False,
    ) -> bool:
        deadline = asyncio.get_running_loop().time() + max(0.0, seconds)
        last: tuple[Any, ...] | None = None
        while True:
            if follow and signals is not None:
                last = self._maybe_follow(signals, last)
            if done():
                return True
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                return False
            await asyncio.sleep(min(0.05, remaining))

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

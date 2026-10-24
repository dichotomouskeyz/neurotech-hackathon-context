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
from typing import Any

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
EVENT_FIELDS = ["t", "wall_time", "session_id", "phase", "source"]

Emit = Callable[[list[dict[str, Any]]], None]


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

    def start_timer(self, durations: dict[str, float] | None = None, cycles: int = 1) -> None:
        if self.session is None:
            raise PhaseError("start a session first")
        if self.session.phase not in (None, "recovery"):
            raise PhaseError("the timed protocol starts from a new session or after recovery")
        self.cancel_timer()
        plan = {**DEFAULT_DURATIONS, **(durations or {})}
        self._timer = asyncio.get_running_loop().create_task(self._run(plan, cycles))

    def cancel_timer(self) -> None:
        if self._timer is not None and self._timer is not asyncio.current_task():
            self._timer.cancel()
        self._timer = None
        if self.timer_next is not None:
            self.timer_next = self.timer_ends_t = None
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
        }

    def _emit_state(self) -> None:
        self.emit([self.state()])

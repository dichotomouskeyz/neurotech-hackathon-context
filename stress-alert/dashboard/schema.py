"""Message contract between producers (ingest, features, logger) and the dashboard.

Every frame is a JSON object with a ``type`` field. ``t`` is seconds on the shared
clock, LSL ``local_clock()`` (see ``dashboard.clock``). See SCHEMA.md for the
human-readable version.
"""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

Unit = Annotated[float, Field(ge=0.0, le=1.0)]
Cameras = Annotated[list[float | None], Field(min_length=8, max_length=8)]


class _Frame(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Hemo(_Frame):
    """BFI or BVI for the 8 cameras on each side; null for a disabled camera."""

    type: Literal["bfi", "bvi"]
    t: float
    left: Cameras
    right: Cameras


class HeartRate(_Frame):
    type: Literal["hr"]
    t: float
    source: Literal["optical"]
    bpm: Annotated[float, Field(gt=0, lt=300)]


class ContactQuality(_Frame):
    """Per-side contact score. Null means that side has no measurement.

    1.0 is only a real pass of the contact check. Producers must not send 1.0
    to fill in a missing side.
    """

    type: Literal["cq"]
    t: float
    left: Unit | None = None
    right: Unit | None = None


class Stress(_Frame):
    """CQ-gated perfusion change versus the session baseline.

    ``index`` is the larger of the BFI and BVI rises versus each camera's baseline
    median. The live gate scores the responsive cameras, not a mean of every
    camera. ``alert`` is true only when that index clears ``alert_at`` (0.10 by
    default) and contact quality passed. Optical heart rate is a separate ``hr``
    frame and does not set ``alert``. ``channels`` names the cameras in use.
    ``tau_s`` is the recovery time constant, in seconds, once a decay fit succeeds.
    ``gate`` is the work-phase policy: ``open`` only when forehead BFI has
    returned and contact quality passed. Calibration (baseline, optional hold,
    recovery) stays locked.     ``task`` is what that policy does to the step
    (locked, advance, ease, break, coach, or hold). ``gate`` follows the latest
    sample. During work, ``coach`` starts when the 4 second trailing mean of
    the BFI rise is still over the recovery boundary, at least three quarters
    of that window is too, and contact is good. It stays until that mean is
    under half the boundary. A slow recovery tau
    (18 s or more) also coaches while the gate is open. Bad contact stays
    ``locked`` and does not start a breath. ``difficulty`` is the step. ``alert`` stays secondary
    telemetry and does not unlock the task. It is not a stressed-or-not score.
    """

    type: Literal["stress"]
    t: float
    index: float
    recovery_score: float | None = None
    alert: bool = False
    reason: str = ""
    tau_s: float | None = None
    # Relative rise that raises alert. The live gate sends 0.10.
    alert_at: float | None = None
    # Responsive cameras used for the index, for example "BFI L3, L4, R2".
    channels: str = ""
    gate: Literal["open", "locked"] | None = None
    gate_reason: str = ""
    task: Literal["locked", "advance", "ease", "break", "coach", "hold"] | None = None
    difficulty: Annotated[int, Field(ge=1, le=8)] | None = None


PhaseName = Literal["baseline", "hold", "recovery", "work", "end"]
LoopMode = Literal[
    "off",
    "baseline",
    "challenge",
    "coach",
    "continue",
    "locked",
    "task",
    "ease",
    "break",
]


class Phase(_Frame):
    type: Literal["phase"]
    t: float
    session_id: str
    phase: PhaseName
    source: Literal["manual", "timer"]


class Session(_Frame):
    """Current session state, sent by the dashboard itself whenever it changes."""

    type: Literal["session"]
    t: float
    active: bool
    session_id: str | None = None
    subject_id: str = ""
    phase: PhaseName | None = None
    phase_t: float | None = None
    timer_next: PhaseName | None = None
    timer_ends_t: float | None = None
    loop: LoopMode = "off"
    loop_cue: str = ""
    # Recovery gate for the task step. ``off`` when no protocol is driving it.
    gate: Literal["off", "open", "locked"] = "off"
    difficulty: Annotated[int, Field(ge=1, le=8)] = 1


class Device(_Frame):
    """Open-Motion connection and scan state, sent by the dashboard itself."""

    type: Literal["device"]
    t: float
    connected: bool
    console: bool
    left: bool
    right: bool
    scanning: bool
    sdk_version: str = ""
    error: str = ""


class Status(_Frame):
    type: Literal["status"]
    source: str
    connected: bool
    detail: str = ""


Frame = Annotated[
    Hemo | HeartRate | ContactQuality | Stress | Phase | Session | Device | Status,
    Field(discriminator="type"),
]

frame_adapter: TypeAdapter[Frame] = TypeAdapter(Frame)

"""Recovery gate and the task policy it controls.

Calibration (baseline, breath-hold, recovery) learns resting forehead blood
flow and how it returns. The gate stays shut there. The work phase is the
application: the next task step unlocks only when forehead blood flow has
returned toward that baseline and contact quality is high enough to trust the
return. A bad contact score keeps the gate shut. Blood volume and the recovery
time constant change difficulty, ask for a break, or coach a breath. They do
not invent an EEG-style focus score.

The stress label remains secondary telemetry. For research. Not a diagnosis.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

# Same contact floor as the live stress label. At or above this, a side is
# trustworthy enough to score. Below it, the gate stays shut.
CQ_MIN = 0.50
# Relative BFI rise under this counts as returned toward baseline. It sits
# under the 10% elevation line so a trace that is still almost elevated does
# not unlock the task.
BFI_RECOVERED_BELOW = 0.05
# A fitted recovery time constant at or above this is slow. The task eases
# and the breath coach runs. This is a research threshold, not a clinical cutoff.
TAU_POOR_S = 18.0
# Blood-volume rise, once BFI has recovered, eases difficulty. A larger rise
# asks for a break. BFI itself re-locks the gate when it leaves the recovered band.
BVI_EASE = 0.08
BVI_BREAK = 0.12
DIFFICULTY_MIN = 1
DIFFICULTY_MAX = 4


@dataclass(frozen=True)
class GateDecision:
    """Whether the next task step is allowed."""

    open: bool
    bfi_recovered: bool
    cq_ok: bool
    reason: str


@dataclass(frozen=True)
class TaskView:
    """What the dashboard should show for the current policy step."""

    action: str
    difficulty: int
    gate_open: bool
    reason: str
    cue: str


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    if not math.isfinite(number):
        return None
    return number


def evaluate_gate(
    bfi_index: float | None,
    cq: float | None,
    *,
    phase: str = "work",
    recovered_below: float = BFI_RECOVERED_BELOW,
    cq_min: float = CQ_MIN,
) -> GateDecision:
    """Open only during work, and only when BFI has returned and contact is good.

    ``bfi_index`` is the relative forehead blood-flow rise versus baseline.
    ``cq`` is contact quality from 0 to 1. Missing values, a non-finite score,
    and contact below ``cq_min`` all keep the gate closed. Contact of 1.0 can
    be a real light/dark pass. Callers that simulate a headset must not send
    1.0 to fill in a missing measurement.

    Baseline, the breath-hold, and recovery are calibration. They never open
    the gate, even when flow is already back and contact is good.
    """
    cq_value = _number(cq)
    bfi_value = _number(bfi_index)
    cq_ok = cq_value is not None and cq_min <= cq_value <= 1.0
    bfi_recovered = bfi_value is not None and bfi_value < recovered_below

    if phase != "work":
        # Calibration is not the unlock window. Report why the step is
        # waiting, and still refuse to open.
        if not cq_ok:
            reason = "locked_cq"
        elif bfi_value is None:
            reason = "locked_waiting"
        elif not bfi_recovered:
            reason = "locked_bfi"
        else:
            reason = "locked_phase"
        return GateDecision(False, bfi_recovered, cq_ok, reason)

    if not cq_ok:
        return GateDecision(False, bfi_recovered, False, "locked_cq")
    if not bfi_recovered:
        reason = "locked_waiting" if bfi_value is None else "locked_bfi"
        return GateDecision(False, False, True, reason)
    return GateDecision(True, True, True, "open")


def _tau_poor(tau_s: float | None) -> bool:
    tau = _number(tau_s)
    return tau is not None and tau >= TAU_POOR_S


def _cue(action: str, reason: str, difficulty: int, gate_open: bool) -> str:
    if action == "advance":
        return f"Perfusion-ready. BFI is back and contact is good. Task step {difficulty} unlocked."
    if action == "hold":
        return f"Perfusion-ready. Task step {difficulty} is open."
    if action == "coach":
        if gate_open:
            return "Recovery is slow. Ease the task and breathe with the circle."
        return "Recovery is slow. Task stays locked. Breathe with the circle."
    if action == "break":
        return "Blood volume is still up. Take a short break. Difficulty eased."
    if action == "ease":
        return "Blood volume is drifting up. Easing difficulty."
    if reason == "locked_cq":
        return "Task locked. Contact is too poor to call perfusion ready."
    if reason == "locked_bfi":
        return "Task locked until forehead BFI returns toward baseline."
    if reason == "locked_waiting":
        return "Task locked. Waiting for forehead BFI and contact quality."
    if reason == "locked_phase":
        return "Calibration. The task stays locked while resting blood flow is learned."
    return "Task locked. The next step waits until perfusion is ready."


def _view(action: str, difficulty: int, gate: GateDecision, reason: str | None = None) -> TaskView:
    why = gate.reason if reason is None else reason
    return TaskView(action, difficulty, gate.open, why, _cue(action, why, difficulty, gate.open))


class TaskController:
    """One difficulty ladder driven by the recovery gate, BVI, and tau.

    The gate has to be open before difficulty can rise. It rises once per open
    episode. A contact failure, a BFI rise, a high BVI, or a slow tau eases it
    once, until the gate opens again. Calling ``update`` on every frame does
    not walk the ladder by itself.
    """

    def __init__(self) -> None:
        self.difficulty = DIFFICULTY_MIN
        self._advanced_this_open = False
        self._armed_ease = False
        self._view = _view(
            "locked",
            DIFFICULTY_MIN,
            GateDecision(False, False, False, "locked_waiting"),
        )

    @property
    def view(self) -> TaskView:
        return self._view

    def reset(self) -> None:
        self.__init__()

    def update(
        self,
        *,
        bfi_index: float | None,
        bvi_index: float | None,
        cq: float | None,
        tau_s: float | None,
        phase: str = "work",
    ) -> TaskView:
        gate = evaluate_gate(bfi_index, cq, phase=phase)
        bvi = _number(bvi_index)
        if not gate.open:
            self._advanced_this_open = False
            if gate.reason == "locked_bfi" and phase == "work" and _tau_poor(tau_s):
                self._ease_once()
                self._view = _view("coach", self.difficulty, gate, "tau_poor")
            elif gate.reason in {"locked_cq", "locked_bfi"}:
                self._ease_once()
                self._view = _view("locked", self.difficulty, gate)
            else:
                self._view = _view("locked", self.difficulty, gate)
            return self._view

        if _tau_poor(tau_s):
            self._ease_once()
            self._view = _view("coach", self.difficulty, gate, "tau_poor")
            return self._view
        if bvi is not None and bvi >= BVI_BREAK:
            self._ease_once()
            self._view = _view("break", self.difficulty, gate, "bvi_high")
            return self._view
        if bvi is not None and bvi >= BVI_EASE:
            self._ease_once()
            self._view = _view("ease", self.difficulty, gate, "bvi_drift")
            return self._view
        if not self._advanced_this_open:
            self.difficulty = min(DIFFICULTY_MAX, self.difficulty + 1)
            self._advanced_this_open = True
            self._armed_ease = True
            self._view = _view("advance", self.difficulty, gate, "open")
            return self._view
        if self._view.action == "advance" and self._view.gate_open:
            return self._view
        self._view = _view("hold", self.difficulty, gate, "open")
        return self._view

    def _ease_once(self) -> None:
        if self._armed_ease and self.difficulty > DIFFICULTY_MIN:
            self.difficulty -= 1
            self._armed_ease = False

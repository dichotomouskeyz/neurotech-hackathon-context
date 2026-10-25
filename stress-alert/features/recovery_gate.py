"""Recovery gate and the task policy it controls.

Calibration (baseline, optional breath-hold, recovery) learns resting forehead
blood flow and, when a hold is run, how it returns. The gate stays shut there.
The work phase is the application: a longer bout where the next task step
unlocks only when forehead blood flow has returned toward that baseline and
contact quality is high enough to trust the return. The gate tile uses the
latest sample, so it locks as soon as flow crosses the operator line. The
breath coach does not. It follows a trailing mean of that rise and stays on
until the mean is back under half the line, so a brief blip cannot start the
breath and one quiet sample cannot cancel it. A bad contact score keeps the
gate shut and does not start a breath.
Blood volume and the recovery time constant can still ease the step, ask for a
break, or coach a breath. None of this is a stressed-or-not score.

The stress label remains secondary telemetry. For research. Not a diagnosis.
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass

# Same contact floor as the live stress label. At or above this, a side is
# trustworthy enough to score. Below it, the gate stays shut.
CQ_MIN = 0.50
# Relative BFI rise under this counts as returned toward baseline. It sits
# under the 10% elevation line so a trace that is still almost elevated does
# not unlock the task. The operator can set this from the timed-protocol card.
# The floor stays above 0 so a typed 0 cannot make "returned" impossible
# (the live index does not go negative). The cap stays under a doubled trace.
BFI_RECOVERED_BELOW = 0.05
RECOVERED_WITHIN_PCT_MIN = 1.0
RECOVERED_WITHIN_PCT_MAX = 25.0
# Breath coach only. The gate itself stays on the latest sample.
# Four seconds ignores a one- or two-second lock-in blip and still answers
# during a long work bout. The breath starts when that average is on or above
# the operator line and at least three quarters of the window is too, so a
# short spike cannot fill the mean by itself. Exit is half the operator line,
# so once the breath has started a single quiet sample cannot cancel it.
COACH_WINDOW_S = 4.0
COACH_ENTER_FRACTION = 0.75
COACH_EXIT_FRACTION = 0.5
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


def parse_recovered_within_pct(percent: float) -> float:
    """Turn an operator percent into the relative rise the gate compares.

    ``5`` means forehead BFI is back when its rise is under 5% of baseline.
    Values outside 1 to 25 are rejected so the gate cannot be stuck shut or
    opened by any rise.
    """
    number = _number(percent)
    if number is None or number < RECOVERED_WITHIN_PCT_MIN or number > RECOVERED_WITHIN_PCT_MAX:
        raise ValueError(
            "BFI within baseline must be from "
            f"{RECOVERED_WITHIN_PCT_MIN:.0f} to {RECOVERED_WITHIN_PCT_MAX:.0f} percent"
        )
    return number / 100.0


def parse_recovered_below(fraction: float) -> float:
    """Accept a relative rise already in the same units as ``bfi_index``."""
    number = _number(fraction)
    lo = RECOVERED_WITHIN_PCT_MIN / 100.0
    hi = RECOVERED_WITHIN_PCT_MAX / 100.0
    if number is None or number < lo or number > hi:
        raise ValueError(
            "BFI within baseline must be from "
            f"{RECOVERED_WITHIN_PCT_MIN:.0f} to {RECOVERED_WITHIN_PCT_MAX:.0f} percent"
        )
    return number


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
        if reason == "coach_mean":
            return (
                "Keep breathing with the circle. The latest sample may already be back. "
                "The breath stays until the average forehead flow is back."
            )
        if gate_open:
            return "Recovery is slow. Ease the task and breathe with the circle."
        if reason == "locked_bfi":
            return (
                "Forehead blood flow is off the calibrated baseline and contact is good. "
                "Breathe with the circle. The task stays locked until flow returns."
            )
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
    once, until the gate opens again. During work, the breath coach follows the
    trailing mean of the forehead BFI rise. The gate open flag stays on the
    latest sample. Calling ``update`` on every frame does not walk the ladder
    by itself.
    """

    def __init__(
        self,
        *,
        coach_window_s: float = COACH_WINDOW_S,
        coach_exit_fraction: float = COACH_EXIT_FRACTION,
        coach_enter_fraction: float = COACH_ENTER_FRACTION,
    ) -> None:
        self.difficulty = DIFFICULTY_MIN
        self.coach_window_s = coach_window_s
        self.coach_exit_fraction = coach_exit_fraction
        self.coach_enter_fraction = coach_enter_fraction
        self._advanced_this_open = False
        self._armed_ease = False
        self._window: deque[tuple[float, float]] = deque()
        self._coaching = False
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
        recovered_below: float = BFI_RECOVERED_BELOW,
        t: float | None = None,
    ) -> TaskView:
        gate = evaluate_gate(bfi_index, cq, phase=phase, recovered_below=recovered_below)
        sustained = self._breath_sustained(
            t,
            bfi_index,
            gate.cq_ok,
            phase,
            recovered_below,
        )
        bvi = _number(bvi_index)
        if not gate.open:
            self._advanced_this_open = False
            # The tile locks on this sample. The breath waits for the mean.
            if gate.reason == "locked_bfi" and phase == "work" and sustained:
                self._ease_once()
                self._coaching = True
                self._view = _view("coach", self.difficulty, gate, "locked_bfi")
            elif gate.reason == "locked_cq" and self._coaching:
                # A brief contact blip locks the tile and does not cancel the breath.
                self._view = _view("coach", self.difficulty, gate)
            elif gate.reason in {"locked_cq", "locked_bfi"}:
                self._coaching = False
                self._ease_once()
                self._view = _view("locked", self.difficulty, gate)
            else:
                self._view = _view("locked", self.difficulty, gate)
            return self._view

        if sustained:
            # Latest sample is back inside the line. Keep the breath until the
            # mean exits, and leave the gate open so the tile recovers at once.
            self._view = _view("coach", self.difficulty, gate, "coach_mean")
            return self._view
        self._coaching = False

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

    def _breath_sustained(
        self,
        t: float | None,
        bfi_index: float | None,
        cq_ok: bool,
        phase: str,
        recovered_below: float,
    ) -> bool:
        """True while the trailing mean of forehead BFI rise should keep the breath.

        Samples older than ``coach_window_s`` drop out. The breath starts once
        the samples on hand span that window, the mean is on or above the
        operator line, and most of those samples are too. A steady cadence
        never stores a point exactly on the cutoff, so the span may sit a
        fraction of a second under the window and still count. The breath
        stops once the mean is under ``coach_exit_fraction`` of the line. A
        sample with poor contact is not added, so a brief lock-in blip does
        not start the breath and does not wipe the window. No clock means no
        breath from this path.
        """
        if phase != "work" or t is None or not math.isfinite(float(t)):
            self._window.clear()
            self._coaching = False
            return False
        now = float(t)
        if cq_ok:
            value = _number(bfi_index)
            if value is not None:
                self._window.append((now, value))
        cutoff = now - self.coach_window_s
        while self._window and self._window[0][0] < cutoff:
            self._window.popleft()
        if len(self._window) < 2:
            self._coaching = False
            return False
        mean = sum(value for _sample_t, value in self._window) / len(self._window)
        over = sum(1 for _sample_t, value in self._window if value >= recovered_below)
        span = self._window[-1][0] - self._window[0][0]
        # One sample interval inside a 4 s window is still the trailing window.
        full = span + 0.5 >= self.coach_window_s
        exit_line = recovered_below * self.coach_exit_fraction
        if self._coaching:
            if mean < exit_line:
                self._coaching = False
        elif (
            full
            and mean >= recovered_below
            and over / len(self._window) + 1e-9 >= self.coach_enter_fraction
        ):
            self._coaching = True
        return self._coaching

    def _ease_once(self) -> None:
        if self._armed_ease and self.difficulty > DIFFICULTY_MIN:
            self.difficulty -= 1
            self._armed_ease = False

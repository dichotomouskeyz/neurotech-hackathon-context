"""Recovery gate: closed unless forehead BFI has returned and contact is good."""

import pytest

from features.recovery_gate import (
    BVI_BREAK,
    BVI_EASE,
    TAU_POOR_S,
    TaskController,
    evaluate_gate,
)


def test_gate_stays_closed_when_contact_is_bad_even_if_bfi_is_back():
    decision = evaluate_gate(0.0, 0.30, phase="work")
    assert decision.open is False
    assert decision.cq_ok is False
    assert decision.bfi_recovered is True
    assert decision.reason == "locked_cq"


def test_gate_stays_closed_when_bfi_has_not_returned():
    decision = evaluate_gate(0.18, 0.86, phase="work")
    assert decision.open is False
    assert decision.cq_ok is True
    assert decision.bfi_recovered is False
    assert decision.reason == "locked_bfi"


def test_gate_opens_only_when_bfi_recovered_and_contact_is_good():
    closed = evaluate_gate(0.0, 0.49, phase="work")
    opened = evaluate_gate(0.04, 0.50, phase="work")
    assert closed.open is False
    assert opened.open is True
    assert opened.reason == "open"
    # Missing measurements fail closed. A real 1.0 pass is allowed; Demo Mode
    # must not use it as a filler.
    assert evaluate_gate(0.0, None, phase="work").open is False
    assert evaluate_gate(None, 0.9, phase="work").open is False
    assert evaluate_gate(0.0, 1.0, phase="work").open is True


def test_gate_does_not_open_before_the_recovery_window():
    ready = evaluate_gate(0.0, 0.9, phase="hold")
    assert ready.open is False
    assert ready.bfi_recovered is True
    assert ready.cq_ok is True


def test_calibration_stays_locked_even_when_bfi_and_contact_are_ready():
    for phase in ("baseline", "hold", "recovery"):
        decision = evaluate_gate(0.0, 0.9, phase=phase)
        assert decision.open is False
        assert decision.reason == "locked_phase"
    task = TaskController()
    view = task.update(bfi_index=0.0, bvi_index=0.0, cq=0.9, tau_s=30.0, phase="recovery")
    assert view.gate_open is False
    assert view.action == "locked"
    assert view.difficulty == 1


def test_task_advances_once_when_the_gate_opens_and_holds():
    task = TaskController()
    first = task.update(bfi_index=0.02, bvi_index=0.01, cq=0.8, tau_s=None, phase="work")
    second = task.update(bfi_index=0.02, bvi_index=0.01, cq=0.8, tau_s=8.0, phase="work")
    assert first.gate_open is True
    assert first.action == "advance"
    assert first.difficulty == 2
    assert "unlocked" in first.cue
    assert second.gate_open is True
    assert second.action == "advance"
    assert second.difficulty == 2


def test_bad_contact_or_a_new_bfi_rise_locks_and_eases():
    task = TaskController()
    task.update(bfi_index=0.01, bvi_index=0.01, cq=0.82, tau_s=None, phase="work")
    blocked = task.update(bfi_index=0.01, bvi_index=0.01, cq=0.22, tau_s=None, phase="work")
    assert blocked.gate_open is False
    assert blocked.action == "locked"
    assert blocked.reason == "locked_cq"
    assert blocked.difficulty == 1

    task.update(bfi_index=0.01, bvi_index=0.01, cq=0.8, tau_s=None, phase="work")
    risen = task.update(bfi_index=0.2, bvi_index=0.01, cq=0.8, tau_s=None, phase="work")
    assert risen.gate_open is False
    assert risen.reason == "locked_bfi"
    assert risen.difficulty == 1


def test_slow_tau_coaches_a_breath_and_eases_without_closing_a_recovered_gate():
    task = TaskController()
    task.update(bfi_index=0.01, bvi_index=0.01, cq=0.8, tau_s=None, phase="work")
    coached = task.update(
        bfi_index=0.01,
        bvi_index=0.01,
        cq=0.8,
        tau_s=TAU_POOR_S,
        phase="work",
    )
    assert coached.gate_open is True
    assert coached.action == "coach"
    assert coached.difficulty == 1
    assert "breathe" in coached.cue.lower()
    # A fast tau does not coach. Rebuild so the open episode can advance again.
    fresh = TaskController()
    steady = fresh.update(bfi_index=0.01, bvi_index=0.01, cq=0.8, tau_s=6.0, phase="work")
    assert steady.action == "advance"


def test_blood_volume_dynamics_ease_or_break_while_bfi_stays_recovered():
    task = TaskController()
    task.update(bfi_index=0.01, bvi_index=0.01, cq=0.8, tau_s=None, phase="work")
    eased = task.update(
        bfi_index=0.02,
        bvi_index=BVI_EASE,
        cq=0.8,
        tau_s=6.0,
        phase="work",
    )
    assert eased.gate_open is True
    assert eased.action == "ease"
    assert eased.difficulty == 1

    task.update(bfi_index=0.01, bvi_index=0.01, cq=0.8, tau_s=None, phase="work")
    paused = task.update(
        bfi_index=0.02,
        bvi_index=BVI_BREAK,
        cq=0.8,
        tau_s=6.0,
        phase="work",
    )
    assert paused.action == "break"
    assert paused.gate_open is True
    assert "break" in paused.cue.lower()


def test_a_slow_tau_while_bfi_is_still_up_coaches_without_unlocking():
    task = TaskController()
    view = task.update(bfi_index=0.25, bvi_index=0.04, cq=0.8, tau_s=30.0, phase="work")
    assert view.gate_open is False
    assert view.action == "coach"
    assert "stays locked" in view.cue


def test_difficulty_does_not_fall_before_it_has_advanced():
    task = TaskController()
    view = task.update(bfi_index=0.4, bvi_index=0.2, cq=0.2, tau_s=40.0, phase="work")
    assert view.difficulty == 1
    assert view.gate_open is False


@pytest.mark.parametrize(
    ("bfi", "cq", "open_"),
    [(0.0, 0.2, False), (0.3, 0.95, False), (0.02, 0.7, True)],
)
def test_gate_table(bfi, cq, open_):
    assert evaluate_gate(bfi, cq, phase="work").open is open_

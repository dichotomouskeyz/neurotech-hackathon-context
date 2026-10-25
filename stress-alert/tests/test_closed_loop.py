"""Closed loop: stop the hold when perfusion is elevated, continue when it settles."""

import asyncio
import contextlib

import pytest

from dashboard.live_gate import LiveGate
from session.phase_logger import NO_ELEVATION_DWELL_S, PhaseLogger


class _Hot:
    def challenge_done(self, now):
        return True

    def settled(self, now):
        return True


class _Quiet:
    def challenge_done(self, now):
        return False

    def settled(self, now):
        return False


def _cues(frames):
    return [frame.get("loop_cue", "") for frame in frames if frame["type"] == "session"]


async def test_closed_loop_coaches_on_elevation_then_continues(tmp_path):
    frames = []
    log = PhaseLogger(tmp_path, emit=frames.extend)
    log.start_session("loop")
    log.start_timer(
        {"baseline": 0.02, "hold": 0.4, "recovery": 0.4, "continue": 0.02},
        closed_loop=True,
        signals=_Hot(),
    )
    await asyncio.sleep(0.4)
    assert [event["phase"] for event in log.session.events] == [
        "baseline",
        "hold",
        "recovery",
        "end",
    ]
    cues = _cues(frames)
    assert any("Pause the hold" in cue for cue in cues)
    assert any("settled" in cue for cue in cues)
    assert log.loop == "off"


async def test_closed_loop_does_not_invent_elevation(tmp_path):
    frames = []
    log = PhaseLogger(tmp_path, emit=frames.extend)
    log.start_session("flat")
    log.start_timer(
        {"baseline": 0.02, "hold": 0.02, "recovery": 0.02, "continue": 0.02},
        closed_loop=True,
        signals=_Quiet(),
    )
    await asyncio.sleep(0.4)
    cues = _cues(frames)
    assert not any("Pause the hold" in cue for cue in cues)
    assert any("No sustained elevation" in cue for cue in cues)
    assert [event["phase"] for event in log.session.events][-1] == "end"


def _recovery_frame(frames):
    for frame in frames:
        if frame["type"] == "session" and frame.get("phase") == "recovery":
            return frame
    return None


async def test_no_elevation_recovery_countdown_matches_the_short_dwell(tmp_path):
    """A hold that never alerts must not show a long recovery it will not run."""
    frames = []
    log = PhaseLogger(tmp_path, emit=frames.extend)
    log.start_session("quiet-timer")
    log.start_timer(
        {"baseline": 0.02, "hold": 0.02, "recovery": 15.0, "continue": 0.02},
        closed_loop=True,
        signals=_Quiet(),
    )
    recovery = None
    for _ in range(40):
        await asyncio.sleep(0.02)
        recovery = _recovery_frame(frames)
        if recovery is not None:
            break
    assert recovery is not None
    assert "No sustained elevation" in recovery["loop_cue"]
    span = recovery["timer_ends_t"] - recovery["phase_t"]
    assert span == pytest.approx(NO_ELEVATION_DWELL_S, abs=0.05)
    assert span < 15.0
    task = log._timer
    log.cancel_timer()
    if task is not None:
        with contextlib.suppress(asyncio.CancelledError):
            await task


async def test_elevated_recovery_countdown_is_the_full_window(tmp_path):
    """When the hold does alert, the countdown is the recovery the operator typed."""
    frames = []
    log = PhaseLogger(tmp_path, emit=frames.extend)
    log.start_session("hot-timer")
    log.start_timer(
        {"baseline": 0.02, "hold": 15.0, "recovery": 15.0, "continue": 0.02},
        closed_loop=True,
        signals=_Hot(),
    )
    recovery = None
    for _ in range(40):
        await asyncio.sleep(0.02)
        recovery = _recovery_frame(frames)
        if recovery is not None:
            break
    assert recovery is not None
    assert "Pause the hold" in recovery["loop_cue"]
    assert "settles" in recovery["loop_cue"]
    span = recovery["timer_ends_t"] - recovery["phase_t"]
    assert span == pytest.approx(15.0, abs=0.05)
    for _ in range(30):
        if log.session is not None and log.session.phase == "end":
            break
        await asyncio.sleep(0.02)
    assert log.session.phase == "end"
    assert any("settled" in cue for cue in _cues(frames))


def _batch(t, level, cq):
    cams = [level] * 8
    return [
        {"type": "bfi", "t": t, "left": cams, "right": cams},
        {"type": "bvi", "t": t, "left": cams, "right": cams},
        {"type": "cq", "t": t, "left": cq, "right": cq},
    ]


async def test_gate_stops_the_hold_and_continues_when_settled(tmp_path):
    gate = LiveGate(stress_hold_s=0.4, settle_hold_s=0.4, settle_index=0.12)
    frames = []

    def emit(batch):
        frames.extend(batch)
        frames.extend(gate.observe(batch))

    log = PhaseLogger(tmp_path, emit=emit)
    log.start_session("live")
    log.start_timer(
        {"baseline": 0.3, "hold": 1.0, "recovery": 1.0, "continue": 0.05},
        closed_loop=True,
        signals=gate,
    )
    while log.session.phase != "baseline":
        await asyncio.sleep(0.01)
    for i in range(6):
        gate.observe(_batch(10.0 + i * 0.3, 2.0, 0.95))
    while log.session.phase != "hold":
        await asyncio.sleep(0.01)
    for i in range(4):
        gate.observe(_batch(30.0 + i * 0.4, 3.0, 0.95))
    while log.session.phase != "recovery":
        await asyncio.sleep(0.01)
    assert any("Pause the hold" in cue for cue in _cues(frames))
    for i in range(6):
        gate.observe(_batch(40.0 + i * 0.4, 2.02, 0.95))
    for _ in range(40):
        if log.session.phase == "end":
            break
        await asyncio.sleep(0.05)
    assert log.session.phase == "end"
    assert any("settled" in cue for cue in _cues(frames))

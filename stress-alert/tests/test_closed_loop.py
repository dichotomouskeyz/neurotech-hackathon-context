"""Closed loop: stop the hold when perfusion is elevated, continue when it settles."""

import asyncio

from dashboard.live_gate import LiveGate
from session.phase_logger import PhaseLogger


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

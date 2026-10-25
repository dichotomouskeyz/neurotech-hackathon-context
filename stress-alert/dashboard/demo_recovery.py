"""Scripted BFI, BVI, and contact stimulus for recovery-gate tests.

Not the dashboard Demo Mode. Demo Mode and ``--dev-feed`` both replay
``data/sample_scan.csv`` through :func:`dashboard.dev_feed.replay`.

This curve is a short baseline, breath-hold, and recovery, then a work window.
Contact quality stays below 1.00 so the gate tests can tell a real miss from a
filled-in perfect score. Nothing in the server calls it.
"""

from __future__ import annotations

import asyncio
import math
from collections.abc import Callable
from typing import Any

from dashboard import clock
from features.recovery_gate import BVI_BREAK

BASE_BFI = 2.0
BASE_BVI = 5.0
HOLD_PEAK = 2.70
RAMP_S = 0.8
# Fast return during calibration so setup stays short. Tau learned here is not
# the work-loop load.
CALIB_DECAY_TAU_S = 1.4
# Work starts already above baseline (the person has been at the task), then
# decays. Flow stays up for 3 s so the breath coach, which needs about 4 s of
# trailing mean, starts before BFI returns.
WORK_PEAK = 2.50
WORK_DECAY_TAU_S = 1.2
WORK_DECAY_START_S = 3.0
WORK_BVI_START_S = 9.4
WORK_CQ_DIP_START_S = 10.8
WORK_CQ_DIP_END_S = 12.2
DEMO_HZ = 20.0
# About 28 s end to end. The hold ends about 1.5 s in, once the rise has held.
# Recovery ends at about 10 s, the shortest window the tau fit accepts. Work
# shows the coach, the unlock, the volume break, the contact lock, the re-open.
DEMO_DURATIONS = {
    "baseline": 2.5,
    "hold": 6.0,
    "recovery": 14.0,
    "work": 13.6,
    "continue": 13.6,
}


def demo_sample(phase: str | None, elapsed: float) -> tuple[float, float, float]:
    """Return ``(bfi, bvi, cq)`` for one moment of the script.

    ``cq`` is always in ``[0, 1)``. This stimulus does not publish 1.00.
    """
    elapsed = max(0.0, float(elapsed))
    if phase == "hold":
        span = min(1.0, elapsed / RAMP_S)
        return (
            BASE_BFI + (HOLD_PEAK - BASE_BFI) * span,
            BASE_BVI + 0.15 * span,
            0.78,
        )
    if phase == "recovery":
        decay = math.exp(-elapsed / CALIB_DECAY_TAU_S)
        return (
            BASE_BFI + (HOLD_PEAK - BASE_BFI) * decay,
            BASE_BVI + 0.15 * decay,
            0.76,
        )
    if phase == "work":
        if elapsed < WORK_DECAY_START_S:
            return WORK_PEAK, BASE_BVI * 1.03, 0.80
        if elapsed < WORK_BVI_START_S:
            decay = math.exp(-(elapsed - WORK_DECAY_START_S) / WORK_DECAY_TAU_S)
            return (
                BASE_BFI + (WORK_PEAK - BASE_BFI) * decay,
                BASE_BVI + BASE_BVI * 0.03 * decay,
                0.78,
            )
        if elapsed < WORK_CQ_DIP_START_S:
            # Flow is back. Volume is still up, so the open gate eases or breaks
            # instead of treating volume as another lock.
            return BASE_BFI * 1.01, BASE_BVI * (1.0 + BVI_BREAK), 0.76
        if elapsed < WORK_CQ_DIP_END_S:
            return BASE_BFI, BASE_BVI, 0.32
        return BASE_BFI, BASE_BVI, 0.74
    return BASE_BFI, BASE_BVI, 0.82


def demo_frames(phase: str | None, elapsed: float, t: float) -> list[dict[str, Any]]:
    """BFI, BVI, and contact frames for one demo sample. CQ is below 1.00."""
    bfi, bvi, cq = demo_sample(phase, elapsed)
    if not math.isfinite(cq) or cq < 0.0 or cq >= 1.0:
        raise ValueError("demo contact quality must be in [0, 1)")
    return [
        {"type": "bfi", "t": t, "left": [bfi] * 8, "right": [bfi] * 8},
        {"type": "bvi", "t": t, "left": [bvi] * 8, "right": [bvi] * 8},
        {"type": "cq", "t": t, "left": cq, "right": cq},
    ]


async def run_recovery_demo(
    publish: Callable[[list[dict[str, Any]]], None],
    phase_of: Callable[[], str | None],
    scanning: Callable[[], bool],
    *,
    now: Callable[[], float] = clock.now,
    hz: float = DEMO_HZ,
) -> str:
    """Publish the script until the session ends, the task is cancelled, or a scan starts.

    Returns ``"end"`` or ``"scan"``. A live scan stops the script so it cannot
    overwrite headset contact quality. Cancellation propagates. The dashboard
    does not call this; Demo Mode uses ``dashboard.dev_feed.replay``.
    """
    period = 1.0 / hz
    phase_t0: float | None = None
    last_phase: str | None = None
    try:
        while True:
            if scanning():
                return "scan"
            phase = phase_of()
            if phase == "end":
                return "end"
            t = now()
            if phase != last_phase:
                phase_t0 = t
                last_phase = phase
            elapsed = 0.0 if phase_t0 is None else max(0.0, t - phase_t0)
            publish(demo_frames(phase, elapsed, t))
            await asyncio.sleep(period)
    except asyncio.CancelledError:
        raise

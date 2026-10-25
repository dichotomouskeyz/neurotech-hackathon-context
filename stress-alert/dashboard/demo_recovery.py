"""Scripted recovery for Demo Mode.

The trace rises, decays back toward the resting blood-flow level, and later
drops contact quality while flow is already back. The recovery gate should
unlock on the decay and lock again on the contact drop.

Contact quality here is a graded score below 1.00. A live scan is a different
path: light and dark digital numbers, and this script must not run over it.
"""

from __future__ import annotations

import asyncio
import math
from collections.abc import Callable
from typing import Any

from dashboard import clock

BASE_BFI = 2.0
BASE_BVI = 5.0
HOLD_PEAK = 2.70
RAMP_S = 0.8
DECAY_TAU_S = 4.5
# While recovery has already brought BFI back, contact falls through the floor
# so the gate has to close again. It then returns to a good score that is
# still not 1.00.
CQ_DIP_START_S = 16.0
CQ_DIP_END_S = 20.0
DEMO_HZ = 20.0
DEMO_DURATIONS = {
    "baseline": 6.0,
    "hold": 8.0,
    "recovery": 24.0,
    "continue": 12.0,
}


def demo_sample(phase: str | None, elapsed: float) -> tuple[float, float, float]:
    """Return ``(bfi, bvi, cq)`` for one moment of the scripted recovery.

    ``cq`` is always in ``[0, 1)``. Demo Mode does not publish 1.00.
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
        decay = math.exp(-elapsed / DECAY_TAU_S)
        bfi = BASE_BFI + (HOLD_PEAK - BASE_BFI) * decay
        bvi = BASE_BVI + 0.15 * decay
        if CQ_DIP_START_S <= elapsed < CQ_DIP_END_S:
            cq = 0.32
        elif elapsed >= CQ_DIP_END_S:
            cq = 0.74
        else:
            cq = 0.76
        return bfi, bvi, cq
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

    Returns ``"end"`` or ``"scan"``. A live scan stops the script so Demo Mode
    cannot overwrite headset contact quality. Cancellation propagates.
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

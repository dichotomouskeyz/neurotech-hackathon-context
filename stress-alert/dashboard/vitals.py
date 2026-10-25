"""Live optical heart rate from the Open-Motion blood flow stream.

``HeartRateEstimator`` listens to ``bfi`` frames on the hub, from the connected
device or from replay, keeps a rolling window of each side's camera mean, and
once a second runs Lane 1's ``estimate_optical_hr`` (FFT peak between 0.7 and
3.0 Hz) on it. It publishes an ``hr`` frame only when the estimate is confident;
otherwise it publishes nothing rather than a guessed value.

For research. An optical estimate, not checked against a reference heart rate.
"""

import math
from collections import deque
from collections.abc import Callable
from typing import Any

from dashboard import clock
from features.pulse_hr import estimate_optical_hr

Emit = Callable[[list[dict[str, Any]]], None]


def _side_mean(values: list[float | None]) -> float:
    finite = [v for v in values if v is not None and math.isfinite(v)]
    return sum(finite) / len(finite) if finite else math.nan


class HeartRateEstimator:
    def __init__(
        self,
        publish: Emit,
        *,
        window_s: float = 12.0,
        min_confidence: float = 0.7,
        now: Callable[[], float] = clock.now,
    ) -> None:
        self._publish = publish
        self.window_s = window_s
        self.min_confidence = min_confidence
        self._now = now
        self._t: deque[float] = deque()
        self._left: deque[float] = deque()
        self._right: deque[float] = deque()

    def feed(self, frames: list[dict[str, Any]]) -> None:
        """Hub listener: buffer side means from every ``bfi`` frame."""
        for frame in frames:
            if frame.get("type") != "bfi":
                continue
            t = float(frame["t"])
            if self._t and t <= self._t[-1]:
                continue  # the estimator needs strictly increasing time
            self._t.append(t)
            self._left.append(_side_mean(frame["left"]))
            self._right.append(_side_mean(frame["right"]))
        while self._t and self._t[-1] - self._t[0] > self.window_s:
            self._t.popleft()
            self._left.popleft()
            self._right.popleft()

    def tick(self) -> dict[str, Any] | None:
        """Estimate now; publish and return an ``hr`` frame if it is confident."""
        if len(self._t) < 2 or not self._has_variation():
            return None
        estimate = estimate_optical_hr(list(self._t), list(self._left), bfi_right=list(self._right))
        if estimate.bpm is None or (estimate.confidence or 0.0) < self.min_confidence:
            return None
        frame = {
            "type": "hr",
            "t": self._t[-1],
            "source": "optical",
            "bpm": round(float(estimate.bpm), 1),
            "confidence": round(float(estimate.confidence), 3),
            "window_s": round(float(estimate.duration_s), 1),
        }
        self._publish([frame])
        return frame

    def _has_variation(self, min_std: float = 1e-3) -> bool:
        """A flat trace (a dark, saturated, or frozen camera) has no pulse.

        Without this check the FFT of floating-point residue after detrending can
        report a confident but meaningless peak.
        """
        for side in (self._left, self._right):
            finite = [v for v in side if math.isfinite(v)]
            if len(finite) > 1:
                mean = sum(finite) / len(finite)
                var = sum((v - mean) ** 2 for v in finite) / len(finite)
                if math.sqrt(var) >= min_std:
                    return True
        return False

"""Optical heart rate from an Open-Motion BFI trace.

BFI carries a systemic pulse on top of slower blood-flow changes. This
estimator removes a linear trend and a 1.5 s moving mean, then takes the
peak frequency of what remains inside 0.7 to 3.0 Hz (42 to 180 bpm).

Limitations, for research:

- One dominant rate over the whole clip. Not beat-to-beat intervals, and not
  heart-rate variability.
- Not checked against a reference heart rate. Do not report it as a clinical
  heart rate.
- Clips shorter than about 8 seconds are rejected. A few clean cycles are
  required before the peak is stable.
- Motion, bad coupling, and a weak pulse move or flatten the peak. Gate on
  ``cq_score`` before trusting a window.
- The search band leaves out typical respiration (around 0.2 Hz). A strong
  non-cardiac oscillation inside the band is reported as if it were pulse.
- Sample rate comes from timestamps. Open-Motion light frames are 40 Hz.
  Pass left and right together; finite samples are averaged per time point.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from scipy.signal import detrend


@dataclass(frozen=True)
class HrEstimate:
    """Dominant-frequency heart-rate estimate from a BFI residual."""

    bpm: float | None
    rate_hz: float | None
    confidence: float | None
    method: str
    n_samples: int
    duration_s: float
    note: str

    @property
    def ok(self) -> bool:
        return self.bpm is not None


def estimate_optical_hr(
    timestamps_s,
    bfi,
    *,
    bfi_right=None,
    f_min: float = 0.7,
    f_max: float = 3.0,
    min_duration_s: float = 8.0,
) -> HrEstimate:
    """Estimate a single optical heart rate in beats per minute.

    ``bfi`` is a 1-D trace (already a side average, or any single BFI series).
    ``bfi_right`` is optional. Missing samples may be ``NaN``.

    ``confidence`` is in-band peak power divided by peak power plus the
    in-band median, so it sits on 0 to 1. A sharp tone is near 1. A flat
    band is near 0.5, and the estimator returns no bpm in that case
    (peak under twice the median).
    """
    if f_min <= 0 or f_max <= f_min:
        raise ValueError("need 0 < f_min < f_max")
    timestamps = np.asarray(timestamps_s, dtype=float)
    values = _combine(bfi, bfi_right)
    if timestamps.shape != values.shape:
        raise ValueError("timestamps and bfi must have the same length")
    finite = np.isfinite(timestamps) & np.isfinite(values)
    timestamps = timestamps[finite]
    values = values[finite]
    n_samples = int(timestamps.size)
    if n_samples < 2:
        return _empty(n_samples, 0.0, "not enough finite samples")
    duration_s = float(timestamps[-1] - timestamps[0])
    if duration_s < min_duration_s:
        return _empty(
            n_samples,
            duration_s,
            f"need at least {min_duration_s:.0f}s of BFI",
        )
    steps = np.diff(timestamps)
    if np.any(steps <= 0):
        return _empty(n_samples, duration_s, "timestamps must increase")
    sample_rate_hz = float(1.0 / np.median(steps))
    if not 5.0 <= sample_rate_hz <= 500.0:
        return _empty(
            n_samples,
            duration_s,
            f"sample rate {sample_rate_hz:.2f} Hz is outside 5 to 500",
        )
    if float(np.max(np.abs(steps - np.median(steps)))) > 0.05 * float(np.median(steps)):
        timestamps, values, sample_rate_hz = _resample(timestamps, values, sample_rate_hz)
        n_samples = int(timestamps.size)
        duration_s = float(timestamps[-1] - timestamps[0])

    nyquist_hz = 0.5 * sample_rate_hz
    if f_min >= nyquist_hz:
        return _empty(n_samples, duration_s, "pulse band is above the Nyquist rate")
    band_hi = min(f_max, 0.45 * sample_rate_hz)

    residual = detrend(values, type="linear")
    residual = _remove_moving_mean(residual, sample_rate_hz, window_s=1.5)
    edge = max(1, int(round(sample_rate_hz * 1.5)))
    if residual.size <= 2 * edge + 16:
        return _empty(n_samples, duration_s, "series too short after detrend")
    residual = residual[edge:-edge]
    residual = residual - float(np.mean(residual))

    nfft = 1 << int(math.ceil(math.log2(max(residual.size * 4, 256))))
    window = np.hanning(residual.size)
    spectrum = np.abs(np.fft.rfft(residual * window, n=nfft)) ** 2
    freqs = np.fft.rfftfreq(nfft, d=1.0 / sample_rate_hz)
    band = (freqs >= f_min) & (freqs <= band_hi)
    if not np.any(band):
        return _empty(n_samples, duration_s, "pulse band is empty at this sample rate")
    band_freqs = freqs[band]
    band_power = spectrum[band]
    peak_index = int(np.argmax(band_power))
    peak_hz = _parabolic_peak(band_freqs, band_power, peak_index)
    peak_hz = min(band_hi, max(f_min, peak_hz))
    peak_power = float(band_power[peak_index])
    median_power = float(np.median(band_power))
    if median_power > 0:
        confidence = float(peak_power / (peak_power + median_power))
        clear_peak = peak_power >= 2.0 * median_power
    elif peak_power > 0:
        confidence = 1.0
        clear_peak = True
    else:
        confidence = 0.0
        clear_peak = False
    if not clear_peak:
        return HrEstimate(
            bpm=None,
            rate_hz=None,
            confidence=confidence,
            method="fft",
            n_samples=n_samples,
            duration_s=duration_s,
            note="no clear peak in the pulse band",
        )
    return HrEstimate(
        bpm=peak_hz * 60.0,
        rate_hz=peak_hz,
        confidence=confidence,
        method="fft",
        n_samples=n_samples,
        duration_s=duration_s,
        note="dominant frequency in the BFI residual; research estimate only",
    )


def _empty(n_samples: int, duration_s: float, note: str) -> HrEstimate:
    return HrEstimate(
        bpm=None,
        rate_hz=None,
        confidence=None,
        method="fft",
        n_samples=n_samples,
        duration_s=duration_s,
        note=note,
    )


def _combine(bfi, bfi_right) -> np.ndarray:
    left = np.asarray(bfi, dtype=float)
    if bfi_right is None:
        return left
    right = np.asarray(bfi_right, dtype=float)
    if left.shape != right.shape:
        raise ValueError("bfi and bfi_right must have the same length")
    stacked = np.vstack([left, right])
    finite = np.isfinite(stacked)
    counts = finite.sum(axis=0)
    totals = np.where(finite, stacked, 0.0).sum(axis=0)
    combined = np.full(left.shape, np.nan, dtype=float)
    good = counts > 0
    combined[good] = totals[good] / counts[good]
    return combined


def _resample(
    timestamps: np.ndarray, values: np.ndarray, sample_rate_hz: float
) -> tuple[np.ndarray, np.ndarray, float]:
    start = float(timestamps[0])
    stop = float(timestamps[-1])
    count = int(math.floor((stop - start) * sample_rate_hz)) + 1
    grid = start + np.arange(count, dtype=float) / sample_rate_hz
    grid = grid[grid <= stop]
    resampled = np.interp(grid, timestamps, values)
    return grid, resampled, sample_rate_hz


def _remove_moving_mean(values: np.ndarray, sample_rate_hz: float, window_s: float) -> np.ndarray:
    window = max(3, int(round(sample_rate_hz * window_s)))
    if window % 2 == 0:
        window += 1
    kernel = np.ones(window, dtype=float) / window
    pad = window // 2
    padded = np.pad(values, pad, mode="edge")
    baseline = np.convolve(padded, kernel, mode="valid")
    if baseline.size != values.size:
        baseline = baseline[: values.size]
    return values - baseline


def _parabolic_peak(freqs: np.ndarray, power: np.ndarray, index: int) -> float:
    if index <= 0 or index >= len(power) - 1:
        return float(freqs[index])
    left, center, right = (float(power[index - 1]), float(power[index]), float(power[index + 1]))
    denom = left - 2.0 * center + right
    if denom == 0.0:
        return float(freqs[index])
    delta = 0.5 * (left - right) / denom
    delta = min(1.0, max(-1.0, delta))
    bin_hz = float(freqs[1] - freqs[0]) if len(freqs) > 1 else 0.0
    return float(freqs[index] + delta * bin_hz)

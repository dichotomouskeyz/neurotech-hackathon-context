"""Optical heart rate from an Open-Motion BFI trace.

BFI carries a systemic pulse on top of slower blood-flow changes. This
estimator removes a linear trend and a 1.5 s moving mean, then finds the
pulse rate inside 0.7 to 3.0 Hz (42 to 180 bpm). The strongest line in
that band is the default. A faster peak near twice that rate replaces it
when the faster peak has a harmonic of its own and the slower line does
not look like a pulse. A pulse that really sits near 50 bpm stays there.

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
  non-cardiac oscillation inside the band is reported as if it were pulse,
  unless a faster peak near twice that rate has its own harmonic.
- Sample rate comes from timestamps. Open-Motion light frames are 40 Hz.
  Stamps closer than about half a light frame are treated as the same
  capture and collapsed, so a second copy does not set the rate. A uniform
  slower cadence is kept as recorded. Pass left and right together; finite
  samples are averaged per time point.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from scipy.signal import detrend

# Open-Motion light frames. Used only to drop a second stamp of one capture.
_LIGHT_FRAME_HZ = 40.0
_MIN_FRAME_S = 0.45 / _LIGHT_FRAME_HZ
# A slow line is not a pulse when its third harmonic is this weak.
_THIRD_HARMONIC_RATIO = 0.05
# The faster peak must be a real tone, not a sidelobe of the slow line.
_FASTER_POWER_RATIO = 0.10
# And it needs its own second harmonic, the way a pulse does.
_FASTER_HARMONIC_RATIO = 0.25
# Half-rate residuals are not exact octaves. Search this far around 2f.
_OCTAVE_TOLERANCE = 0.12


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

    When the tallest line is a slow tone and a peak near twice that
    frequency has its own harmonic, the faster peak is the one reported.
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
    timestamps, values = _collapse_repeat_captures(timestamps, values)
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
    band_index = np.flatnonzero(band)
    band_power = spectrum[band]
    peak_index = int(band_index[int(np.argmax(band_power))])
    median_power = float(np.median(band_power))
    faster = _faster_fundamental(freqs, spectrum, peak_index, band_hi, median_power)
    if faster is not None:
        peak_index = faster
    peak_hz = _parabolic_peak(freqs, spectrum, peak_index)
    peak_hz = min(band_hi, max(f_min, peak_hz))
    peak_power = float(spectrum[peak_index])
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


def _collapse_repeat_captures(
    timestamps: np.ndarray, values: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """Drop extra stamps of one light frame.

    A second copy of the same capture arrives microseconds later. The median
    gap would then be that copy, and the sample rate would be nonsense.
    Uniform spacing, including a steady rate below 40 Hz, is unchanged.
    """
    if timestamps.size < 3:
        return timestamps, values
    steps = np.diff(timestamps)
    if float(np.median(steps)) >= _MIN_FRAME_S or not np.any(steps >= _MIN_FRAME_S):
        return timestamps, values
    keep = [0]
    last = float(timestamps[0])
    for index in range(1, int(timestamps.size)):
        if float(timestamps[index]) - last >= _MIN_FRAME_S:
            keep.append(index)
            last = float(timestamps[index])
    chosen = np.asarray(keep, dtype=int)
    return timestamps[chosen], values[chosen]


def _power_near(freqs: np.ndarray, power: np.ndarray, hz: float) -> float:
    index = int(np.argmin(np.abs(freqs - hz)))
    lo = max(0, index - 1)
    hi = min(int(power.size), index + 2)
    return float(np.max(power[lo:hi]))


def _faster_fundamental(
    freqs: np.ndarray,
    power: np.ndarray,
    peak_index: int,
    band_hi: float,
    median_power: float,
) -> int | None:
    """Index of the cardiac peak when the tallest line is a half-rate tone.

    A pulsatile trace has a third harmonic. A sine near half the pulse rate
    does not. The faster peak has to carry a harmonic of its own before it
    replaces the tall line, so a real slow pulse is left alone.
    """
    slow_hz = float(freqs[peak_index])
    slow_power = float(power[peak_index])
    if slow_power <= 0.0 or slow_hz <= 0.0:
        return None
    if _power_near(freqs, power, 3.0 * slow_hz) >= _THIRD_HARMONIC_RATIO * slow_power:
        return None
    lo = 2.0 * slow_hz * (1.0 - _OCTAVE_TOLERANCE)
    hi = min(band_hi, 2.0 * slow_hz * (1.0 + _OCTAVE_TOLERANCE))
    if hi <= lo:
        return None
    best: int | None = None
    best_power = 0.0
    nyquist = float(freqs[-1]) if freqs.size else 0.0
    for index in range(1, int(power.size) - 1):
        hz = float(freqs[index])
        if hz < lo or hz > hi:
            continue
        height = float(power[index])
        if height < power[index - 1] or height < power[index + 1]:
            continue
        if height < _FASTER_POWER_RATIO * slow_power:
            continue
        if median_power > 0.0 and height < 2.0 * median_power:
            continue
        harmonic_hz = 2.0 * hz
        if harmonic_hz >= nyquist:
            continue
        if _power_near(freqs, power, harmonic_hz) < _FASTER_HARMONIC_RATIO * height:
            continue
        if height > best_power:
            best = index
            best_power = height
    return best


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

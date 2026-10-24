"""Heart rate and a narrow HRV set from a single-lead ECG. For research.

NeuroKit2 ``ecg_process`` cleans the trace, finds R peaks, and interpolates
a per-sample rate (``ECG_Rate``). ``hrv_time`` then reports:

- ``HRV_MeanNN``: mean RR interval in milliseconds. Mean heart rate in bpm
  is 60000 divided by that value.
- ``HRV_SDNN``: standard deviation of RR intervals, milliseconds.
- ``HRV_RMSSD``: root mean square of successive RR differences, milliseconds.

Longer-window indices (SDANN and the frequency-domain set) are omitted.
They need minutes of data and are the wrong scope for this demo.

Limitations, for research:

- One clip-level rate plus an interpolated trace for plotting. This is a
  research cross-check for the optical rate from BFI, and a recovery
  feature after the breath-hold task.
- Clips shorter than 8 seconds are rejected.
- The sample rate passed to NeuroKit2 is the median timestamp step, rounded
  to an integer Hz. Explorepy does not store the rate, and the device clock
  can drift. This function does not resample.
- Motion, a loose lead, or a channel that is not ECG will move the peaks.
- These figures are not a clinical heart-rate or HRV measurement.
"""

from __future__ import annotations

from dataclasses import dataclass
import math

import neurokit2 as nk
import numpy as np


class EcgFeatureError(ValueError):
    """NeuroKit2 could not produce a heart-rate estimate from this clip."""


@dataclass(frozen=True)
class EcgSummary:
    """Clip-level ECG rate and the two HRV numbers the demo keeps."""

    duration_s: float
    sample_rate_hz: float
    hr_bpm_mean: float | None
    hrv_mean_nn_ms: float | None
    hrv_sdnn_ms: float | None
    hrv_rmssd_ms: float | None
    n_peaks: int
    note: str


def analyze_ecg(
    timestamps_s,
    ecg_uv,
    *,
    sampling_rate_hz: float | None = None,
    min_duration_s: float = 8.0,
) -> tuple[EcgSummary, np.ndarray]:
    """Return clip metrics and a per-sample heart-rate trace in bpm.

    The trace lines up with ``timestamps_s``. Missing rates are NaN.
    """
    timestamps = np.asarray(timestamps_s, dtype=float)
    values = np.asarray(ecg_uv, dtype=float)
    if timestamps.shape != values.shape:
        raise ValueError("timestamps and ecg must have the same length")
    finite = np.isfinite(timestamps) & np.isfinite(values)
    timestamps = timestamps[finite]
    values = values[finite]
    if timestamps.size < 2:
        raise EcgFeatureError("not enough finite ECG samples")
    duration_s = float(timestamps[-1] - timestamps[0])
    if duration_s < min_duration_s:
        raise EcgFeatureError(f"need at least {min_duration_s:.0f}s of ECG")
    steps = np.diff(timestamps)
    if np.any(steps <= 0):
        raise EcgFeatureError("timestamps must increase")
    if sampling_rate_hz is None:
        sampling_rate_hz = float(1.0 / np.median(steps[steps > 0]))
    if not 50.0 <= float(sampling_rate_hz) <= 2000.0:
        raise EcgFeatureError(
            f"sample rate {float(sampling_rate_hz):.2f} Hz is outside 50 to 2000"
        )
    rate_hz = int(round(float(sampling_rate_hz)))
    try:
        signals, info = nk.ecg_process(values, sampling_rate=rate_hz)
        hrv = nk.hrv_time(info, sampling_rate=rate_hz)
    except Exception as exc:
        raise EcgFeatureError(f"NeuroKit2 could not process this ECG: {exc}") from exc
    peaks = info.get("ECG_R_Peaks", [])
    n_peaks = int(len(peaks))
    mean_nn = _metric(hrv, "HRV_MeanNN")
    sdnn = _metric(hrv, "HRV_SDNN")
    rmssd = _metric(hrv, "HRV_RMSSD")
    if mean_nn is not None and mean_nn > 0:
        hr_bpm = 60000.0 / mean_nn
        note = "mean RR from NeuroKit2 hrv_time; research estimate only"
    else:
        hr_bpm = _mean_positive(signals["ECG_Rate"].to_numpy(dtype=float))
        note = "mean of the interpolated ECG_Rate trace; research estimate only"
    if hr_bpm is None or n_peaks < 3:
        raise EcgFeatureError("no reliable R peaks in this ECG clip")
    per_sample = _align_rate(signals["ECG_Rate"].to_numpy(dtype=float), finite)
    return (
        EcgSummary(
            duration_s=duration_s,
            sample_rate_hz=float(sampling_rate_hz),
            hr_bpm_mean=hr_bpm,
            hrv_mean_nn_ms=mean_nn,
            hrv_sdnn_ms=sdnn,
            hrv_rmssd_ms=rmssd,
            n_peaks=n_peaks,
            note=note,
        ),
        per_sample,
    )


def _align_rate(rate_on_finite: np.ndarray, finite: np.ndarray) -> np.ndarray:
    """Map the NeuroKit rate, computed on finite samples, back to input length."""
    aligned = np.full(finite.shape, np.nan, dtype=float)
    if rate_on_finite.shape[0] != int(finite.sum()):
        raise EcgFeatureError("NeuroKit2 returned a heart-rate trace of the wrong length")
    aligned[finite] = rate_on_finite
    return aligned


def _metric(frame, name: str) -> float | None:
    if name not in frame.columns:
        return None
    value = float(frame[name].iloc[0])
    if not math.isfinite(value):
        return None
    return value


def _mean_positive(values: np.ndarray) -> float | None:
    usable = values[np.isfinite(values) & (values > 0)]
    if usable.size == 0:
        return None
    return float(np.mean(usable))

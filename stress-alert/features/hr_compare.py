"""Compare an optical heart rate with an ECG heart rate. For research.

Lane 1 prints one ``optical_hr_bpm`` for a BFI clip. Lane 2 prints one
``hr_bpm_mean`` for the ECG clip. ``compare_hr`` is the pitch cross-check:
absolute difference, and that difference as a percent of the ECG rate.

``compare_hr_windows`` does the same on shared time windows when both
signals already have per-sample rates and a shared clock. Lane 1's
side-average CSV does not carry a per-sample optical rate. Aligning the
Open-Motion clock with the Explore ``TimeStamp`` is the sync lane.

A small difference supports the demo story. It is not agreement with a
clinical monitor, and it is not a validation claim.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class HrCompare:
    """Absolute and percent difference between two clip-level rates."""

    optical_bpm: float
    ecg_bpm: float
    abs_diff_bpm: float
    pct_diff: float


@dataclass(frozen=True)
class HrWindowCompare:
    """The same difference on one shared time window."""

    t_start_s: float
    t_end_s: float
    optical_bpm: float
    ecg_bpm: float
    abs_diff_bpm: float
    pct_diff: float


def compare_hr(optical_bpm: float, ecg_bpm: float) -> HrCompare:
    """Compare two finite rates. Percent uses the ECG rate as the denominator."""
    optical = float(optical_bpm)
    ecg = float(ecg_bpm)
    if not math.isfinite(optical) or not math.isfinite(ecg):
        raise ValueError("heart rates must be finite")
    if ecg == 0.0:
        raise ValueError("ECG heart rate must be non-zero")
    diff = abs(optical - ecg)
    return HrCompare(
        optical_bpm=optical,
        ecg_bpm=ecg,
        abs_diff_bpm=diff,
        pct_diff=100.0 * diff / abs(ecg),
    )


def compare_hr_windows(
    optical_t,
    optical_hr,
    ecg_t,
    ecg_hr,
    *,
    window_s: float = 10.0,
) -> list[HrWindowCompare]:
    """Mean optical rate versus mean ECG rate on successive windows.

    Windows cover the overlap of the two clocks, each ``window_s`` long,
    with a shorter tail kept when it still has samples on both sides.
    An empty overlap returns an empty list.
    """
    optical_times = np.asarray(optical_t, dtype=float)
    optical_rates = np.asarray(optical_hr, dtype=float)
    ecg_times = np.asarray(ecg_t, dtype=float)
    ecg_rates = np.asarray(ecg_hr, dtype=float)
    if optical_times.shape != optical_rates.shape or ecg_times.shape != ecg_rates.shape:
        raise ValueError("timestamps and heart-rate traces must have the same length")
    if window_s <= 0:
        raise ValueError("window_s must be positive")
    if optical_times.size == 0 or ecg_times.size == 0:
        return []
    t_start = max(float(np.nanmin(optical_times)), float(np.nanmin(ecg_times)))
    t_end = min(float(np.nanmax(optical_times)), float(np.nanmax(ecg_times)))
    if not t_end > t_start:
        return []
    rows: list[HrWindowCompare] = []
    cursor = t_start
    while cursor < t_end - 1e-9:
        stop = min(cursor + window_s, t_end)
        optical_mean = _window_mean(optical_times, optical_rates, cursor, stop, t_end)
        ecg_mean = _window_mean(ecg_times, ecg_rates, cursor, stop, t_end)
        if optical_mean is not None and ecg_mean is not None and ecg_mean != 0.0:
            compared = compare_hr(optical_mean, ecg_mean)
            rows.append(
                HrWindowCompare(
                    t_start_s=cursor,
                    t_end_s=stop,
                    optical_bpm=compared.optical_bpm,
                    ecg_bpm=compared.ecg_bpm,
                    abs_diff_bpm=compared.abs_diff_bpm,
                    pct_diff=compared.pct_diff,
                )
            )
        cursor = stop
    return rows


def _window_mean(
    times: np.ndarray,
    values: np.ndarray,
    start: float,
    stop: float,
    overlap_end: float,
) -> float | None:
    if stop >= overlap_end - 1e-9:
        inside = (times >= start) & (times <= stop)
    else:
        inside = (times >= start) & (times < stop)
    usable = values[inside & np.isfinite(values)]
    if usable.size == 0:
        return None
    return float(np.mean(usable))

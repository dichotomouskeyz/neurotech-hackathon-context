"""Replay a Mentalab Explore ExG CSV. Live explorepy stays behind a flag.

explorepy ``record_data(..., file_type='csv')`` writes ``{file_name}_ExG.csv``
with one header row and no units row. Columns are ``TimeStamp`` (seconds)
then each enabled channel ``ch1``, ``ch2``, ... in microvolts (uV). That
layout is ``create_exg_recorder`` in explorepy's ``tools.py``. The sampling
rate is not a column. Explore devices use 250, 500, or 1000 Hz, and the
device rate can drift, so callers should take the rate from timestamps.

This reader also accepts ``timestamp_s`` and ``ecg_uv`` for a file the team
already renamed. When several ``ch*`` columns exist and no ECG name is
given, it uses the lowest channel number (usually ``ch1``). Pass ``channel``
to pick another lead. Orientation files (``ax``, ``ay``, ...) are rejected.

For research. This module does not interpret the trace as a diagnosis.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
import csv
import re

import numpy as np
import pandas as pd

ECG_TRACE_COLUMNS = ("timestamp_s", "ecg_uv", "hr_bpm")
ECG_METRICS_COLUMNS = (
    "duration_s",
    "sample_rate_hz",
    "channel",
    "hr_bpm_mean",
    "hrv_mean_nn_ms",
    "hrv_sdnn_ms",
    "hrv_rmssd_ms",
    "n_peaks",
)

_TIMESTAMP_NAMES = ("timestamp_s", "timestamp", "time_s", "time", "TimeStamp")
_ECG_NAMES = ("ecg_uv", "ecg")
_CHANNEL_PATTERN = re.compile(r"ch(\d+)$", re.IGNORECASE)


class MentalabCsvError(ValueError):
    """The file is not an Explore ExG CSV this reader can use."""


@dataclass(frozen=True)
class EcgRecording:
    """One ECG lead and its timestamps, in file order."""

    timestamps_s: np.ndarray
    ecg_uv: np.ndarray
    channel: str


def read_ecg_csv(path: str | Path, *, channel: str | None = None) -> EcgRecording:
    """Load one ECG lead from an Explore ``*_ExG.csv`` or a renamed equivalent."""
    csv_path = Path(path)
    if not csv_path.is_file():
        raise MentalabCsvError(f"ECG CSV not found: {csv_path}")
    try:
        frame = pd.read_csv(csv_path, encoding="utf-8-sig")
    except pd.errors.ParserError as exc:
        raise MentalabCsvError(f"could not parse CSV: {exc}") from exc
    except OSError as exc:
        raise MentalabCsvError(f"could not read CSV: {exc}") from exc
    if frame.empty:
        raise MentalabCsvError("ECG CSV has no samples")
    frame.columns = [str(name).strip() for name in frame.columns]
    timestamp_col = _pick_timestamp(frame.columns)
    ecg_col = _pick_ecg(frame.columns, channel)
    timestamps = pd.to_numeric(frame[timestamp_col], errors="coerce").to_numpy(dtype=float)
    values = pd.to_numeric(frame[ecg_col], errors="coerce").to_numpy(dtype=float)
    finite = np.isfinite(timestamps) & np.isfinite(values)
    timestamps = timestamps[finite]
    values = values[finite]
    if timestamps.size == 0:
        raise MentalabCsvError("ECG CSV has no numeric timestamp and ECG samples")
    if timestamps.size > 1 and np.any(np.diff(timestamps) <= 0):
        raise MentalabCsvError("ECG timestamps must increase")
    return EcgRecording(
        timestamps_s=timestamps,
        ecg_uv=values,
        channel=ecg_col,
    )


def estimate_sample_rate_hz(timestamps_s: Sequence[float] | np.ndarray) -> float:
    """Median sample rate from timestamps. Explore does not store the rate."""
    timestamps = np.asarray(timestamps_s, dtype=float)
    if timestamps.size < 2:
        raise MentalabCsvError("need at least two samples to estimate the sample rate")
    steps = np.diff(timestamps)
    steps = steps[steps > 0]
    if steps.size == 0:
        raise MentalabCsvError("timestamps must increase")
    return float(1.0 / np.median(steps))


def write_ecg_trace(
    path: str | Path,
    timestamps_s: Sequence[float],
    ecg_uv: Sequence[float],
    hr_bpm: Sequence[float],
) -> None:
    """Write the dashboard trace: timestamp_s, ecg_uv, hr_bpm.

    ``hr_bpm`` is the per-sample rate (blank where it is missing). Clip-level
    HRV belongs in the metrics CSV, not on every row.
    """
    timestamps = list(timestamps_s)
    values = list(ecg_uv)
    rates = list(hr_bpm)
    if not (len(timestamps) == len(values) == len(rates)):
        raise ValueError("trace columns must have the same length")
    out_path = Path(path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=ECG_TRACE_COLUMNS)
        writer.writeheader()
        for timestamp, sample, rate in zip(timestamps, values, rates):
            writer.writerow(
                {
                    "timestamp_s": _format_float(timestamp),
                    "ecg_uv": _format_float(sample),
                    "hr_bpm": _format_float(rate),
                }
            )


def write_ecg_metrics(
    path: str | Path,
    *,
    duration_s: float,
    sample_rate_hz: float,
    channel: str,
    hr_bpm_mean: float | None,
    hrv_mean_nn_ms: float | None,
    hrv_sdnn_ms: float | None,
    hrv_rmssd_ms: float | None,
    n_peaks: int,
) -> None:
    """Write one row of clip-level heart rate and HRV."""
    out_path = Path(path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=ECG_METRICS_COLUMNS)
        writer.writeheader()
        writer.writerow(
            {
                "duration_s": _format_float(duration_s),
                "sample_rate_hz": _format_float(sample_rate_hz),
                "channel": channel,
                "hr_bpm_mean": _format_float(hr_bpm_mean),
                "hrv_mean_nn_ms": _format_float(hrv_mean_nn_ms),
                "hrv_sdnn_ms": _format_float(hrv_sdnn_ms),
                "hrv_rmssd_ms": _format_float(hrv_rmssd_ms),
                "n_peaks": str(int(n_peaks)),
            }
        )


def start_live_ecg(
    *,
    file_name: str,
    device_name: str | None = None,
    mac_address: str | None = None,
    duration_sec: float | None = 60,
    overwrite: bool = False,
    allow_live: bool = False,
):
    """Record an Explore device to CSV and return the ``explorepy.Explore`` instance.

    Refuses to run unless ``allow_live=True``. CSV replay does not import
    explorepy. The device must already be paired. Bluetooth name looks like
    ``Explore_XXXX``.

    When ``duration_sec`` is set, ``record_data`` blocks until that many
    seconds are written. The ECG file is ``{file_name}_ExG.csv`` with
    ``TimeStamp`` and ``ch*`` columns. Replay that file with ``read_ecg_csv``.
    """
    if not allow_live:
        raise RuntimeError(
            "Live Mentalab is gated. Pass allow_live=True only when an Explore "
            "device is paired. Offline work should replay an ExG CSV."
        )
    if not device_name and not mac_address:
        raise ValueError("pass device_name or mac_address")
    explorepy = _import_explorepy()
    explore = explorepy.Explore()
    if device_name:
        explore.connect(device_name=device_name)
    else:
        explore.connect(mac_address=mac_address)
    explore.record_data(
        file_name=file_name,
        duration=duration_sec,
        file_type="csv",
        do_overwrite=overwrite,
    )
    return explore


def _import_explorepy():
    try:
        import explorepy
    except ImportError as exc:
        raise ImportError(
            "explorepy is not installed. CSV replay does not need it. "
            "On the machine with the Explore device: pip install explorepy"
        ) from exc
    return explorepy


def _pick_timestamp(columns) -> str:
    found = _match_name(columns, _TIMESTAMP_NAMES)
    if found is None:
        raise MentalabCsvError(
            "ECG CSV needs a TimeStamp or timestamp_s column "
            "(explorepy *_ExG.csv uses TimeStamp)"
        )
    return found


def _pick_ecg(columns, channel: str | None) -> str:
    if channel:
        found = _match_name(columns, (channel,))
        if found is None:
            raise MentalabCsvError(f"ECG column {channel!r} is not in the CSV")
        return found
    named = _match_name(columns, _ECG_NAMES)
    if named is not None:
        return named
    numbered = []
    for name in columns:
        match = _CHANNEL_PATTERN.fullmatch(str(name).strip())
        if match:
            numbered.append((int(match.group(1)), str(name).strip()))
    if not numbered:
        raise MentalabCsvError(
            "no ECG column found; expected ch1 (microvolts) from an explorepy "
            "*_ExG.csv, or ecg_uv. Orientation files are a different export."
        )
    numbered.sort()
    return numbered[0][1]


def _match_name(columns, names: tuple[str, ...]) -> str | None:
    by_lower = {str(column).strip().lower(): str(column).strip() for column in columns}
    for name in names:
        found = by_lower.get(name.lower())
        if found is not None:
            return found
    return None


def _format_float(value: float | None) -> str:
    if value is None:
        return ""
    number = float(value)
    if not np.isfinite(number):
        return ""
    return f"{number:.6f}"

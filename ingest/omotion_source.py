"""Read a corrected Open-Motion scan CSV and stream side averages.

Primary path is offline replay. A corrected scan CSV has ``frame_id``,
``timestamp_s``, then per-camera columns ``bfi_l1``..``bfi_l8``,
``bfi_r1``..``bfi_r8``, and the same pattern for ``bvi``, ``mean``,
``contrast``, ``temp``, and ``quality``. That is the header of
``openmotion-bloodflow-app/resources/sample_scan.csv`` (98 columns).
Extra columns are ignored. ``quality_*`` may be absent: a later SDK change
kept quality on the scan database and dropped it from the corrected CSV.
When those columns are missing, ``cq`` is left blank.

Side averages match the SDK side average: the mean of finite cameras on
that side. Blank cells and ``NaN`` values are omitted from that mean.
``window_s`` greater than 0 replaces each row with a trailing mean over
that many seconds. The default is one row per frame, which is what other
lanes should replay when they need the pulse.

Output CSV columns for teammates: ``timestamp_s,bfi_l,bfi_r,bvi_l,bvi_r,cq``.

Live path: ``start_live_scan`` imports ``MotionInterface`` and ``ScanRequest``
only when ``allow_live=True``. ``demo_mode`` is refused. On 2026-10-24 a Mac
check of ``MotionInterface(demo_mode=True)`` wrote a telemetry CSV and no
BFI/BVI frames (see docs/OPEN-MOTION.md). Prefer this CSV replay off the
station. Live hardware is the Windows host. This module does not change
laser power or any safety-critical optical output.

For research.
"""

from __future__ import annotations

import csv
from collections import deque
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from features.cq_score import DEFAULT_BAD_BELOW, cq_score

SIDE_CSV_COLUMNS = ("timestamp_s", "bfi_l", "bfi_r", "bvi_l", "bvi_r", "cq")
_CAMERAS = range(1, 9)
_SIDES = ("l", "r")


class ScanCsvError(ValueError):
    """The file is not a corrected Open-Motion scan CSV this reader can use."""


@dataclass(frozen=True)
class SideAverage:
    """One time point of left/right BFI and BVI, plus contact quality."""

    frame_id: int | None
    timestamp_s: float
    bfi_l: float | None
    bfi_r: float | None
    bvi_l: float | None
    bvi_r: float | None
    cq: float | None
    bad_coupling: bool | None


def iter_side_averages(path: str | Path, *, window_s: float = 0.0) -> Iterator[SideAverage]:
    """Yield side averages in file order.

    The CSV is loaded, then rows are yielded. Hackathon scans are short
    enough that a full read is simpler than a streaming parser.
    """
    yield from replay_scan(path, window_s=window_s)


def replay_scan(path: str | Path, *, window_s: float = 0.0) -> list[SideAverage]:
    """Return per-frame side averages, optionally trailing-averaged."""
    return apply_window(read_side_frames(path), window_s)


def read_side_frames(path: str | Path) -> list[SideAverage]:
    """Per-frame side means from a corrected scan CSV. No temporal window."""
    csv_path = Path(path)
    if not csv_path.is_file():
        raise ScanCsvError(f"scan CSV not found: {csv_path}")
    try:
        frame = pd.read_csv(csv_path, encoding="utf-8-sig")
    except pd.errors.ParserError as exc:
        raise ScanCsvError(f"could not parse CSV: {exc}") from exc
    except OSError as exc:
        raise ScanCsvError(f"could not read CSV: {exc}") from exc
    if frame.empty:
        return []
    frame.columns = [str(name).strip() for name in frame.columns]
    if "timestamp_s" not in frame.columns:
        raise ScanCsvError("corrected scan CSV needs a timestamp_s column")

    bfi_l = _metric_columns(frame.columns, "bfi", "l")
    bfi_r = _metric_columns(frame.columns, "bfi", "r")
    if not bfi_l and not bfi_r:
        raise ScanCsvError("no BFI columns found; expected bfi_l1..bfi_l8 and bfi_r1..bfi_r8")
    bvi_l = _metric_columns(frame.columns, "bvi", "l")
    bvi_r = _metric_columns(frame.columns, "bvi", "r")
    quality_columns = [
        f"quality_{side}{cam}"
        for side in _SIDES
        for cam in _CAMERAS
        if f"quality_{side}{cam}" in frame.columns
    ]

    timestamps = pd.to_numeric(frame["timestamp_s"], errors="coerce").to_numpy(dtype=float)
    frame_ids = (
        pd.to_numeric(frame["frame_id"], errors="coerce").to_numpy(dtype=float)
        if "frame_id" in frame.columns
        else np.full(len(frame), np.nan)
    )
    bfi_l_mean = _side_means(frame, bfi_l)
    bfi_r_mean = _side_means(frame, bfi_r)
    bvi_l_mean = _side_means(frame, bvi_l)
    bvi_r_mean = _side_means(frame, bvi_r)
    quality_rows = _quality_rows(frame, quality_columns)

    rows: list[SideAverage] = []
    for index in range(len(frame)):
        timestamp = timestamps[index]
        if not np.isfinite(timestamp):
            continue
        labels = quality_rows[index]
        if labels:
            scored = cq_score(labels)
            cq: float | None = scored.score
            bad: bool | None = scored.bad_coupling
        else:
            cq = None
            bad = None
        rows.append(
            SideAverage(
                frame_id=_as_int(frame_ids[index]),
                timestamp_s=float(timestamp),
                bfi_l=_finite(bfi_l_mean[index]),
                bfi_r=_finite(bfi_r_mean[index]),
                bvi_l=_finite(bvi_l_mean[index]),
                bvi_r=_finite(bvi_r_mean[index]),
                cq=cq,
                bad_coupling=bad,
            )
        )
    return rows


def apply_window(rows: Sequence[SideAverage], window_s: float) -> list[SideAverage]:
    """Trailing mean. ``window_s`` of 0 returns a copy of ``rows``.

    Each output row is stamped with the last frame in the window, so a live
    consumer can append one row per input frame.
    """
    if window_s < 0:
        raise ValueError("window_s must be >= 0")
    if window_s == 0:
        return list(rows)
    window: deque[SideAverage] = deque()
    averaged: list[SideAverage] = []
    for row in rows:
        window.append(row)
        while len(window) > 1 and row.timestamp_s - window[0].timestamp_s > window_s:
            window.popleft()
        averaged.append(_average_window(window, row))
    return averaged


def write_side_csv(rows: Sequence[SideAverage], path: str | Path) -> None:
    """Write the teammate replay CSV. Blank cells mean a missing value."""
    out_path = Path(path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=SIDE_CSV_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "timestamp_s": _format_float(row.timestamp_s),
                    "bfi_l": _format_float(row.bfi_l),
                    "bfi_r": _format_float(row.bfi_r),
                    "bvi_l": _format_float(row.bvi_l),
                    "bvi_r": _format_float(row.bvi_r),
                    "cq": _format_float(row.cq),
                }
            )


def start_live_scan(
    *,
    data_dir: str,
    subject_id: str = "phantom-01",
    duration_sec: float = 60,
    operator_id: str = "stress-alert",
    demo_mode: bool = False,
    allow_live: bool = False,
):
    """Start a station scan and return the ``MotionInterface``.

    Refuses to run unless ``allow_live=True``. Refuses ``demo_mode`` because
    that mode did not emit BFI/BVI in the 2026-10-24 check. The corrected CSV
    is written under ``data_dir`` when no scan database is configured. Stop
    the interface with ``iface.stop()`` after ``scan_workflow.await_complete()``.

    This does not set laser power. Follow ``scripts/sdk_examples.py`` on the
    station host if a scan needs the laser enabled, and do not change
    safety-critical optical output.
    """
    if not allow_live:
        raise RuntimeError(
            "Live Open-Motion is gated. Pass allow_live=True only on the "
            "Windows station host. Offline work should replay a corrected scan CSV."
        )
    if demo_mode:
        raise RuntimeError(
            "MotionInterface(demo_mode=True) did not emit BFI/BVI in the "
            "2026-10-24 Mac check (telemetry CSV only). Replay a corrected "
            "scan CSV instead of demo_mode."
        )
    motion_interface, scan_request = _import_live_types()
    interface = motion_interface(data_dir=data_dir, operator_id=operator_id)
    interface.start(wait=True, wait_timeout=3.0)
    started = interface.start_scan(
        scan_request(
            subject_id=subject_id,
            duration_sec=duration_sec,
            left_camera_mask=0xFF,
            right_camera_mask=0xFF,
        )
    )
    if not started:
        error = getattr(interface.scan_workflow, "last_scan_error", None)
        interface.stop()
        raise RuntimeError(error or "start_scan was refused")
    return interface


def _import_live_types():
    try:
        from omotion import MotionInterface
        from omotion.ScanWorkflow import ScanRequest
    except ImportError as exc:
        raise ImportError(
            "openmotion-sdk is not installed. CSV replay does not need it. "
            "On the station host: pip install openmotion-sdk"
        ) from exc
    return MotionInterface, ScanRequest


def _metric_columns(columns, metric: str, side: str) -> list[str]:
    names = [f"{metric}_{side}{cam}" for cam in _CAMERAS]
    return [name for name in names if name in columns]


def _side_means(frame: pd.DataFrame, columns: list[str]) -> np.ndarray:
    if not columns:
        return np.full(len(frame), np.nan)
    numeric = pd.DataFrame(
        {name: pd.to_numeric(frame[name], errors="coerce") for name in columns}
    ).to_numpy(dtype=float)
    finite = np.isfinite(numeric)
    counts = finite.sum(axis=1)
    totals = np.where(finite, numeric, 0.0).sum(axis=1)
    means = np.full(len(frame), np.nan)
    good = counts > 0
    means[good] = totals[good] / counts[good]
    return means


def _quality_rows(frame: pd.DataFrame, columns: list[str]) -> list[list[str]]:
    if not columns:
        return [[] for _ in range(len(frame))]
    rows: list[list[str]] = []
    for record in frame.loc[:, columns].itertuples(index=False, name=None):
        labels: list[str] = []
        for value in record:
            if value is None or (isinstance(value, float) and np.isnan(value)):
                continue
            text = str(value).strip()
            if text and text.lower() != "nan":
                labels.append(text)
        rows.append(labels)
    return rows


def _average_window(window: Sequence[SideAverage], end: SideAverage) -> SideAverage:
    cq_values = [row.cq for row in window if row.cq is not None]
    if cq_values:
        cq = float(sum(cq_values) / len(cq_values))
        bad: bool | None = cq < DEFAULT_BAD_BELOW
    else:
        cq = None
        bad = None
    return SideAverage(
        frame_id=end.frame_id,
        timestamp_s=end.timestamp_s,
        bfi_l=_mean_optional(row.bfi_l for row in window),
        bfi_r=_mean_optional(row.bfi_r for row in window),
        bvi_l=_mean_optional(row.bvi_l for row in window),
        bvi_r=_mean_optional(row.bvi_r for row in window),
        cq=cq,
        bad_coupling=bad,
    )


def _mean_optional(values) -> float | None:
    usable = [float(value) for value in values if value is not None and np.isfinite(value)]
    if not usable:
        return None
    return float(sum(usable) / len(usable))


def _finite(value: float) -> float | None:
    if value is None or not np.isfinite(value):
        return None
    return float(value)


def _as_int(value: float) -> int | None:
    if not np.isfinite(value):
        return None
    return int(value)


def _format_float(value: float | None) -> str:
    if value is None or not np.isfinite(value):
        return ""
    return f"{value:.6f}"

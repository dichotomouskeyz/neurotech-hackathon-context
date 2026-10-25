#!/usr/bin/env python3
"""Replay a corrected Open-Motion scan CSV and print Lane 1 features.

For research. This does not diagnose stress, and the optical heart-rate
figure is not a clinical measurement.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# `python replay_csv.py` from the repo root, without an install.
_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from features.pulse_hr import estimate_optical_hr  # noqa: E402
from ingest.omotion_source import (  # noqa: E402
    ScanCsvError,
    apply_window,
    read_side_frames,
    write_side_csv,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Replay an Open-Motion corrected scan CSV (Lane 1). For research."
    )
    parser.add_argument("--csv", type=Path, required=True, help="Corrected scan CSV")
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Side-average CSV: timestamp_s, bfi_l, bfi_r, bvi_l, bvi_r, cq",
    )
    parser.add_argument(
        "--window-s",
        type=float,
        default=0.0,
        help="Trailing window for the written side averages, in seconds. "
        "0 keeps one row per frame. Heart rate always uses the per-frame trace.",
    )
    args = parser.parse_args(argv)
    try:
        raw = read_side_frames(args.csv)
        rows = apply_window(raw, args.window_s)
    except (ScanCsvError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if not rows:
        print("error: no frames in scan", file=sys.stderr)
        return 1

    heart_rate = estimate_optical_hr(
        [row.timestamp_s for row in raw],
        _series(raw, "bfi_l"),
        bfi_right=_series(raw, "bfi_r"),
    )
    print(f"frames: {len(rows)}")
    print(f"duration_s: {_duration(raw):.3f}")
    sample_rate = _sample_rate_hz(raw)
    print(f"sample_rate_hz: {_num(sample_rate)}")
    print(f"bfi_l_mean: {_num(_mean(row.bfi_l for row in rows))}")
    print(f"bfi_r_mean: {_num(_mean(row.bfi_r for row in rows))}")
    print(f"bvi_l_mean: {_num(_mean(row.bvi_l for row in rows))}")
    print(f"bvi_r_mean: {_num(_mean(row.bvi_r for row in rows))}")
    print(f"cq_mean: {_num(_mean(row.cq for row in rows))}")
    print(f"bad_coupling_frames: {_bad_frames(rows)}")
    if heart_rate.bpm is None:
        print(f"optical_hr_bpm: n/a ({heart_rate.note})")
    else:
        print(f"optical_hr_bpm: {heart_rate.bpm:.1f}")
        print(f"hr_method: {heart_rate.method}")
        if heart_rate.confidence is not None:
            print(f"hr_confidence: {heart_rate.confidence:.2f}")
    if args.out is not None:
        write_side_csv(rows, args.out)
        print(f"wrote: {args.out}")
    print("research demonstration only; not a clinical heart-rate or stress measure")
    return 0


def _series(rows, name: str) -> list[float]:
    values: list[float] = []
    for row in rows:
        value = getattr(row, name)
        values.append(float("nan") if value is None else float(value))
    return values


def _mean(values) -> float | None:
    usable = [float(value) for value in values if value is not None]
    if not usable:
        return None
    return sum(usable) / len(usable)


def _duration(rows) -> float:
    if len(rows) < 2:
        return 0.0
    return float(rows[-1].timestamp_s - rows[0].timestamp_s)


def _sample_rate_hz(rows) -> float | None:
    if len(rows) < 2:
        return None
    steps = [
        right.timestamp_s - left.timestamp_s
        for left, right in zip(rows, rows[1:], strict=False)
        if right.timestamp_s > left.timestamp_s
    ]
    if not steps:
        return None
    steps.sort()
    return 1.0 / steps[len(steps) // 2]


def _bad_frames(rows) -> str:
    flags = [row.bad_coupling for row in rows]
    if all(flag is None for flag in flags):
        return "n/a"
    return str(sum(1 for flag in flags if flag))


def _num(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.4f}"


if __name__ == "__main__":
    raise SystemExit(main())

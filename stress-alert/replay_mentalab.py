#!/usr/bin/env python3
"""Replay a Mentalab Explore ECG CSV and print heart rate and HRV.

For research. Heart rate and HRV from this replay are a demo cross-check
for the optical rate, not a clinical measurement.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# `python stress-alert/replay_mentalab.py` from the repo root, without an install.
_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from features.ecg_hrv import EcgFeatureError, analyze_ecg
from features.hr_compare import compare_hr
from ingest.mentalab_source import MentalabCsvError, read_ecg_csv, write_ecg_metrics, write_ecg_trace


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Replay a Mentalab Explore ExG CSV (Lane 2). For research."
    )
    parser.add_argument("--csv", type=Path, required=True, help="Explore *_ExG.csv or timestamp_s,ecg_uv")
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Trace CSV: timestamp_s, ecg_uv, hr_bpm",
    )
    parser.add_argument(
        "--metrics",
        type=Path,
        default=None,
        help="One-row HRV CSV. Defaults to <out stem>_metrics.csv when --out is set.",
    )
    parser.add_argument(
        "--channel",
        default=None,
        help="ECG column to read. Default: ecg_uv if present, otherwise the lowest chN.",
    )
    parser.add_argument(
        "--optical-hr",
        type=float,
        default=None,
        help="Lane 1 optical_hr_bpm, for a research cross-check against this ECG rate.",
    )
    args = parser.parse_args(argv)
    try:
        recording = read_ecg_csv(args.csv, channel=args.channel)
        summary, rates = analyze_ecg(recording.timestamps_s, recording.ecg_uv)
    except (MentalabCsvError, EcgFeatureError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    print(f"frames: {recording.timestamps_s.size}")
    print(f"duration_s: {summary.duration_s:.3f}")
    print(f"sample_rate_hz: {summary.sample_rate_hz:.4f}")
    print(f"channel: {recording.channel}")
    print(f"hr_bpm_mean: {_num(summary.hr_bpm_mean)}")
    print(f"hrv_mean_nn_ms: {_num(summary.hrv_mean_nn_ms)}")
    print(f"hrv_sdnn_ms: {_num(summary.hrv_sdnn_ms)}")
    print(f"hrv_rmssd_ms: {_num(summary.hrv_rmssd_ms)}")
    print(f"n_peaks: {summary.n_peaks}")
    if args.optical_hr is not None:
        _print_compare(args.optical_hr, summary.hr_bpm_mean)
    if args.out is not None:
        write_ecg_trace(args.out, recording.timestamps_s, recording.ecg_uv, rates)
        metrics_path = args.metrics
        if metrics_path is None:
            metrics_path = args.out.with_name(args.out.stem + "_metrics.csv")
        _write_metrics(metrics_path, recording.channel, summary)
        print(f"wrote: {args.out}")
        print(f"wrote_metrics: {metrics_path}")
    elif args.metrics is not None:
        _write_metrics(args.metrics, recording.channel, summary)
        print(f"wrote_metrics: {args.metrics}")
    print("for research only. ECG heart rate and HRV here are a demo cross-check")
    return 0


def _print_compare(optical_bpm: float, ecg_bpm: float | None) -> None:
    print(f"optical_hr_bpm: {_num(optical_bpm)}")
    if ecg_bpm is None:
        print("hr_abs_diff_bpm: n/a")
        print("hr_pct_diff_vs_ecg: n/a")
        return
    compared = compare_hr(optical_bpm, ecg_bpm)
    print(f"hr_abs_diff_bpm: {compared.abs_diff_bpm:.2f}")
    print(f"hr_pct_diff_vs_ecg: {compared.pct_diff:.2f}")


def _write_metrics(path: Path, channel: str, summary) -> None:
    write_ecg_metrics(
        path,
        duration_s=summary.duration_s,
        sample_rate_hz=summary.sample_rate_hz,
        channel=channel,
        hr_bpm_mean=summary.hr_bpm_mean,
        hrv_mean_nn_ms=summary.hrv_mean_nn_ms,
        hrv_sdnn_ms=summary.hrv_sdnn_ms,
        hrv_rmssd_ms=summary.hrv_rmssd_ms,
        n_peaks=summary.n_peaks,
    )


def _num(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.4f}"


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Write data/synthetic_scan.csv, a stand-in corrected Open-Motion scan.

640 frames at 40 Hz. BFI is a 72 bpm sinusoid on a slow drift, with a
different baseline per camera. Camera r8 is blank and marked nan_filled
so the side average skips it and contact quality is below 1. BVI carries
a slow wobble and no cardiac pulse. Synthetic fixture only.

Run from anywhere:

    python stress-alert/data/make_synthetic_scan.py
"""

from __future__ import annotations

from pathlib import Path
import csv
import math
import random

SAMPLE_RATE_HZ = 40.0
DURATION_S = 16.0
PULSE_BPM = 72.0
OUT_PATH = Path(__file__).resolve().parent / "synthetic_scan.csv"

_BASELINE_L = (3.4, 2.4, 1.3, 0.4, 0.3, 1.4, 2.5, 3.3)
_BASELINE_R = (3.5, 2.6, 1.3, 0.5, 0.4, 1.4, 3.5, 4.6)
_BVI_L = (5.6, 6.0, 6.1, 5.0, 5.6, 6.8, 7.0, 5.8)
_BVI_R = (5.6, 6.7, 6.9, 7.1, 6.7, 6.7, 6.3, 6.4)


def rows() -> list[dict[str, str]]:
    count = int(DURATION_S * SAMPLE_RATE_HZ)
    rng = random.Random(24)
    pulse_hz = PULSE_BPM / 60.0
    built: list[dict[str, str]] = []
    for index in range(count):
        timestamp = index / SAMPLE_RATE_HZ
        pulse = 0.25 * math.sin(2.0 * math.pi * pulse_hz * timestamp)
        drift = 0.03 * timestamp
        resp = 0.12 * math.sin(2.0 * math.pi * 0.18 * timestamp)
        record: dict[str, str] = {
            "frame_id": str(index),
            "timestamp_s": f"{timestamp:.4f}",
        }
        for cam in range(1, 9):
            noise = rng.gauss(0.0, 0.012)
            record[f"bfi_l{cam}"] = f"{_BASELINE_L[cam - 1] + pulse + drift + noise:.4f}"
            record[f"bvi_l{cam}"] = f"{_BVI_L[cam - 1] + resp + rng.gauss(0.0, 0.01):.4f}"
            record[f"quality_l{cam}"] = "ok"
            if cam == 8:
                record["bfi_r8"] = ""
                record["bvi_r8"] = ""
                record["quality_r8"] = "nan_filled"
            else:
                record[f"bfi_r{cam}"] = (
                    f"{_BASELINE_R[cam - 1] + pulse + drift + rng.gauss(0.0, 0.012):.4f}"
                )
                record[f"bvi_r{cam}"] = f"{_BVI_R[cam - 1] + resp + rng.gauss(0.0, 0.01):.4f}"
                record[f"quality_r{cam}"] = "ok"
        built.append(record)
    return built


def header() -> list[str]:
    names = ["frame_id", "timestamp_s"]
    for metric in ("bfi", "bvi"):
        for side in ("l", "r"):
            for cam in range(1, 9):
                names.append(f"{metric}_{side}{cam}")
    for side in ("l", "r"):
        for cam in range(1, 9):
            names.append(f"quality_{side}{cam}")
    return names


def write_csv(path: Path = OUT_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    names = header()
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=names)
        writer.writeheader()
        writer.writerows(rows())
    return path


if __name__ == "__main__":
    written = write_csv()
    print(f"wrote {written}")

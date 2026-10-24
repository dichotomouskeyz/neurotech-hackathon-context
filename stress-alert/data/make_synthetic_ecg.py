#!/usr/bin/env python3
"""Write data/synthetic_ecg.csv, a stand-in Explore ExG file.

5000 samples at 250 Hz. The waveform is NeuroKit2 ``ecg_simulate`` at 72 bpm
with a little noise, stored in microvolts under the explorepy header
``TimeStamp,ch1``. Synthetic fixture only.

Requires neurokit2:

    python stress-alert/data/make_synthetic_ecg.py
"""

from __future__ import annotations

from pathlib import Path
import csv

SAMPLE_RATE_HZ = 250
DURATION_S = 20
PULSE_BPM = 72
OUT_PATH = Path(__file__).resolve().parent / "synthetic_ecg.csv"


def write_csv(path: Path = OUT_PATH) -> Path:
    try:
        import neurokit2 as nk
    except ImportError as exc:
        raise SystemExit(
            "neurokit2 is required to regenerate the synthetic ECG. "
            "CSV replay of the committed file does not need this script."
        ) from exc
    ecg = nk.ecg_simulate(
        duration=DURATION_S,
        sampling_rate=SAMPLE_RATE_HZ,
        heart_rate=PULSE_BPM,
        noise=0.01,
        random_state=24,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["TimeStamp", "ch1"])
        for index, sample in enumerate(ecg):
            timestamp = index / SAMPLE_RATE_HZ
            writer.writerow([f"{timestamp:.4f}", f"{float(sample) * 1000.0:.4f}"])
    return path


if __name__ == "__main__":
    written = write_csv()
    print(f"wrote {written}")

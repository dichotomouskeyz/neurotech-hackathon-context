"""Lane 1 replay, contact quality, and optical heart rate."""

from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path

from features.cq_score import cq_score
from features.pulse_hr import estimate_optical_hr
from ingest.omotion_source import (
    ScanCsvError,
    apply_window,
    read_side_frames,
    replay_scan,
    start_live_scan,
    write_side_csv,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "data" / "synthetic_scan.csv"


class CqScoreTests(unittest.TestCase):
    def test_all_ok(self):
        result = cq_score(["ok"] * 16)
        self.assertEqual(result.score, 1.0)
        self.assertFalse(result.bad_coupling)
        self.assertEqual(result.n, 16)

    def test_nan_filled_camera_lowers_score(self):
        result = cq_score(["ok"] * 15 + ["nan_filled"])
        self.assertAlmostEqual(result.score, 15 / 16)
        self.assertFalse(result.bad_coupling)

    def test_mostly_dropouts_are_bad_coupling(self):
        result = cq_score(["ok"] * 4 + ["nan_filled"] * 12)
        self.assertLess(result.score, 0.5)
        self.assertTrue(result.bad_coupling)

    def test_half_score_is_not_below_the_gate(self):
        result = cq_score([True, False])
        self.assertAlmostEqual(result.score, 0.5)
        self.assertFalse(result.bad_coupling)

    def test_contact_dn_pass_and_near_miss(self):
        good = {"light_avg_dn": 30.0, "dark_max_dn": 1.0}
        near_miss = {"light_avg_dn": 5.0, "dark_max_dn": 1.0}
        result = cq_score([good, good, near_miss, near_miss])
        self.assertAlmostEqual(result.score, (1.0 + 1.0 + 5.0 / 15.0 + 5.0 / 15.0) / 4)
        self.assertFalse(result.bad_coupling)

    def test_contact_at_thresholds_scores_one(self):
        result = cq_score([{"light_avg_dn": 15.0, "dark_max_dn": 3.0}])
        self.assertEqual(result.score, 1.0)
        self.assertFalse(result.bad_coupling)

    def test_wide_interval_is_poor_coupling(self):
        result = cq_score(["wide_interval"])
        self.assertAlmostEqual(result.score, 0.35)
        self.assertTrue(result.bad_coupling)

    def test_unknown_label_raises(self):
        with self.assertRaises(ValueError):
            cq_score(["ok", "not-a-label"])


class PulseHrTests(unittest.TestCase):
    def test_known_sine_is_near_72_bpm(self):
        import numpy as np

        sample_rate = 40.0
        timestamps = np.arange(0.0, 16.0, 1.0 / sample_rate)
        bpm = 72.0
        trace = 2.2 + 0.2 * np.sin(2 * np.pi * (bpm / 60.0) * timestamps)
        trace = trace + 0.04 * timestamps
        estimate = estimate_optical_hr(timestamps, trace)
        self.assertIsNotNone(estimate.bpm)
        self.assertAlmostEqual(estimate.bpm, 72.0, delta=2.0)
        self.assertEqual(estimate.method, "fft")
        self.assertGreater(estimate.confidence, 0.9)

    def test_half_rate_tone_does_not_replace_a_100_bpm_pulse(self):
        import numpy as np

        sample_rate = 40.0
        timestamps = np.arange(0.0, 16.0, 1.0 / sample_rate)
        phase = (timestamps * (100.0 / 60.0)) % 1.0
        width = np.minimum(phase, 1.0 - phase)
        pulse = np.exp(-0.5 * (width / 0.07) ** 2)
        pulse = pulse / float(np.std(pulse))
        # Stronger sine at half the pulse rate. The FFT argmax sits on it.
        slow = np.sin(2 * np.pi * (50.0 / 60.0) * timestamps)
        trace = 2.2 + 0.35 * pulse + 0.5 * slow
        estimate = estimate_optical_hr(timestamps, trace)
        self.assertIsNotNone(estimate.bpm)
        self.assertAlmostEqual(estimate.bpm, 100.0, delta=3.0)
        self.assertGreater(estimate.bpm, 80.0)

    def test_true_50_bpm_pulse_is_not_doubled(self):
        import numpy as np

        sample_rate = 40.0
        timestamps = np.arange(0.0, 16.0, 1.0 / sample_rate)
        phase = (timestamps * (50.0 / 60.0)) % 1.0
        width = np.minimum(phase, 1.0 - phase)
        pulse = np.exp(-0.5 * (width / 0.07) ** 2)
        pulse = pulse / float(np.std(pulse))
        trace = 2.2 + 0.35 * pulse
        estimate = estimate_optical_hr(timestamps, trace)
        self.assertIsNotNone(estimate.bpm)
        self.assertAlmostEqual(estimate.bpm, 50.0, delta=3.0)

    def test_repeated_capture_stamps_do_not_set_the_sample_rate(self):
        import numpy as np

        sample_rate = 40.0
        timestamps = np.arange(0.0, 16.0, 1.0 / sample_rate)
        bpm = 100.0
        trace = 2.2 + 0.2 * np.sin(2 * np.pi * (bpm / 60.0) * timestamps)
        # Three stamps of each light frame, a few tens of microseconds apart.
        stamped = np.repeat(timestamps, 3) + np.tile([0.0, 50e-6, 100e-6], timestamps.size)
        values = np.repeat(trace, 3)
        estimate = estimate_optical_hr(stamped, values)
        self.assertIsNotNone(estimate.bpm)
        self.assertAlmostEqual(estimate.bpm, 100.0, delta=3.0)

    def test_uniform_20_hz_cadence_keeps_a_100_bpm_tone(self):
        import numpy as np

        # Dropped frames leave a real 20 Hz series. Do not rewrite it to 40 Hz.
        sample_rate = 20.0
        timestamps = np.arange(0.0, 16.0, 1.0 / sample_rate)
        bpm = 100.0
        trace = 2.2 + 0.2 * np.sin(2 * np.pi * (bpm / 60.0) * timestamps)
        estimate = estimate_optical_hr(timestamps, trace)
        self.assertIsNotNone(estimate.bpm)
        self.assertAlmostEqual(estimate.bpm, 100.0, delta=2.0)

    def test_short_clip_is_rejected(self):
        estimate = estimate_optical_hr([0.0, 0.025, 0.05], [1.0, 1.2, 0.8])
        self.assertIsNone(estimate.bpm)
        self.assertIn("8s", estimate.note)


class ReplayTests(unittest.TestCase):
    def test_synthetic_fixture_reports_pulse_and_cq(self):
        rows = replay_scan(FIXTURE)
        self.assertGreaterEqual(len(rows), 600)
        self.assertEqual(rows[0].frame_id, 0)
        self.assertIsNotNone(rows[0].bfi_l)
        self.assertIsNotNone(rows[0].bfi_r)
        self.assertAlmostEqual(rows[0].cq, 15 / 16)
        self.assertFalse(rows[0].bad_coupling)
        # r8 is the dropout, so the right side uses 7 cameras, not 8.
        self.assertIsNotNone(rows[0].bvi_r)

        estimate = estimate_optical_hr(
            [row.timestamp_s for row in rows],
            [row.bfi_l for row in rows],
            bfi_right=[row.bfi_r for row in rows],
        )
        self.assertIsNotNone(estimate.bpm)
        self.assertAlmostEqual(estimate.bpm, 72.0, delta=3.0)

    def test_blank_camera_is_skipped_in_the_side_mean(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "scan.csv"
            _write_scan(
                path,
                [
                    {
                        "frame_id": "1",
                        "timestamp_s": "0.0",
                        "bfi_l1": "2",
                        "bfi_l2": "",
                        "bfi_r1": "4",
                        "bvi_l1": "6",
                        "quality_l1": "ok",
                        "quality_l2": "nan_filled",
                    }
                ],
            )
            rows = read_side_frames(path)
        self.assertEqual(len(rows), 1)
        self.assertAlmostEqual(rows[0].bfi_l, 2.0)
        self.assertAlmostEqual(rows[0].bfi_r, 4.0)
        self.assertAlmostEqual(rows[0].cq, 0.5)
        self.assertFalse(rows[0].bad_coupling)

    def test_missing_quality_columns_leave_cq_blank(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "scan.csv"
            _write_scan(
                path,
                [
                    {"frame_id": "1", "timestamp_s": "0.0", "bfi_l1": "1.5", "mean_l1": "100"},
                    {"frame_id": "2", "timestamp_s": "0.025", "bfi_l1": "1.7", "mean_l1": "101"},
                ],
            )
            rows = read_side_frames(path)
            out = Path(tmp) / "side.csv"
            write_side_csv(rows, out)
            with out.open(newline="", encoding="utf-8") as handle:
                written = list(csv.DictReader(handle))
        self.assertIsNone(rows[0].cq)
        self.assertEqual(written[0]["cq"], "")
        self.assertEqual(written[0]["bfi_l"], "1.500000")
        self.assertEqual(written[1]["bfi_r"], "")

    def test_full_sample_header_is_accepted(self):
        header = ["frame_id", "timestamp_s"]
        for metric in ("bfi", "bvi", "mean", "contrast", "temp", "quality"):
            for side in ("l", "r"):
                for cam in range(1, 9):
                    header.append(f"{metric}_{side}{cam}")
        self.assertEqual(len(header), 98)
        row = {name: "0" for name in header}
        row["frame_id"] = "10"
        row["timestamp_s"] = "0.225"
        for side in ("l", "r"):
            for cam in range(1, 9):
                row[f"quality_{side}{cam}"] = "ok"
                row[f"bfi_{side}{cam}"] = "2.0"
                row[f"bvi_{side}{cam}"] = "6.0"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sample_shaped.csv"
            with path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=header)
                writer.writeheader()
                writer.writerow(row)
            rows = read_side_frames(path)
        self.assertAlmostEqual(rows[0].bfi_l, 2.0)
        self.assertAlmostEqual(rows[0].bvi_r, 6.0)
        self.assertEqual(rows[0].cq, 1.0)

    def test_window_trails_and_keeps_one_row_per_frame(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "scan.csv"
            records = []
            for index in range(5):
                records.append(
                    {
                        "frame_id": str(index),
                        "timestamp_s": f"{index * 0.5:.1f}",
                        "bfi_l1": str(index),
                        "quality_l1": "ok",
                    }
                )
            _write_scan(path, records)
            raw = read_side_frames(path)
            windowed = apply_window(raw, 1.0)
        self.assertEqual(len(windowed), 5)
        # t=1.0 sees frames at 0.0, 0.5, and 1.0 (values 0, 1, 2).
        self.assertAlmostEqual(windowed[2].bfi_l, 1.0)
        self.assertEqual(windowed[2].frame_id, 2)

    def test_missing_bfi_columns_raise(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "scan.csv"
            _write_scan(path, [{"timestamp_s": "0", "mean_l1": "1"}])
            with self.assertRaises(ScanCsvError):
                read_side_frames(path)

    def test_live_scan_is_gated(self):
        with self.assertRaises(RuntimeError) as blocked:
            start_live_scan(data_dir="/tmp/omotion-stress-alert")
        self.assertIn("allow_live", str(blocked.exception))
        with self.assertRaises(RuntimeError) as demo:
            start_live_scan(
                data_dir="/tmp/omotion-stress-alert",
                allow_live=True,
                demo_mode=True,
            )
        self.assertIn("demo_mode", str(demo.exception))


def _write_scan(path: Path, records: list[dict[str, str]]) -> None:
    names: list[str] = []
    for record in records:
        for key in record:
            if key not in names:
                names.append(key)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=names)
        writer.writeheader()
        writer.writerows(records)


if __name__ == "__main__":
    unittest.main()

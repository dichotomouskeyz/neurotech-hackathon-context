"""Lane 2 Mentalab ECG replay, HRV, and the optical cross-check."""

from __future__ import annotations

import csv
import sys
import tempfile
import unittest
from pathlib import Path

from features.ecg_hrv import EcgFeatureError, analyze_ecg
from features.hr_compare import compare_hr, compare_hr_windows
from ingest.mentalab_source import (
    MentalabCsvError,
    read_ecg_csv,
    start_live_ecg,
    write_ecg_metrics,
    write_ecg_trace,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "data" / "synthetic_ecg.csv"


class EcgReplayTests(unittest.TestCase):
    def test_explore_header_and_known_rate(self):
        recording = read_ecg_csv(FIXTURE)
        self.assertEqual(recording.channel, "ch1")
        self.assertGreaterEqual(recording.timestamps_s.size, 4000)
        self.assertAlmostEqual(recording.timestamps_s[0], 0.0)
        summary, rates = analyze_ecg(recording.timestamps_s, recording.ecg_uv)
        self.assertAlmostEqual(summary.sample_rate_hz, 250.0, delta=0.1)
        self.assertIsNotNone(summary.hr_bpm_mean)
        self.assertAlmostEqual(summary.hr_bpm_mean, 72.0, delta=3.0)
        self.assertGreater(summary.n_peaks, 15)
        self.assertIsNotNone(summary.hrv_sdnn_ms)
        self.assertIsNotNone(summary.hrv_rmssd_ms)
        self.assertGreater(summary.hrv_sdnn_ms, 0.0)
        self.assertLess(summary.hrv_rmssd_ms, 80.0)
        self.assertEqual(rates.shape, recording.ecg_uv.shape)

    def test_named_columns_and_channel_choice(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "lead.csv"
            _write(
                path,
                ["timestamp_s", "ecg_uv", "ch2"],
                [
                    ["0", "10", "1"],
                    ["0.004", "11", "2"],
                    ["0.008", "12", "3"],
                ],
            )
            named = read_ecg_csv(path)
            other = read_ecg_csv(path, channel="ch2")
        self.assertEqual(named.channel, "ecg_uv")
        self.assertAlmostEqual(named.ecg_uv[0], 10.0)
        self.assertEqual(other.channel, "ch2")
        self.assertAlmostEqual(other.ecg_uv[-1], 3.0)

    def test_lowest_channel_is_the_default_lead(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "exg.csv"
            _write(
                path,
                ["TimeStamp", "ch4", "ch1"],
                [["0", "9", "1"], ["0.004", "8", "2"]],
            )
            recording = read_ecg_csv(path)
        self.assertEqual(recording.channel, "ch1")
        self.assertAlmostEqual(recording.ecg_uv[0], 1.0)

    def test_orientation_file_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "orn.csv"
            _write(path, ["TimeStamp", "ax", "ay"], [["0", "1", "2"], ["0.05", "1", "2"]])
            with self.assertRaises(MentalabCsvError):
                read_ecg_csv(path)

    def test_missing_file_raises(self):
        with self.assertRaises(MentalabCsvError):
            read_ecg_csv(ROOT / "data" / "no_such_ecg.csv")

    def test_short_clip_is_rejected(self):
        with self.assertRaises(EcgFeatureError):
            analyze_ecg([0.0, 0.004, 0.008], [0.0, 1.0, 0.0])

    def test_trace_and_metrics_roundtrip(self):
        recording = read_ecg_csv(FIXTURE)
        summary, rates = analyze_ecg(recording.timestamps_s, recording.ecg_uv)
        with tempfile.TemporaryDirectory() as tmp:
            trace = Path(tmp) / "ecg_trace.csv"
            metrics = Path(tmp) / "ecg_trace_metrics.csv"
            write_ecg_trace(trace, recording.timestamps_s, recording.ecg_uv, rates)
            write_ecg_metrics(
                metrics,
                duration_s=summary.duration_s,
                sample_rate_hz=summary.sample_rate_hz,
                channel=recording.channel,
                hr_bpm_mean=summary.hr_bpm_mean,
                hrv_mean_nn_ms=summary.hrv_mean_nn_ms,
                hrv_sdnn_ms=summary.hrv_sdnn_ms,
                hrv_rmssd_ms=summary.hrv_rmssd_ms,
                n_peaks=summary.n_peaks,
            )
            with trace.open(newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))
            with metrics.open(newline="", encoding="utf-8") as handle:
                metric_rows = list(csv.DictReader(handle))
        self.assertEqual(list(rows[0]), ["timestamp_s", "ecg_uv", "hr_bpm"])
        self.assertEqual(len(rows), recording.timestamps_s.size)
        self.assertEqual(len(metric_rows), 1)
        self.assertEqual(metric_rows[0]["channel"], "ch1")
        self.assertAlmostEqual(float(metric_rows[0]["hr_bpm_mean"]), summary.hr_bpm_mean, places=4)


class HrCompareTests(unittest.TestCase):
    def test_scalar_difference(self):
        compared = compare_hr(70.0, 72.0)
        self.assertAlmostEqual(compared.abs_diff_bpm, 2.0)
        self.assertAlmostEqual(compared.pct_diff, 100.0 * 2.0 / 72.0)

    def test_windows_on_overlap(self):
        times = [0.0, 5.0, 10.0, 15.0, 20.0]
        rows = compare_hr_windows(times, [70.0] * 5, times, [74.0] * 5, window_s=10.0)
        self.assertEqual(len(rows), 2)
        self.assertAlmostEqual(rows[0].abs_diff_bpm, 4.0)
        self.assertAlmostEqual(rows[0].pct_diff, 100.0 * 4.0 / 74.0)
        self.assertAlmostEqual(rows[0].t_start_s, 0.0)
        self.assertAlmostEqual(rows[1].t_end_s, 20.0)

    def test_no_overlap_is_empty(self):
        rows = compare_hr_windows([0.0, 1.0], [70.0, 70.0], [10.0, 11.0], [72.0, 72.0])
        self.assertEqual(rows, [])


class LiveGateTests(unittest.TestCase):
    def test_live_refuses_without_allow_live(self):
        with self.assertRaises(RuntimeError) as blocked:
            start_live_ecg(file_name="rec", device_name="Explore_TEST")
        self.assertIn("allow_live", str(blocked.exception))

    def test_live_needs_a_device_id(self):
        with self.assertRaises(ValueError):
            start_live_ecg(file_name="rec", allow_live=True)

    def test_missing_explorepy_points_at_csv_replay(self):
        sentinel = sys.modules.get("explorepy", "missing")
        sys.modules["explorepy"] = None
        try:
            with self.assertRaises(ImportError) as missing:
                start_live_ecg(file_name="rec", device_name="Explore_TEST", allow_live=True)
        finally:
            if sentinel == "missing":
                sys.modules.pop("explorepy", None)
            else:
                sys.modules["explorepy"] = sentinel
        self.assertIn("CSV replay", str(missing.exception))


class CliTests(unittest.TestCase):
    def test_cli_on_synthetic(self):
        import io
        from contextlib import redirect_stdout

        from replay_mentalab import main

        buf = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "ecg_trace.csv"
            with redirect_stdout(buf):
                code = main(["--csv", str(FIXTURE), "--out", str(out), "--optical-hr", "72"])
            metrics = Path(tmp) / "ecg_trace_metrics.csv"
            self.assertEqual(code, 0)
            self.assertTrue(out.is_file())
            self.assertTrue(metrics.is_file())
        text = buf.getvalue()
        self.assertIn("hr_bpm_mean: 72.", text)
        self.assertIn("hr_abs_diff_bpm:", text)
        self.assertIn("for research only", text)


def _write(path: Path, header: list[str], rows: list[list[str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows(rows)


if __name__ == "__main__":
    unittest.main()

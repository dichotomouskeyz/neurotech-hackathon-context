"""Lane 1 contact quality, optical heart rate, and the live-scan gate."""

from __future__ import annotations

import unittest

from features.cq_score import cq_score
from features.pulse_hr import estimate_optical_hr
from ingest.omotion_source import start_live_scan


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

    def test_short_clip_is_rejected(self):
        estimate = estimate_optical_hr([0.0, 0.025, 0.05], [1.0, 1.2, 0.8])
        self.assertIsNone(estimate.bpm)
        self.assertIn("8s", estimate.note)


class LiveScanTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()

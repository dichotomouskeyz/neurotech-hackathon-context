"""Unit tests for stress_index.py alert math and CQ gating."""

import math
import unittest

from features.stress_index import (
    StressTracker,
    compute_baseline,
    compute_recovery_tau,
    compute_stress_frame,
)


class TestStressIndex(unittest.TestCase):
    def test_cq_gate_suppresses_alert_when_cq_below_threshold(self):
        # Massive stress spike (3.0 vs baseline 1.5 = 100% elevation), but poor coupling
        result = compute_stress_frame(
            t=100.0,
            current_value=3.0,
            baseline_value=1.5,
            cq=0.42,  # Below default 0.50
            cq_threshold=0.50,
        )
        self.assertFalse(result.alert)
        self.assertEqual(result.index, 0.0)
        self.assertIn("poor_coupling", result.reason)
        self.assertIn("0.42 < 0.50", result.reason)

    def test_cq_gate_suppresses_alert_when_cq_is_none(self):
        result = compute_stress_frame(
            t=100.0,
            current_value=3.0,
            baseline_value=1.5,
            cq=None,
        )
        self.assertFalse(result.alert)
        self.assertIn("poor_coupling", result.reason)
        self.assertIn("missing", result.reason)

    def test_alert_triggers_when_cq_valid_and_elevated(self):
        # 30% elevation over baseline with good CQ
        result = compute_stress_frame(
            t=105.0,
            current_value=2.60,
            baseline_value=2.00,
            cq=0.88,
            alert_threshold=0.20,
        )
        self.assertTrue(result.alert)
        self.assertAlmostEqual(result.index, 0.30, places=2)
        self.assertAlmostEqual(result.delta, 0.60, places=2)
        self.assertIn("elevated_stress", result.reason)

    def test_nominal_when_index_below_threshold(self):
        # 5% elevation, under 20% alert threshold
        result = compute_stress_frame(
            t=105.0,
            current_value=2.10,
            baseline_value=2.00,
            cq=0.88,
            alert_threshold=0.20,
        )
        self.assertFalse(result.alert)
        self.assertAlmostEqual(result.index, 0.05, places=2)
        self.assertIn("nominal", result.reason)

    def test_baseline_uncalibrated_guard(self):
        result = compute_stress_frame(
            t=5.0,
            current_value=2.00,
            baseline_value=None,
            cq=0.90,
        )
        self.assertFalse(result.alert)
        self.assertIn("baseline_uncalibrated", result.reason)

    def test_frame_format_matches_schema(self):
        result = compute_stress_frame(
            t=1089839.91,
            current_value=2.6,
            baseline_value=2.0,
            cq=0.85,
            recovery_score=0.75,
        )
        frame = result.to_frame()
        self.assertEqual(frame["type"], "stress")
        self.assertEqual(frame["t"], 1089839.91)
        self.assertAlmostEqual(frame["index"], 0.30, places=2)
        self.assertAlmostEqual(frame["recovery_score"], 0.75, places=2)
        self.assertTrue(frame["alert"])
        self.assertIsInstance(frame["reason"], str)

    def test_compute_baseline_filters_noise_and_poor_cq(self):
        values = [2.0, 2.1, 100.0, 2.05, 1.95, 2.0, 99.0]
        cqs = [0.9, 0.85, 0.20, 0.90, 0.88, 0.91, 0.10]
        baseline = compute_baseline(values, cqs, cq_threshold=0.5)
        self.assertIsNotNone(baseline)
        # Median of clean values [1.95, 2.0, 2.0, 2.05, 2.1] should be 2.0
        self.assertAlmostEqual(baseline, 2.0, places=2)

    def test_recovery_tau_ideal_exponential(self):
        # y(t) = baseline + excess * exp(-t / tau)
        # tau = 20.0s, baseline = 2.0, excess = 1.0
        tau_true = 20.0
        baseline = 2.0
        excess = 1.0
        ts = [float(i) for i in range(50)]
        vs = [baseline + excess * math.exp(-t / tau_true) for t in ts]

        res = compute_recovery_tau(ts, vs, baseline, min_samples=10, min_duration_s=10.0)
        self.assertTrue(res.ok)
        self.assertIsNotNone(res.tau_s)
        self.assertAlmostEqual(res.tau_s, tau_true, places=1)
        self.assertGreater(res.r_squared, 0.99)
        self.assertGreater(res.fraction_recovered, 0.80)

    def test_recovery_tau_honest_null_on_rising_signal(self):
        # Signal increasing rather than decaying back to baseline
        baseline = 2.0
        ts = [float(i) for i in range(30)]
        vs = [2.5 + 0.1 * t for t in ts]

        res = compute_recovery_tau(ts, vs, baseline, min_samples=10, min_duration_s=10.0)
        self.assertFalse(res.ok)
        self.assertIsNone(res.tau_s)
        self.assertIn("rising rather than recovering", res.note)

    def test_recovery_tau_short_duration_null(self):
        baseline = 2.0
        # 15 samples but only 3 seconds duration
        ts = [0.2 * i for i in range(15)]
        vs = [2.5 - 0.05 * t for t in ts]
        res = compute_recovery_tau(ts, vs, baseline, min_samples=10, min_duration_s=10.0)
        self.assertFalse(res.ok)
        self.assertIsNone(res.tau_s)
        self.assertIn("shorter than minimum", res.note)

    def test_stress_tracker_lifecycle(self):
        tracker = StressTracker(cq_threshold=0.5, alert_threshold=0.20)

        # Phase 1: Baseline (collect samples at 2.0)
        tracker.on_phase("baseline", t=0.0)
        for i in range(10):
            res = tracker.on_sample(t=float(i), value=2.0, cq=0.9)
            self.assertFalse(res.alert)

        self.assertIsNotNone(tracker.calibrated_baseline)
        self.assertAlmostEqual(tracker.calibrated_baseline, 2.0, places=2)

        # Phase 2: Hold (BFI elevates to 2.6 = 30% increase)
        tracker.on_phase("hold", t=60.0)
        res_hold = tracker.on_sample(t=65.0, value=2.6, cq=0.92)
        self.assertTrue(res_hold.alert)
        self.assertAlmostEqual(res_hold.index, 0.30, places=2)

        # Phase 2 with poor coupling: alert should drop immediately
        res_slip = tracker.on_sample(t=70.0, value=2.6, cq=0.35)
        self.assertFalse(res_slip.alert)
        self.assertIn("poor_coupling", res_slip.reason)

        # Phase 3: Recovery
        tracker.on_phase("recovery", t=90.0)
        for i in range(25):
            t = 90.0 + float(i)
            # Decaying back toward 2.0
            val = 2.0 + 0.6 * math.exp(-float(i) / 15.0)
            tracker.on_sample(t=t, value=val, cq=0.95)

        self.assertIsNotNone(tracker.last_recovery_result)
        self.assertTrue(tracker.last_recovery_result.ok)


if __name__ == "__main__":
    unittest.main()

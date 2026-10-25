"""Stress index and recovery math gated on contact quality.

For research use only. This is a research engineering demonstration. These numbers
do not provide a diagnosis, clinical screening, treatment signal, or therapy.

Physics and physiology background:
- Open-Motion measures blood flow index (BFI) and blood volume index (BVI) on the
  forehead at 40 Hz using optical diffuse speckle contrast analysis.
- During breath-hold stress, arterial carbon dioxide rises (transient hypercapnia),
  driving cerebral vasodilation and increased forehead blood flow (BFI). Heart rate
  also shifts in response to autonomic nervous system modulation.
- Following release of the breath-hold, hemodynamics recover back toward baseline,
  modeled by an exponential decay time-constant (tau).
- Contact Quality Gate: Motion artifacts, hair obstruction, or probe slippage can
  produce large artificial swings in optical signals. If contact quality (CQ) falls
  below threshold (default 0.5), the stress alert is strictly gated off and marked
  as poor coupling rather than true physiological stress.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

DEFAULT_CQ_THRESHOLD = 0.50
# 10% above each camera's baseline median. Forehead BFI on a partial set of
# cameras often rises about this much in a breath hold; 20% left real holds
# on the no-elevation path. The live gate smooths for 1 s and holds the
# alert for 0.8 s, so the cardiac pulse does not clear this bar.
DEFAULT_ALERT_THRESHOLD = 0.10
DEFAULT_MIN_SAMPLES = 5


@dataclass(frozen=True)
class StressResult:
    """Calculated stress metric for a single time point or window.

    Matches the dashboard frame contract:
    {"type": "stress", "t": float, "index": float, "recovery_score": float | None,
     "alert": bool, "reason": str}
    """

    t: float
    index: float
    recovery_score: float | None
    alert: bool
    reason: str
    cq: float | None = None
    delta: float = 0.0
    baseline: float | None = None

    def to_frame(self) -> dict[str, Any]:
        """Return dictionary matching dashboard schema.py Stress frame."""
        frame: dict[str, Any] = {
            "type": "stress",
            "t": float(self.t),
            "index": float(round(self.index, 4)),
            "alert": bool(self.alert),
            "reason": str(self.reason),
        }
        if self.recovery_score is not None:
            frame["recovery_score"] = float(round(self.recovery_score, 4))
        else:
            frame["recovery_score"] = None
        return frame


@dataclass(frozen=True)
class RecoveryResult:
    """Estimated exponential recovery time-constant tau back to baseline."""

    tau_s: float | None
    r_squared: float | None
    n_samples: int
    duration_s: float
    y_peak: float | None
    y_baseline: float | None
    fraction_recovered: float | None
    note: str

    @property
    def ok(self) -> bool:
        return self.tau_s is not None


def compute_stress_frame(
    t: float,
    current_value: float,
    baseline_value: float | None,
    cq: float | None,
    *,
    cq_threshold: float = DEFAULT_CQ_THRESHOLD,
    alert_threshold: float = DEFAULT_ALERT_THRESHOLD,
    recovery_score: float | None = None,
) -> StressResult:
    """Compute a single CQ-gated stress result from current and baseline values.

    Args:
        t: Timestamp in seconds (LSL local_clock preferred).
        current_value: Current metric (BFI or optical HR).
        baseline_value: Mean or median metric during resting baseline.
        cq: Mean contact quality score, 0.0 to 1.0.
        cq_threshold: Minimum acceptable CQ to evaluate stress (default 0.5).
        alert_threshold: Relative elevation (0.10 for 10%) to trigger alert.
        recovery_score: Optional recovery metric during recovery phase.

    Returns:
        StressResult with alert boolean and descriptive reason string.
    """
    if math.isnan(current_value) or math.isinf(current_value):
        return StressResult(
            t=t,
            index=0.0,
            recovery_score=None,
            alert=False,
            reason="invalid_sample: non-finite input value",
            cq=cq,
            delta=0.0,
            baseline=baseline_value,
        )

    # CQ Gate check: strictly suppress alert on poor coupling or missing CQ
    if cq is None or math.isnan(cq):
        return StressResult(
            t=t,
            index=0.0,
            recovery_score=recovery_score,
            alert=False,
            reason="poor_coupling: CQ signal missing",
            cq=None,
            delta=0.0,
            baseline=baseline_value,
        )

    if cq < cq_threshold:
        return StressResult(
            t=t,
            index=0.0,
            recovery_score=recovery_score,
            alert=False,
            reason=f"poor_coupling: CQ {cq:.2f} < {cq_threshold:.2f}",
            cq=cq,
            delta=0.0,
            baseline=baseline_value,
        )

    # Baseline validation
    if baseline_value is None or math.isnan(baseline_value) or baseline_value <= 0.0:
        return StressResult(
            t=t,
            index=0.0,
            recovery_score=recovery_score,
            alert=False,
            reason="baseline_uncalibrated: awaiting valid baseline",
            cq=cq,
            delta=0.0,
            baseline=baseline_value,
        )

    delta = current_value - baseline_value
    rel_change = delta / baseline_value
    index = max(0.0, rel_change)

    if index >= alert_threshold:
        alert = True
        reason = f"elevated_stress: index {index:.2f} >= {alert_threshold:.2f}"
    else:
        alert = False
        reason = f"nominal: index {index:.2f} < {alert_threshold:.2f}"

    return StressResult(
        t=t,
        index=index,
        recovery_score=recovery_score,
        alert=alert,
        reason=reason,
        cq=cq,
        delta=delta,
        baseline=baseline_value,
    )


def compute_baseline(
    values: Sequence[float],
    cqs: Sequence[float | None] | None = None,
    *,
    cq_threshold: float = DEFAULT_CQ_THRESHOLD,
    min_samples: int = DEFAULT_MIN_SAMPLES,
) -> float | None:
    """Compute robust resting baseline from a sequence of values during baseline phase.

    Filters out NaNs and frames with CQ < cq_threshold.
    Returns median of usable values to guard against brief motion spikes.
    """
    usable: list[float] = []
    has_cqs = cqs is not None and len(cqs) == len(values)

    for i, val in enumerate(values):
        if val is None or math.isnan(val) or math.isinf(val) or val <= 0.0:
            continue
        if has_cqs:
            cq_val = cqs[i]  # type: ignore[index]
            if cq_val is None or math.isnan(cq_val) or cq_val < cq_threshold:
                continue
        usable.append(float(val))

    if len(usable) < min_samples:
        return None

    usable.sort()
    mid = len(usable) // 2
    if len(usable) % 2 == 1:
        return usable[mid]
    return 0.5 * (usable[mid - 1] + usable[mid])


def compute_recovery_tau(
    timestamps_s: Sequence[float],
    values: Sequence[float],
    baseline_value: float,
    *,
    min_samples: int = 10,
    min_duration_s: float = 10.0,
) -> RecoveryResult:
    """Estimate exponential recovery time-constant tau back to baseline.

    Model:
        y(t) - y_baseline = (y_peak - y_baseline) * exp(-(t - t_peak) / tau)
    Taking natural log of excess signal:
        ln((y(t) - y_baseline) / (y_peak - y_baseline)) = - (1 / tau) * (t - t_peak)
    Slope of linear fit m = -1 / tau => tau = -1 / m.

    Honest null handling:
    If recovery is non-monotonic, values increase instead of recovering,
    data is flat, or fit R^2 is too low, returns tau_s = None with clear note.
    """
    if len(timestamps_s) != len(values):
        raise ValueError("timestamps_s and values must have the same length")

    # Filter finite pairs
    pairs = [
        (float(t), float(v))
        for t, v in zip(timestamps_s, values, strict=False)
        if math.isfinite(t) and math.isfinite(v)
    ]
    if len(pairs) < min_samples:
        return RecoveryResult(
            tau_s=None,
            r_squared=None,
            n_samples=len(pairs),
            duration_s=0.0,
            y_peak=None,
            y_baseline=baseline_value,
            fraction_recovered=None,
            note=f"insufficient finite samples ({len(pairs)} < {min_samples})",
        )

    ts = [p[0] for p in pairs]
    vs = [p[1] for p in pairs]
    duration_s = ts[-1] - ts[0]
    if duration_s < min_duration_s:
        return RecoveryResult(
            tau_s=None,
            r_squared=None,
            n_samples=len(pairs),
            duration_s=duration_s,
            y_peak=None,
            y_baseline=baseline_value,
            fraction_recovered=None,
            note=f"duration {duration_s:.1f}s shorter than minimum {min_duration_s:.1f}s",
        )

    # Find peak value and its index
    max_idx = 0
    max_val = vs[0]
    for i, v in enumerate(vs):
        if v > max_val:
            max_val = v
            max_idx = i

    y_peak = max_val
    t_peak = ts[max_idx]
    excess_peak = y_peak - baseline_value

    if excess_peak <= 0.001:
        return RecoveryResult(
            tau_s=None,
            r_squared=None,
            n_samples=len(pairs),
            duration_s=duration_s,
            y_peak=y_peak,
            y_baseline=baseline_value,
            fraction_recovered=1.0,
            note="peak was already at or below baseline",
        )

    # If peak occurs near the end, signal is rising rather than recovering
    if max_idx >= len(vs) - 4:
        return RecoveryResult(
            tau_s=None,
            r_squared=None,
            n_samples=len(pairs),
            duration_s=duration_s,
            y_peak=y_peak,
            y_baseline=baseline_value,
            fraction_recovered=0.0,
            note="peak occurs at or near end of window; signal is rising rather than recovering",
        )

    # Fit exponential decay from peak onward
    decay_ts: list[float] = []
    log_residuals: list[float] = []

    for t, v in zip(ts[max_idx:], vs[max_idx:], strict=False):
        excess = v - baseline_value
        if excess > 0.0:
            dt = t - t_peak
            decay_ts.append(dt)
            log_residuals.append(math.log(excess / excess_peak))

    if len(decay_ts) < 5:
        return RecoveryResult(
            tau_s=None,
            r_squared=None,
            n_samples=len(pairs),
            duration_s=duration_s,
            y_peak=y_peak,
            y_baseline=baseline_value,
            fraction_recovered=None,
            note="too few points above baseline after peak to fit decay",
        )

    # Linear regression: log_residuals = slope * dt + intercept
    n = len(decay_ts)
    sum_x = sum(decay_ts)
    sum_y = sum(log_residuals)
    sum_xx = sum(x * x for x in decay_ts)
    sum_xy = sum(x * y for x, y in zip(decay_ts, log_residuals, strict=False))
    denom = n * sum_xx - sum_x * sum_x

    if abs(denom) < 1e-12:
        return RecoveryResult(
            tau_s=None,
            r_squared=None,
            n_samples=len(pairs),
            duration_s=duration_s,
            y_peak=y_peak,
            y_baseline=baseline_value,
            fraction_recovered=None,
            note="zero variance in time coordinates",
        )

    slope = (n * sum_xy - sum_x * sum_y) / denom
    intercept = (sum_y - slope * sum_x) / n

    # Compute R-squared
    mean_y = sum_y / n
    ss_tot = sum((y - mean_y) ** 2 for y in log_residuals)
    ss_res = sum(
        (y - (slope * x + intercept)) ** 2 for x, y in zip(decay_ts, log_residuals, strict=False)
    )
    r_squared = 1.0 - (ss_res / ss_tot) if ss_tot > 1e-12 else 0.0

    # Fraction recovered at end of window
    y_end = vs[-1]
    fraction_recovered = max(0.0, min(1.0, 1.0 - (y_end - baseline_value) / excess_peak))

    # Slope must be negative for physical decay back to baseline
    if not math.isfinite(slope) or slope >= 0.0:
        return RecoveryResult(
            tau_s=None,
            r_squared=r_squared,
            n_samples=len(pairs),
            duration_s=duration_s,
            y_peak=y_peak,
            y_baseline=baseline_value,
            fraction_recovered=fraction_recovered,
            note="positive slope indicates signal was rising rather than recovering",
        )

    tau_s = -1.0 / slope
    if not math.isfinite(tau_s):
        return RecoveryResult(
            tau_s=None,
            r_squared=r_squared,
            n_samples=len(pairs),
            duration_s=duration_s,
            y_peak=y_peak,
            y_baseline=baseline_value,
            fraction_recovered=fraction_recovered,
            note="decay fit was not finite",
        )

    # Reject unphysically long or short tau (< 1s or > 300s)
    if tau_s < 1.0 or tau_s > 300.0:
        return RecoveryResult(
            tau_s=tau_s,
            r_squared=r_squared,
            n_samples=len(pairs),
            duration_s=duration_s,
            y_peak=y_peak,
            y_baseline=baseline_value,
            fraction_recovered=fraction_recovered,
            note=f"tau {tau_s:.1f}s outside realistic physiological range (1 to 300s)",
        )

    return RecoveryResult(
        tau_s=round(tau_s, 2),
        r_squared=round(r_squared, 4),
        n_samples=len(pairs),
        duration_s=round(duration_s, 2),
        y_peak=round(y_peak, 4),
        y_baseline=round(baseline_value, 4),
        fraction_recovered=round(fraction_recovered, 4),
        note="exponential decay fit successful",
    )


class StressTracker:
    """Stateful stream processor tracking baseline, hold, and recovery phases.

    Feeds directly into the dashboard WebSocket or offline CSV pipeline.
    """

    def __init__(
        self,
        *,
        cq_threshold: float = DEFAULT_CQ_THRESHOLD,
        alert_threshold: float = DEFAULT_ALERT_THRESHOLD,
    ) -> None:
        self.cq_threshold = cq_threshold
        self.alert_threshold = alert_threshold
        self.current_phase: str = "baseline"
        self.baseline_samples: list[float] = []
        self.baseline_cqs: list[float | None] = []
        self.calibrated_baseline: float | None = None
        self.recovery_ts: list[float] = []
        self.recovery_values: list[float] = []
        self.last_recovery_result: RecoveryResult | None = None

    def on_phase(self, phase: str, t: float) -> None:
        """Handle phase change (baseline -> hold -> recovery -> work -> end)."""
        valid_phases = {"baseline", "hold", "recovery", "work", "end"}
        if phase not in valid_phases:
            raise ValueError(f"unknown phase {phase!r}, must be one of {valid_phases}")

        prev_phase = self.current_phase
        self.current_phase = phase

        if phase == "hold" and self.calibrated_baseline is None:
            # Calibrate baseline from collected baseline phase samples
            self.calibrated_baseline = compute_baseline(
                self.baseline_samples,
                self.baseline_cqs,
                cq_threshold=self.cq_threshold,
            )

        if phase == "recovery" and prev_phase != "recovery":
            # Reset recovery buffers for new recovery run
            self.recovery_ts.clear()
            self.recovery_values.clear()

    def set_baseline(self, baseline: float) -> None:
        """Manually override or preset baseline value."""
        if baseline <= 0.0 or not math.isfinite(baseline):
            raise ValueError("baseline must be positive and finite")
        self.calibrated_baseline = float(baseline)

    def on_sample(
        self,
        t: float,
        value: float,
        cq: float | None = None,
    ) -> StressResult:
        """Process incoming sample and return dashboard-compliant StressResult."""
        if self.current_phase == "baseline":
            if math.isfinite(value) and value > 0.0:
                self.baseline_samples.append(value)
                self.baseline_cqs.append(cq)
                # Running median baseline estimate
                if len(self.baseline_samples) >= DEFAULT_MIN_SAMPLES:
                    self.calibrated_baseline = compute_baseline(
                        self.baseline_samples,
                        self.baseline_cqs,
                        cq_threshold=self.cq_threshold,
                    )
            return compute_stress_frame(
                t=t,
                current_value=value,
                baseline_value=self.calibrated_baseline,
                cq=cq,
                cq_threshold=self.cq_threshold,
                alert_threshold=self.alert_threshold,
                recovery_score=None,
            )

        recovery_score: float | None = None

        if self.current_phase == "recovery":
            if math.isfinite(value):
                self.recovery_ts.append(t)
                self.recovery_values.append(value)
                if (
                    self.calibrated_baseline is not None
                    and len(self.recovery_ts) >= 10
                    and (self.recovery_ts[-1] - self.recovery_ts[0]) >= 10.0
                ):
                    self.last_recovery_result = compute_recovery_tau(
                        self.recovery_ts,
                        self.recovery_values,
                        self.calibrated_baseline,
                    )
                    if (
                        self.last_recovery_result
                        and self.last_recovery_result.fraction_recovered is not None
                    ):
                        recovery_score = self.last_recovery_result.fraction_recovered

        return compute_stress_frame(
            t=t,
            current_value=value,
            baseline_value=self.calibrated_baseline,
            cq=cq,
            cq_threshold=self.cq_threshold,
            alert_threshold=self.alert_threshold,
            recovery_score=recovery_score,
        )

    def reset(self) -> None:
        """Reset state for a fresh session."""
        self.current_phase = "baseline"
        self.baseline_samples.clear()
        self.baseline_cqs.clear()
        self.calibrated_baseline = None
        self.recovery_ts.clear()
        self.recovery_values.clear()
        self.last_recovery_result = None

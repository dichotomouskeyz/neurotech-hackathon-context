"""Optional Track 3 ML & Brain-State Classifier (Gated on Sunday Noon Ingest Status).

For research use only. Research engineering demonstration for the UC Berkeley
Neurotech Hackathon (October 24 to 25, 2026, Openwater sponsor).

No diagnostic, clinical, treatment, or screening claims.

Status:
This classifier is strictly optional and gated. It activates only if hardware
and CSV ingest across lanes is verified green by Sunday noon. Otherwise, the
primary rule-based CQ-gated stress index (stress_index.py) serves as the core
evaluated deliverable.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Mapping, Sequence


@dataclass(frozen=True)
class WindowFeatures:
    """Summary features extracted over a sliding analysis window."""

    duration_s: float
    n_samples: int
    mean_bfi: float
    delta_bfi_rel: float
    bfi_variance: float
    mean_cq: float
    cq_pass_fraction: float
    optical_hr_bpm: float | None

    def to_vector(self) -> list[float]:
        """Numeric vector for linear/logistic baseline classifier."""
        hr_val = self.optical_hr_bpm if self.optical_hr_bpm is not None else 0.0
        return [
            self.delta_bfi_rel,
            self.bfi_variance,
            self.mean_cq,
            self.cq_pass_fraction,
            hr_val,
        ]


@dataclass(frozen=True)
class StatePrediction:
    """Predicted physiological phase state."""

    predicted_state: str  # "baseline", "stress_hold", "recovery", "artifact"
    confidence: float
    features: WindowFeatures
    note: str


def extract_window_features(
    timestamps_s: Sequence[float],
    bfi_values: Sequence[float],
    cq_values: Sequence[float | None],
    *,
    baseline_bfi: float,
    optical_hr_bpm: float | None = None,
    cq_threshold: float = 0.50,
) -> WindowFeatures:
    """Extract summary hemodynamic and signal quality features over a window."""
    if len(timestamps_s) != len(bfi_values) or len(timestamps_s) != len(cq_values):
        raise ValueError("timestamps_s, bfi_values, and cq_values must have the same length")

    pairs = [
        (t, b, c)
        for t, b, c in zip(timestamps_s, bfi_values, cq_values)
        if math.isfinite(t) and math.isfinite(b)
    ]
    if not pairs:
        raise ValueError("no finite samples found in window")

    ts = [p[0] for p in pairs]
    bs = [p[1] for p in pairs]
    cs = [p[2] for p in pairs]

    duration_s = ts[-1] - ts[0]
    n = len(bs)
    mean_bfi = sum(bs) / n
    var_bfi = sum((b - mean_bfi) ** 2 for b in bs) / n if n > 1 else 0.0
    delta_rel = (mean_bfi - baseline_bfi) / baseline_bfi if baseline_bfi > 0 else 0.0

    valid_cqs = [c for c in cs if c is not None and math.isfinite(c)]
    if valid_cqs:
        mean_cq = sum(valid_cqs) / len(valid_cqs)
        pass_count = sum(1 for c in valid_cqs if c >= cq_threshold)
        cq_pass_fraction = pass_count / len(valid_cqs)
    else:
        mean_cq = 0.0
        cq_pass_fraction = 0.0

    return WindowFeatures(
        duration_s=duration_s,
        n_samples=n,
        mean_bfi=mean_bfi,
        delta_bfi_rel=delta_rel,
        bfi_variance=var_bfi,
        mean_cq=mean_cq,
        cq_pass_fraction=cq_pass_fraction,
        optical_hr_bpm=optical_hr_bpm,
    )


def classify_state(
    features: WindowFeatures,
    *,
    cq_threshold: float = 0.50,
    stress_delta_threshold: float = 0.20,
) -> StatePrediction:
    """Simple, interpretable baseline state classifier with CQ gating."""
    # Gate 1: Check coupling quality first
    if features.mean_cq < cq_threshold or features.cq_pass_fraction < 0.60:
        return StatePrediction(
            predicted_state="artifact",
            confidence=round(1.0 - features.mean_cq, 2),
            features=features,
            note="poor contact quality indicates motion or decoupling artifact",
        )

    # Gate 2: Evaluate hemodynamic delta
    if features.delta_bfi_rel >= stress_delta_threshold:
        conf = min(0.95, 0.50 + features.delta_bfi_rel)
        return StatePrediction(
            predicted_state="stress_hold",
            confidence=round(conf, 2),
            features=features,
            note="elevated BFI consistent with hypercapnic vasodilation during hold",
        )

    if features.delta_bfi_rel <= 0.08:
        conf = max(0.50, 1.0 - abs(features.delta_bfi_rel))
        return StatePrediction(
            predicted_state="baseline",
            confidence=round(conf, 2),
            features=features,
            note="BFI near calibrated baseline",
        )

    return StatePrediction(
        predicted_state="recovery",
        confidence=0.70,
        features=features,
        note="intermediate BFI consistent with post-stress recovery return",
    )

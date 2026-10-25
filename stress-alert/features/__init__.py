"""Lane features for the stress-alert demo. For research."""

from .cq_score import CqResult, cq_score
from .pulse_hr import HrEstimate, estimate_optical_hr
from .recovery_gate import GateDecision, TaskController, TaskView, evaluate_gate
from .stress_index import (
    RecoveryResult,
    StressResult,
    StressTracker,
    compute_baseline,
    compute_recovery_tau,
    compute_stress_frame,
)

__all__ = [
    "CqResult",
    "GateDecision",
    "HrEstimate",
    "RecoveryResult",
    "StressResult",
    "StressTracker",
    "TaskController",
    "TaskView",
    "compute_baseline",
    "compute_recovery_tau",
    "compute_stress_frame",
    "cq_score",
    "estimate_optical_hr",
    "evaluate_gate",
]

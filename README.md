# Neurotech Hackathon: Stress-Alert (Lane 4)

Team project for the UC Berkeley Neurotechnology Hackathon (October 24 to 25, 2026, sponsored by Openwater).

Prompt: **How can neurotechnology expand human cognitive potential?**

The team is building **`stress-alert`**, a real-time optical stress and recovery monitoring platform on Open-Motion (forehead blood flow index at 40 Hz) and Mentalab Explore ECG (chest electrical cardiac ground truth), presented on a live dashboard.

For research use only. This is a research engineering demonstration. These metrics and alerts do not provide a diagnosis, clinical screening, treatment signal, or therapy. Say "for research."

---

## Lane 4 Deliverables (Protocol, Alert Math, Packaging)

This branch (`lane-4`) implements Lane 4:

| Deliverable | Path | Description |
| :- | :- | :- |
| **Protocol** | [`protocol/breathhold.md`](file:///Users/liamlenh/Downloads/neurotech%20hackathon/lane-4/protocol/breathhold.md) | Standardized 3-phase breath-hold protocol (60s baseline, 20 to 40s hold, 90s recovery). |
| **Alert Math & CQ Gate** | [`features/stress_index.py`](file:///Users/liamlenh/Downloads/neurotech%20hackathon/lane-4/features/stress_index.py) | Pure-Python CQ-gated stress index, baseline calibration, and exponential recovery time-constant ($\tau$). |
| **Demo Script (60s)** | [`docs/DEMO_SCRIPT_60S.md`](file:///Users/liamlenh/Downloads/neurotech%20hackathon/lane-4/docs/DEMO_SCRIPT_60S.md) | Cue-by-cue 60-second walkthrough for Sunday 2:30 dry run and judging. |
| **Devpost Draft** | [`docs/DEVPOST_DRAFT.md`](file:///Users/liamlenh/Downloads/neurotech%20hackathon/lane-4/docs/DEVPOST_DRAFT.md) | Complete submission draft with problem statement, math formulation, honest null analysis, and research scope. |
| **Optional Track 3** | [`features/track3_classifier.py`](file:///Users/liamlenh/Downloads/neurotech%20hackathon/lane-4/features/track3_classifier.py) | Gated feature extraction and baseline brain-state classifier (evaluated only if ingest is green Sunday noon). |
| **Unit Tests** | [`tests/test_stress_index.py`](file:///Users/liamlenh/Downloads/neurotech%20hackathon/lane-4/tests/test_stress_index.py) | 11 automated unit tests verifying CQ gating, baseline estimation, recovery fits, and schema compliance. |

*(All deliverables are mirrored in `stress-alert/` for direct compatibility with dashboard and ingest imports).*

---

## Integration Guide: How Other Lanes Call Lane 4

Lane 4 is completely decoupled from hardware and the web interface. Other lanes import and call the following interfaces:

### 1. Single Frame Calculation (Dashboard / Stream Ingest)

Use `compute_stress_frame` to evaluate incoming samples. The output conforms directly to the dashboard frame contract (`dashboard/schema.py:Stress`):

```python
from features.stress_index import compute_stress_frame

# Example: Ingest receives a sample during the hold phase
result = compute_stress_frame(
    t=1089839.91,             # Seconds on pylsl.local_clock()
    current_value=2.70,        # Current BFI or optical HR
    baseline_value=2.00,       # Calibrated resting baseline
    cq=0.88,                   # Contact quality (0.0 to 1.0) from cq_score.py
    cq_threshold=0.50,         # Minimum acceptable CQ (default 0.50)
    alert_threshold=0.20,      # Relative elevation for alert (default 20%)
)

# Broadcast frame over WebSocket to dashboard
frame = result.to_frame()
# Output:
# {
#   "type": "stress",
#   "t": 1089839.91,
#   "index": 0.35,
#   "recovery_score": None,
#   "alert": True,
#   "reason": "elevated_stress: index 0.35 >= 0.20"
# }
```

### 2. Contact Quality (CQ) Gating in Action

If contact quality drops below threshold (e.g. participant frowns or moves sensor), `alert` is strictly forced `False`:

```python
slipped = compute_stress_frame(
    t=1089842.10,
    current_value=3.10,        # Massive optical surge
    baseline_value=2.00,
    cq=0.38,                   # Poor coupling (< 0.50)
)
print(slipped.alert)           # False
print(slipped.reason)          # "poor_coupling: CQ 0.38 < 0.50"
```

### 3. Stateful Stream Processing (`StressTracker`)

Use `StressTracker` to manage phase transitions automatically:

```python
from features.stress_index import StressTracker

tracker = StressTracker(cq_threshold=0.50, alert_threshold=0.20)

# Phase 1: Baseline (0 to 60s)
tracker.on_phase("baseline", t=0.0)
for sample in baseline_stream:
    tracker.on_sample(t=sample.t, value=sample.bfi, cq=sample.cq)

# Baseline is automatically calibrated as the median of clean frames
print(tracker.calibrated_baseline)

# Phase 2: Hold (60 to 90s)
tracker.on_phase("hold", t=60.0)
for sample in hold_stream:
    res = tracker.on_sample(t=sample.t, value=sample.bfi, cq=sample.cq)
    if res.alert:
        send_to_dashboard(res.to_frame())

# Phase 3: Recovery (90 to 180s)
tracker.on_phase("recovery", t=90.0)
for sample in recovery_stream:
    res = tracker.on_sample(t=sample.t, value=sample.bfi, cq=sample.cq)

# Inspect fitted recovery time-constant
recovery = tracker.last_recovery_result
if recovery and recovery.ok:
    print(f"Recovery Tau: {recovery.tau_s}s, R^2: {recovery.r_squared}")
else:
    print(f"Honest null recovery: {recovery.note}")
```

### 4. Recovery Time-Constant ($\tau$) Estimation

```python
from features.stress_index import compute_recovery_tau

res = compute_recovery_tau(
    timestamps_s=timestamps,   # List of timestamps during recovery
    values=bfi_values,         # List of BFI values
    baseline_value=2.0,        # Calibrated baseline
    min_samples=10,
    min_duration_s=10.0,
)
if res.ok:
    print(f"Tau: {res.tau_s}s, Fraction recovered: {res.fraction_recovered}")
```

---

## Testing and Verification

Run the test suite:

```bash
python3 -m unittest tests/test_stress_index.py
```

All 11 tests pass with zero external dependencies (pure standard library).

---

## Sunday Milestone Targets

- **Sunday 12:00 pm (Noon)**: Alert math wired into dashboard server (supports live stream and offline CSV replay). Track 3 classifier evaluated if ingest is green.
- **Sunday 2:30 pm**: One complete dry run of [`docs/DEMO_SCRIPT_60S.md`](file:///Users/liamlenh/Downloads/neurotech%20hackathon/lane-4/docs/DEMO_SCRIPT_60S.md).
- **Sunday 3:00 to 5:00 pm**: Hackathon judging presentation.

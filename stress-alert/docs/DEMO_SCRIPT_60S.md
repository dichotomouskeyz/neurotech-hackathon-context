# 60-Second Demo Script: CQ-Gated Stress and Recovery Alert

For research use only. Research engineering demonstration for the UC Berkeley Neurotech Hackathon (October 24 to 25, 2026, sponsored by Openwater).

No diagnostic, screening, clinical, treatment, or therapeutic claims.

---

## Overview

- **Format**: Live 60-second pitch and demonstration for judges (Sunday 3:00 to 5:00 pm).
- **Dry-run target**: Sunday 2:30 pm.
- **Hardware on screen**:
  - Open-Motion optical headband on forehead (40 Hz BFI/BVI).
  - Mentalab Explore ECG on chest (Lead II, LSL bridge via explorepy).
  - Live stress-alert dashboard (status strip, phase bands, live optical and electrical charts, CQ gauges, alert banner).
- **Backup**: If live station optical stream is not connected, replay `stress-alert/data/sample_scan.csv` through `replay_csv.py` with identical screen results.

---

## Timeline (0:00 to 1:00)

| Elapsed | Speaker Cue (What to Say) | Screen / Visual Cue (What to Show) | Status & System State |
| :- | :- | :- | :- |
| **0:00 - 0:12** (12 s) | "We built an optical stress and recovery alert on Open-Motion, gated by contact quality. On our subject, Open-Motion records forehead blood flow index at 40 Hz, while a Mentalab ECG records electrical cardiac ground truth. We begin in a resting baseline phase: contact quality is green at 0.92, baseline BFI is steady at 2.0, and heart rate is nominal." | Point to subject wearing headband and ECG. Direct judge attention to dashboard status strip (green chips) and steady baseline trace across the 60-second baseline band. | Phase: `baseline`<br>CQ: `0.92`<br>BFI: `2.0`<br>Alert: `False` (nominal) |
| **0:12 - 0:28** (16 s) | "Now our subject begins a controlled 30-second breath-hold. As arterial carbon dioxide rises, cerebral autoregulation drives vasodilation. Watch the forehead BFI trace climb by 35%. Because contact quality remains above 0.50, our pipeline verifies this as physiological elevation, and the stress alert turns red." | Subject holds breath. Timer marks `hold`. Blood flow curve rises visibly above the baseline dotted line. Dashboard displays red alert banner: `elevated_stress: index 0.35 >= 0.20`. | Phase: `hold`<br>CQ: `0.89`<br>BFI: `2.70`<br>Alert: `True` (elevated) |
| **0:28 - 0:42** (14 s) | "Here is the critical engineering feature: the contact-quality gate. In real-world neurotech, motion artifacts and probe slippage mimic vascular surges. Watch what happens when the subject shifts the sensor. BFI spikes wildly, but contact quality plummets to 0.35. Instead of triggering a false alarm, our gate immediately suppresses the alert and labels it 'poor coupling'." | Subject gently shifts probe/frowns. CQ bar drops into amber/red (< 0.50). Dashboard alert banner instantly clears from red stress to amber status: `poor_coupling: CQ 0.35 < 0.50`. | Phase: `hold`<br>CQ: `0.35`<br>Alert: `False` (gated off) |
| **0:42 - 0:54** (12 s) | "The subject resumes normal breathing into the recovery phase. Forehead hemodynamics decay back toward baseline. Our pipeline fits an exponential decay model in real time, calculating a recovery time-constant tau of 22 seconds, showing healthy cerebrovascular return." | Subject breathes normally. Phase logger marks `recovery`. BFI decay curve flattens toward baseline. Recovery panel displays fitted exponential curve, `tau = 22.4 s`, and `R^2 = 0.98`. | Phase: `recovery`<br>CQ: `0.91`<br>Tau: `22.4 s`<br>Alert: `False` |
| **0:54 - 1:00** (6 s) | "In summary: a multi-modal, artifact-robust hemodynamic stress alert on Open-Motion for research, demonstrating how optical neurotech can reliably monitor cognitive and autonomic state." | Show full 3-phase dashboard summary. Hand over for questions. | Phase: `end`<br>Session saved to `sessions/` |

---

## Contingency Checklist (For Sunday 2:30 Dry Run)

1. **Hardware Ingest Green**:
   - Open-Motion live station scanning on Windows host.
   - ECG streaming via `explorepy push2lsl`.
2. **Hardware Ingest Blocked or Station In Use**:
   - Switch dashboard to CSV replay mode:
     ```bash
     python stress-alert/replay_csv.py --csv stress-alert/data/synthetic_scan.csv --dashboard ws://localhost:8765/ws/ingest?source=omotion
     ```
   - Replay executes the exact same 3-phase sequence with synthetic breath-hold dynamics and identical dashboard visualization.

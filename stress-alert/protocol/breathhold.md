# Breath-Hold Stress and Recovery Protocol

For research use only. This protocol is an experimental engineering demonstration for the UC Berkeley Neurotech Hackathon (October 24 to 25, 2026, sponsored by Openwater).

These procedures and recorded metrics do not constitute medical, diagnostic, screening, clinical, or therapeutic evaluations. Say "for research."

## Purpose

This protocol induces transient, controlled physiological stress via voluntary breath-holding to evaluate:
1. Optical cerebral blood flow index (BFI) and blood volume index (BVI) measured on the forehead at 40 Hz with the Open-Motion station.
2. Optical heart rate estimated from pulsatile BFI residuals.
3. Electrical cardiac ground truth (heart rate, R-R intervals) recorded with a Mentalab ECG on the chest.
4. Contact-quality (CQ) gated stress alerting and recovery kinetics (exponential recovery time-constant tau).

## Safety and Scope Constraints

- Openwater approved self-testing of the Open-Motion station by team members for this project. Recordings stay in the local `stress-alert/sessions/` directory and are never committed to git.
- Never open the Open-Motion console. The console houses a Class 3 laser source and high voltage.
- No modifications of optical or acoustic safety outputs.
- Closed loop neuromodulation (e.g. HPA axis regulation, Open-LIFU stimulation) is outside the scope of this hackathon build and is reserved strictly for future research.
- If a subject experiences dizziness, discomfort, or lightheadedness, the breath-hold must terminate immediately.

## Hardware Setup and Placement

### 1. Forehead Optical Sensor (Open-Motion)
- Mount the Open-Motion optical headband across the forehead.
- Part hair cleanly away from the optical apertures to ensure direct scalp contact.
- Secure the band firmly to minimize mechanical slippage while ensuring participant comfort.
- Verify contact quality (CQ) using the contact quality check (`python scripts/sdk_examples.py contact-quality` or the dashboard CQ widget). Ensure mean CQ is >= 0.50 before starting a session.

### 2. Chest Electrical Sensor (Mentalab ECG)

Optional, and off by default. Skip this step for an Open-Motion run. `replay_mentalab.py` and `start_live_ecg` do not run until `STRESS_ALERT_MENTALAB=1` (or `--enable` on the replay CLI). Live recording also needs `allow_live=True` in the explorepy environment. The bridge below is that later step, not part of a normal run.

- Place Lead I or Lead II disposable electrodes on the chest.
- Connect the Mentalab Explore amplifier.
- Start the LSL bridge in a dedicated Python environment:
  ```bash
  explorepy push2lsl -s <DEVICE_ID>
  ```
- Verify the stream is discovered on the local network (`Explore_ECG`).

### 3. Dashboard and Session Logger
- Launch the stress-alert dashboard:
  ```bash
  python stress-alert/serve.py
  ```
- The dashboard automatically initializes the phase logger, synchronizes to `pylsl.local_clock()`, and emits LSL string markers on the stream `stress-alert-phases`.

## Protocol Phases and Timing

The protocol runs in three sequential phases totaling 180 seconds (3 minutes), matching the default durations in `stress-alert/session/phase_logger.py`:

| Phase | Duration | Subject Action | Dashboard Annotation |
| :- | :- | :- | :- |
| `baseline` | 60.0 s | Sit upright, quiet normal nasal breathing, minimal movement | `baseline` |
| `hold` | 30.0 s (20 to 40 s window) | End-tidal breath-hold, no Valsalva straining, maintain stillness | `hold` |
| `recovery` | 90.0 s | Release hold, resume normal breathing quietly, remain still | `recovery` |
| `end` | - | Session completed, file written | `end` |

### Phase 1: Baseline (0:00 to 1:00, 60 seconds)
- The subject sits comfortably in an upright chair with back supported.
- Normal, unforced tidal breathing through the nose.
- Eyes open, fixated on a static cross or the dashboard display.
- No talking, head movements, or swallowing during the final 15 seconds.
- The system computes the resting median baseline for BFI and optical heart rate.

### Phase 2: Breath-Hold (1:00 to 1:30, default 30 seconds; 20 to 40 seconds range)
- At the audio or visual cue from the operator/dashboard, the subject breathes out normally to functional residual capacity (end-tidal expiration) or takes a gentle normal inhalation, then holds their breath.
- Avoid forced Valsalva straining (bearing down against a closed glottis). Forced straining creates massive intrathoracic pressure spikes and gross mechanical head motion that artifacts optical signals.
- Maintain the hold for 30 seconds (or stop earlier between 20 to 40 seconds if breakpoint is reached).
- Maintain complete head and facial stillness.
- Arterial carbon dioxide (PaCO2) accumulates, initiating cerebrovascular vasodilation and elevating forehead BFI. If CQ >= 0.50 and BFI elevation exceeds 20%, the dashboard triggers a stress alert.

### Phase 3: Recovery (1:30 to 3:00, 90 seconds)
- Upon operator cue or timer expiration, the subject gently resumes normal tidal breathing.
- Avoid deep hyperventilation or gasping, which causes motion artifacts.
- Remain seated and still for the full 90 seconds.
- Cerebrovascular hemodynamics decay back toward baseline. The feature pipeline fits an exponential decay model to calculate the recovery time-constant tau.

## Phase Logger Integration

Phase markers must match what the dashboard annotates:
- Every phase transition is recorded in `stress-alert/sessions/<session_id>/events.csv` with fields:
  `t`, `wall_time`, `session_id`, `phase`, `source`
- Phase markers are pushed over LSL on stream `stress-alert-phases` with format:
  `<phase>|<session_id>|<source>`
- WebSocket `phase` frames are broadcast to connected clients:
  `{"type": "phase", "t": 1089839.91, "session_id": "20261024-140000_subject01", "phase": "hold", "source": "timer"}`

## Contact Quality (CQ) Gating Rules

1. **Gate Threshold**: The system gate threshold is strictly CQ >= 0.50.
2. **Motion and Coupling Artifacts**:
   - If the subject moves, frowns, or the headband slips, optical CQ drops below 0.50.
   - When CQ < 0.50, the pipeline forces `alert = False` and sets `reason = "poor_coupling: CQ < 0.50"`.
   - The dashboard must never show a "stress" alert when contact quality is poor.
3. **Honest Null Results**:
   - If a subject swallows or moves during the hold, data from that window is labeled as an artifact rather than true stress.
   - If recovery does not follow a monotonic decline (e.g. subject was speaking or moving during recovery), the pipeline returns an honest null for tau (`tau_s = None`, `note = "positive slope indicates signal was rising rather than recovering"`).

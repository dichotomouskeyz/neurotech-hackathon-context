# Breath-Hold Stress and Recovery Protocol

For research use only. This protocol is an experimental engineering demonstration for the UC Berkeley Neurotech Hackathon (October 24 to 25, 2026, sponsored by Openwater).

These procedures and recorded metrics do not constitute medical, diagnostic, screening, clinical, or therapeutic evaluations. Say "for research."

## Purpose

This protocol induces transient, controlled physiological stress via voluntary breath-holding to evaluate:
1. Optical cerebral blood flow index (BFI) and blood volume index (BVI) measured on the forehead at 40 Hz with the Open-Motion station.
2. Optical heart rate estimated from pulsatile BFI residuals.
3. Contact-quality (CQ) gated recovery kinetics (exponential recovery time-constant tau).
4. A recovery gate for the work step after calibration: locked until forehead BFI has returned toward baseline and CQ is at least 0.50. Bad CQ blocks the unlock. BVI and tau can ease the step, ask for a break, or coach a breath. The breath-hold is calibration, not the application. The perfusion readout is secondary telemetry, not a stress classifier.

## Safety and Scope Constraints

- Openwater approved self-testing of the Open-Motion station by team members for this project. Recordings stay in the local `stress-alert/sessions/` directory and are never committed to git.
- Never open the Open-Motion console. The console houses a Class 3 laser source and high voltage.
- No modifications of optical or acoustic safety outputs.
- The dashboard recovery gate is a task-unlock policy in this build. It does not stimulate. Closed loop neuromodulation (e.g. HPA axis regulation, Open-LIFU stimulation) is outside the scope of this hackathon build and is reserved strictly for future research.
- If a subject experiences dizziness, discomfort, or lightheadedness, the breath-hold must terminate immediately.

## Hardware Setup and Placement

### 1. Forehead Optical Sensor (Open-Motion)
- Mount the Open-Motion optical headband across the forehead.
- Part hair cleanly away from the optical apertures to ensure direct scalp contact.
- Secure the band firmly to minimize mechanical slippage while ensuring participant comfort.
- Verify contact quality (CQ) using the contact quality check (`python scripts/sdk_examples.py contact-quality` or the dashboard CQ widget). Ensure mean CQ is >= 0.50 before starting a session.

### 2. Dashboard and Session Logger
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
- The system computes a resting median baseline for each camera, for BFI and for BVI, and an optical heart rate for the side panel. Heart rate is not part of the stress index.

### Phase 2: Breath-Hold (1:00 to 1:30, default 30 seconds; 20 to 40 seconds range)
- At the audio or visual cue from the operator/dashboard, the subject breathes out normally to functional residual capacity (end-tidal expiration) or takes a gentle normal inhalation, then holds their breath.
- Avoid forced Valsalva straining (bearing down against a closed glottis). Forced straining creates massive intrathoracic pressure spikes and gross mechanical head motion that artifacts optical signals.
- Maintain the hold for 30 seconds (or stop earlier between 20 to 40 seconds if breakpoint is reached).
- Maintain complete head and facial stillness.
- Arterial carbon dioxide (PaCO2) accumulates, initiating cerebrovascular vasodilation and elevating forehead BFI. If CQ >= 0.50 and the stress index stays at least 10% above the selected cameras' baselines, the dashboard raises the stress alert. The index is the median relative rise of the responsive cameras, not an unweighted mean of every camera.

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

## Closed loop demo (about 60 seconds)

For research. **Demo Mode** plays calibration, then a work loop, with contact quality below 1.00, and it will not start during a live scan. **Closed loop (~60s)** runs the same two parts on a live scan. The button reads the duration fields. The defaults below sum to 60 seconds. Typing 60 / 30 / 90 still runs the full calibration sitting if work is set to match. The recovery gate controls the work step. The perfusion tile is secondary and does not unlock a step.

| Step | Duration | What the screen does |
| :- | :- | :- |
| Calibration baseline | 8 s | "Breathe normally." Each camera stores its own median while contact quality is at least 0.50. The task stays locked. |
| Calibration breath-hold | up to 8 s | Setup only. The gate stays locked while forehead BFI is up. After the first second, up to four cameras with at least a 3% rise are kept when at least two clear that floor. The secondary perfusion index is the median of those rises. |
| Calibration recovery | up to 12 s | "Learning how forehead blood flow returns. The task stays locked." The gate does not open here. A contact drop below 0.50 does not count as returned. |
| Work | 32 s | The application. The next step unlocks when BFI is back under 5% and contact is still at least 0.50. If BVI is still high, the step eases or the banner asks for a break. If recovery tau is 18 s or slower, the breath coach runs and the step eases. Bad contact locks the gate. |

If the hold ends without that elevation, recovery runs for about 4 seconds (or the typed recovery, whichever is shorter). The cue says there was no sustained elevation, and the work step does not unlock. Optical heart rate stays on the side panel and is not an input.

Camera selection, for research. A camera is eligible when it has at least five positive baseline samples, a baseline of at least 0.2, and a coefficient of variation of at most 0.50. Non-positive samples are dropped, so a camera sitting on zero does not enter the mean. Rank is the relative rise of the hold median versus that camera's own baseline. The kept set is at most four cameras, and only when at least two rise by 3% or more. One spiked camera does not choose the set. The index after that lock is the median of the kept cameras' latest 1 second rises, so recovery can fall and a single spike does not set the alert. The same rule runs separately for BFI and for BVI. The label is the larger of the two.

Laser light still comes only from **Start scan (laser on)**.

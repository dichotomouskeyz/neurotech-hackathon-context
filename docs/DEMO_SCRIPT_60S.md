# Demo script: calibrate, then a long work bout

For research use only. Research engineering demonstration for the UC Berkeley Neurotech Hackathon (October 24 to 25, 2026, sponsored by Openwater).

No diagnostic, screening, clinical, treatment, or therapeutic claims.

The file name is historical. Speak for about three minutes. The Work phase itself runs 20 minutes, or until you press End.

Three beats. Calibrate is a short baseline sit: learn resting forehead blood flow. The breath-hold is optional proof, off by default. The task stays locked. Work is the session: wear it and do something. When forehead BFI leaves that baseline and contact quality is still good, a breath starts on its own. When flow is back and contact is still good, the step unlocks. Bad contact keeps the gate shut and does not start a breath. Blood volume and recovery tau can ease the step, ask for a break, or coach a breath after an optional hold. The chart during work is the proof. The perfusion tile is secondary telemetry. It does not unlock the task, and it is not a stress classifier.

---

## Overview

- **Format**: Live long session for judges (Sunday 3:00 to 5:00 pm). Demo Mode is the offline 16-channel replay, the same feed as `--dev-feed`.
- **On screen**: Present view. The info control by the title says calibrate, then work, then an automatic breath. The top row is phase, heart rate, contact quality, and perfusion. The task line sits on the phase tile. The coach card stays on Operator. Neither view shows a recovery-gate card. Below the top row, the heatmap is on the left and the BFI and BVI charts are stacked on the right.
- **Live contact**: light and dark digital numbers on the Open-Motion `live` batch, the same thresholds as `features/cq_score.py`. A bad score blocks the gate.
- **Demo replay**, if the console is down: **Demo Mode** loops `data/sample_scan.csv` (16-channel BFI and BVI). Contact on that file is the recorded quality label. Demo Mode will not start while a live scan is running, and starting a scan stops the replay.

## What to say

Speak to the tiles. Do not quote a fixed percent or tau unless that is what the screen shows. Do not say the person is stressed or not stressed.

| When | What to say | What to point at |
| :- | :- | :- |
| 0:00, phase says Calibrate | "This is setup, not the product. Twenty seconds of quiet sitting learns resting forehead blood flow. The task stays locked." | Phase tile Calibrate. Task line on that tile. |
| Optional hold, if you turned it on | "The breath-hold is only calibration proof. Flow is up, and we still do not unlock a task. Recovery tau is how fast flow came back. It is not the countdown." | BFI chart during the hold. |
| Phase flips to Work | "Now the session. This work bout runs twenty minutes. Wear it and keep going. The step unlocks only when forehead flow is back and contact is good." | Phase tile Work. Countdown near 20:00. |
| Flow leaves the baseline, coach appears | "Forehead flow left the calibrated baseline, and contact is still good, so a breath starts on its own. This is a readiness cue. It is not a stress score." | Phase tile task line: Breath coach, then inhale and exhale. |
| Gate opens | "Perfusion-ready. Flow is back and contact is still good, so the step unlocks and the breath stops." | Phase tile task line: the step unlocked. |
| Contact dips under 0.50 | "Contact failed. The gate locks, and we do not coach a breath on a bad signal." | Contact quality tile. The task line stays on the locked step. |
| Last line | "For research. Not a diagnosis. The control signal is forehead BFI and BVI from Open-Motion." | Session under `sessions/`. |

## Live scan

Use this when the console is connected. Demo Mode refuses to run during a scan.

1. **Search.** The button reads Search until the console is connected, then Disconnect. Console and at least one sensor should read connected.
2. **Start scan.** This is the only control that turns the laser on. It reads Stop scan while the scan is running. BFI, BVI, and contact quality should leave their waiting states.
3. **Run timed.** Subject id can stay blank. Press **Run timed**. Defaults: baseline 20 s, hold 0, work 1200 s. To show the calibration hold, set Hold above 0 (for example 12) and Recovery to 20 before you press the button. The same button reads Stop protocol while the bout is running.
4. Switch to **Present**. Use the table. You do not advance the phases by hand. The breath coach follows the gate during Work.

A hold that never rises does not fake an unlock. Calibration says there was no sustained elevation, and the work step stays locked until flow moves and returns.

## Demo Mode (no laser)

Same 16-channel replay as `--dev-feed`. Leave this path if the console is up.

From the repository root:

```bash
uv sync --locked
uv run python -m dashboard
```

Open http://127.0.0.1:8765. Leave the laser off. Press **Demo Mode** (or start with `uv run python -m dashboard --dev-feed`, which turns that replay on immediately). Switch to **Present**. Charts, the heatmap, contact, and optical heart rate move from `data/sample_scan.csv`. The replay does not start a session. To walk calibrate, work, and the automatic breath without the console, press **Run timed** while the replay is on, then use the table above. For research. Not a diagnosis.

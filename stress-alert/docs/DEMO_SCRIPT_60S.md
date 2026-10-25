# 60-Second Demo Script: Perfusion-Ready Gate

For research use only. Research engineering demonstration for the UC Berkeley Neurotech Hackathon (October 24 to 25, 2026, sponsored by Openwater).

No diagnostic, screening, clinical, treatment, or therapeutic claims.

Two parts. Calibration is a short breath-hold sit: learn resting forehead blood flow, contact quality, and how perfusion returns. The task stays locked. The application is the work loop after that. The next step unlocks only when forehead BFI has returned toward that baseline and contact quality is good. Bad contact keeps the gate shut. Blood volume and recovery tau can ease the step, ask for a break, or coach a breath. The chart during work is the proof. The perfusion tile is secondary telemetry. It does not unlock the task, and it is not a stress classifier.

---

## Overview

- **Format**: Live or Demo Mode, for judges (Sunday 3:00 to 5:00 pm). Spend the minute on work, not on the breath-hold.
- **Dry-run target**: Sunday 2:30 pm.
- **On screen**: Present view. Phase reads Calibrate, then Work. Recovery gate tile, contact quality, BFI and BVI charts with the gate line, and the coach banner. Perfusion percent and optical heart rate stay secondary.
- **Demo contact**: graded scores such as 0.82, 0.78, 0.76, and 0.32. Demo Mode never publishes 1.00, and it will not start while a live scan is running.
- **Live contact**: light and dark digital numbers on the Open-Motion `live` batch, the same thresholds as `features/cq_score.py`. A bad score blocks the gate.

## Demo Mode (no laser)

```bash
cd stress-alert
uv sync --locked
uv run python -m dashboard
```

Open http://127.0.0.1:8765. Leave the laser off. Press **Demo Mode** (operator bar or the heatmap toolbar). Switch the top bar to **Present**. It runs about 25 seconds: 3 s baseline, a hold that ends about a second in, about 10 s of recovery, and 10.5 s of work. The heart rate tile stays empty because the script has no pulse.

Speak to the tiles. Do not quote a fixed percent or tau unless that is what the screen shows.

| When | What to say | What to point at |
| :- | :- | :- |
| 0:00, phase says Calibrate | "This is setup, not the product. A short breath-hold learns resting forehead blood flow and how it returns. The task stays locked." | Phase tile Calibrate. Gate locked. CQ under 1.00. |
| Trace rises, still Calibrate | "The hold is only the calibration load. Flow is up, and we still do not unlock a task." | BFI chart during the hold band. Banner says Calibration. |
| Recovery τ leaves -- | "That number is the fitted recovery time constant, how fast flow came back. It is not the countdown." | Recovery τ on the gate card, with unit s. |
| Phase flips to Work, gate Locked | "Now the application. You have been working and flow is up. The next step stays locked until BFI is back and contact is good. This is perfusion, not an EEG focus score." | Phase tile Work. Chart band labeled work. Gate locked, BFI. |
| Gate flips to Step 2 | "Perfusion-ready. BFI has returned and contact is still good, so the work step unlocks." | Gate tile Step 2. Chart line: Gate open. Banner: Task unlocked. |
| Banner eases or asks for a break | "Blood volume is still up, so the step eases or takes a break. Flow can be back while volume is not." | BVI chart. Gate still open. Difficulty step. |
| Contact dips (CQ near 0.32) | "Contact just failed during work. Flow can look recovered and the gate still locks. Bad CQ does not unlock the task." | Contact tile. Gate returns to Locked. |
| Gate opens again | "Contact is back and BFI is still recovered, so the step unlocks again. A slow recovery tau would coach a breath and ease the step." | Gate open, step number. |
| Last few seconds | "For research. Not a diagnosis. The control signal is forehead BFI and BVI from Open-Motion." | Session under `stress-alert/sessions/`. |

## Live scan

Use this when the console is connected. Demo Mode refuses to run during a scan, so headset contact is not replaced by the script.

1. **Connect device.** Console and at least one sensor should read connected.
2. **Start scan (laser on).** This is the only control that turns the laser on. BFI, BVI, and contact quality should leave their waiting states. Contact comes from light and dark DN, not from a filled-in 1.00.
3. **Closed loop (~60s).** Subject id can stay blank. Defaults are calibration (baseline 8 s, breath-hold up to 8 s, recovery up to 12 s) and then work for 32 s. The task stays locked through calibration. During work it unlocks only when BFI is back under 5% and contact stays at or above 0.50.
4. Switch to **Present**. Use the calibration sentence, then the work sentences in the table. If contact drops under 0.50 during work, say the swing does not count and point at the locked gate.

A hold that never rises does not fake an unlock. Calibration says there was no sustained elevation, and the work step stays locked until flow moves and returns.

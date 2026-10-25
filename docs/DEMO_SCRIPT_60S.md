# 60-Second Demo Script: Perfusion-Ready Gate

For research use only. Research engineering demonstration for the UC Berkeley Neurotech Hackathon (October 24 to 25, 2026, sponsored by Openwater).

No diagnostic, screening, clinical, treatment, or therapeutic claims.

The loop is a recovery gate. The next task step unlocks only when forehead blood flow (BFI) has returned toward baseline and contact quality is good. Bad contact keeps the gate shut. Blood volume (BVI) and the recovery time constant can ease the step, ask for a break, or coach a breath. The perfusion tile is secondary telemetry. It does not unlock the task, and it is not a stress classifier.

The same script lives at `stress-alert/docs/DEMO_SCRIPT_60S.md`.

---

## Overview

- **Format**: Live or Demo Mode, for judges (Sunday 3:00 to 5:00 pm). Demo Mode finishes the locked, recover, unlock, relock story in well under a minute.
- **Dry-run target**: Sunday 2:30 pm.
- **On screen**: Present view. Recovery gate tile, contact quality, BFI and BVI charts with the gate line, and the coach banner. Perfusion percent and optical heart rate stay secondary.
- **Demo contact**: graded scores such as 0.82, 0.76, and 0.32. Demo Mode never publishes 1.00, and it will not start while a live scan is running.
- **Live contact**: light and dark digital numbers on the Open-Motion `live` batch, the same thresholds as `features/cq_score.py`. A bad score blocks the gate.

## Demo Mode (no laser)

```bash
cd stress-alert
uv sync --locked
uv run python -m dashboard
```

Open http://127.0.0.1:8765. Leave the laser off. Press **Demo Mode** (operator bar or the heatmap toolbar). Switch the top bar to **Present**.

Speak to the tiles. Do not quote a fixed percent or tau unless that is what the screen shows.

| When | What to say | What to point at |
| :- | :- | :- |
| 0:00, gate says Locked | "The next step is locked. We do not start the task until forehead blood flow is back toward this baseline and contact is good enough to trust." | Recovery gate tile. The line on the blood flow chart: Gate locked, and a CQ under 1.00. |
| Trace rises | "The breath-hold is the load. Flow is up, so the gate stays shut. This is perfusion, not an EEG focus score." | BFI chart climbing. Gate still Locked. Coach says breathe. |
| Gate flips to Step 2 | "Perfusion-ready. BFI has returned and contact is still good, so task step 2 unlocks." | Gate tile "Step 2". Chart line: Gate open. Banner: Task unlocked. |
| Contact dips (CQ near 0.32) | "Contact just failed. Flow can look recovered and the gate still locks. Bad CQ does not unlock the task." | Contact tile. Gate returns to Locked. |
| Gate opens again | "Contact is back above the line and BFI is still recovered, so the step unlocks again. If recovery tau is slow, or blood volume is still up, the step eases, asks for a break, or coaches a breath." | Gate open, step number, BVI chart. |
| Last few seconds | "For research. Not a diagnosis. The control signal is forehead BFI and BVI from Open-Motion." | Session under `stress-alert/sessions/`. |

## Live scan

Use this when the console is connected. Demo Mode refuses to run during a scan, so headset contact is not replaced by the script.

1. **Connect device.** Console and at least one sensor should read connected.
2. **Start scan (laser on).** This is the only control that turns the laser on. BFI, BVI, and contact quality should leave their waiting states. Contact comes from light and dark DN, not from a filled-in 1.00.
3. **Closed loop (~60s).** Subject id can stay blank. The task stays locked through the breath-hold. It unlocks only after BFI returns and contact stays at or above 0.50.
4. Switch to **Present** and use the same sentences as the table above. If contact drops under 0.50, say the swing does not count and point at the locked gate.

A hold that never rises does not fake an unlock. The banner says there was no sustained elevation and the task stays locked.

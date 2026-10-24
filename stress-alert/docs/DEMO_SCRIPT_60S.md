# 60-Second Demo Script: Closed-Loop Perfusion Alert

For research use only. Research engineering demonstration for the UC Berkeley Neurotech Hackathon (October 24 to 25, 2026, sponsored by Openwater).

No diagnostic, screening, clinical, treatment, or therapeutic claims.

---

## Overview

- **Format**: Live demonstration for judges (Sunday 3:00 to 5:00 pm). The closed-loop button is built to finish in about a minute.
- **Dry-run target**: Sunday 2:30 pm.
- **On screen**: Open-Motion on the forehead, dashboard in Present view. BFI and BVI charts, contact quality, the stress label, and a breathing circle.
- **Stress label**: the larger of the BFI and BVI rises versus the resting baseline, and only when contact quality is at least 0.50. Optical heart rate is the side panel. It does not set the label.
- **Backup**: `uv run python -m dashboard --dev-feed` replays `stress-alert/data/sample_scan.csv` and fills contact quality from that file. It does not invent a breath-hold rise. Use the live scan for the pause-and-breathe moment.

## Before the judges

```bash
cd stress-alert
uv sync --locked
uv run python -m dashboard
```

1. **Connect device.** Console and at least one sensor should read connected.
2. **Start scan (laser on).** This is the only control that turns the laser on. BFI and BVI should leave "Waiting for bfi frames". Contact quality should leave "Waiting for contact quality" within the first captures.
3. **Closed loop (~60s).** This starts the session if you have not. Subject id can stay blank (the session is named `demo`).
4. Switch the top bar to **Present**.

## Timeline

Speak to the live numbers. Do not quote a fixed heart rate, tau, or percent unless that is what the tile shows.

| Elapsed | What to say | What to point at |
| :- | :- | :- |
| 0:00 | "This is a research demo on Open-Motion. Forehead blood flow and blood volume, gated on contact quality. Heart rate is only the side panel." | Headband. Green contact. Stress tile: resting baseline. |
| 0:12 | "Hold a gentle breath." | Banner: challenge. Phase `hold`. The BFI or BVI trace should rise. |
| when the label crosses 20% | "Perfusion is up versus this person's baseline, and contact is still good, so the task stops." | Red stress tile, "Elevated vs baseline". Banner: pause. Circle says Inhale, then Exhale. |
| if contact drops under 0.50 | "That swing does not count. Contact is too poor to call it elevation." | Contact tile. Stress label clears. The banner does not treat it as settled. |
| when the trace returns | "Perfusion is back near baseline and contact is still good, so we continue." | Banner: continue. If recovery lasted long enough, the stress tile shows a recovery tau. |
| last few seconds | "For research. Not a diagnosis. The loop is baseline, challenge, pause and breathe, continue." | Session is saved under `stress-alert/sessions/`. |

A hold that never rises does not fake the pause. The banner says there was no sustained elevation.

## If the station is not scanning

Leave the laser off. Run `uv run python -m dashboard --dev-feed` and show the charts, contact quality from the sample file, and the stress tile asking for a baseline. Say the closed loop needs the live breath-hold. Do not describe the replay as the same physiological result.

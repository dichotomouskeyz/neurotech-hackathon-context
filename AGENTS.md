# Agent instructions

This repository is stress-alert, the recovery-gate dashboard from the UC Berkeley Neurotech Hackathon (October 24 to 25, 2026, Openwater sponsor). Event notes live in `docs/hackathon/`. Read README.md, then docs/hackathon/OPEN-MOTION.md, before changing either.

## The app

The dashboard is a contact-quality-gated recovery gate on Open-Motion forehead BFI and BVI. Calibrate learns resting flow. Work unlocks the next step when BFI has returned and contact quality is good, and a breath starts when flow leaves that baseline with contact still good. The Mentalab ECG was dropped on 2026-10-24; do not reintroduce it without the team. The build plan lives in the team's Google Doc "Neurotech Hackathon", tab "Pitch / Summary".

Lanes. Stay in your lane and code against the message contract in `dashboard/SCHEMA.md`:

| Lane | Paths | Owner |
| :- | :- | :- |
| Dashboard and session/phase logger | `dashboard/`, `session/` | Jahlon |
| Ingest, features, sync | `ingest/`, `features/`, `sync/` | Teammates |

Environments:

- The app uses Python 3.12 with uv. Dependencies are pinned exactly in `pyproject.toml` and locked in `uv.lock`. Add a dependency with `uv add <pkg>==<version>`, preferring releases at least two weeks old, and commit the lockfile.
- `openmotion-sdk` is pinned to 1.12.0, matching Openwater's bloodflow app, and is a regular dependency. The dashboard's Search button uses it (`dashboard/device.py`). On macOS it needs `brew install libusb`. `demo_mode` produced no BFI/BVI in our test. Dashboard Demo Mode replays `data/sample_scan.csv` and does not use SDK demo mode.

## Scope rules

- Per Jahlon (2026-10-24), Openwater approved self-testing of Open-Motion by team members. This overrides SOW §6 for this team. Recordings of team members stay in the gitignored `sessions/` directory and never go in git.
- Outputs are research engineering demonstrations. Make no diagnostic, screening, clinical, treatment, or therapy claims. Say "for research."
- No modification of safety-critical optical or acoustic output. Never open the Open-Motion console.

The source docs in `docs/hackathon/sources/` are snapshots. The Google Docs are live, so re-read them before relying on them. Keep source URL, owner, and capture time with any new snapshot.

No em dashes, slogans, or ornamental taglines. Keep plans, drafts, built work, and verified results distinct.

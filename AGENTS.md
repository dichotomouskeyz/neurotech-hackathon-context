# Agent instructions

Team repo for the UC Berkeley Neurotech Hackathon (October 24 to 25, 2026, Openwater sponsor). It holds the `stress-alert/` app and the event context in `docs/` and `sources/`. Read README.md, then docs/OPEN-MOTION.md, before changing either.

## The app

`stress-alert/` measures breath-hold stress (baseline, hold, recovery) with Open-Motion on the forehead, shown on one live dashboard. The Mentalab ECG was dropped on 2026-10-24; do not reintroduce it without the team. The build plan lives in the team's Google Doc "Neurotech Hackathon", tab "Pitch / Summary".

Lanes. Stay in your lane and code against the message contract in `stress-alert/dashboard/SCHEMA.md`:

| Lane | Paths | Owner |
| :- | :- | :- |
| Dashboard and session/phase logger | `stress-alert/dashboard/`, `stress-alert/session/` | Jahlon |
| Ingest, features, sync | `stress-alert/ingest/`, `stress-alert/features/`, `stress-alert/sync/` | Teammates |

Environments:

- The app uses Python 3.12 with uv. Dependencies are pinned exactly in `stress-alert/pyproject.toml` and locked in `uv.lock`. Add a dependency with `uv add <pkg>==<version>`, preferring releases at least two weeks old, and commit the lockfile.
- `openmotion-sdk` is pinned to 1.12.0, matching Openwater's bloodflow app. `demo_mode` produced no BFI/BVI in our test, so off-station work replays CSVs.

## Scope rules

- Per Jahlon (2026-10-24), Openwater approved self-testing of Open-Motion by team members. This overrides SOW §6 for this team. Recordings of team members stay in the gitignored `stress-alert/sessions/` and never go in git.
- Outputs are research engineering demonstrations. Make no diagnostic, screening, clinical, treatment, or therapy claims. Say "for research."
- No modification of safety-critical optical or acoustic output. Never open the Open-Motion console.

The source docs in `sources/` are snapshots. The Google Docs are live, so re-read them before relying on them. Keep source URL, owner, and capture time with any new snapshot.

No em dashes, slogans, or ornamental taglines. Keep plans, drafts, built work, and verified results distinct.

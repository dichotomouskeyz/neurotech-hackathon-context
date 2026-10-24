# Neurotech Hackathon

Team repo for the Neurotechnology at Berkeley Hackathon, October 24 to 25, 2026, sponsored by Openwater. Judging is Sunday, October 25, 3:00 to 5:00 pm. The team is building on **Open-Motion** and has the station for the weekend.

Prompt: **How can neurotechnology expand human cognitive potential?**

The repo holds two things:

- **`stress-alert/`**: the app. Open-Motion (forehead blood flow, blood volume, optical heart rate) feeds a live dashboard. Lane 1 replays recorded CSVs offline. Lane 4 adds the breath-hold protocol, a contact-quality-gated stress index from BFI and BVI, and a closed loop that pauses for a breathing guide when perfusion is elevated. See `stress-alert/README.md`.
- **`docs/` and `sources/`**: event context, including rules, tracks, Openwater platform notes, and snapshots of the planning documents.

## Layout

| Path | Contents |
| :- | :- |
| `stress-alert/` | The app: live dashboard, session/phase logger, Lane 1 Open-Motion replay, Lane 4 stress index |
| `docs/DEMO_SCRIPT_60S.md` | 60-second demo script for the dry run and judging |
| `docs/DEVPOST_DRAFT.md` | Devpost draft. For research. |
| `docs/EVENT.md` | Prompt, scope rules, shared device inventory, links |
| `docs/OPEN-MOTION.md` | The team's platform: physics, hardware, data path, SDK, data formats, Mac test results, track fit, judging |
| `docs/FLOW-STATE.md` | Flow-state idea: what the device can do, literature, datasets, a rule-compliant design |
| `docs/TRACKS.md` | The eight challenge tracks, condensed, with what counts as a strong entry |
| `docs/REPOS.md` | Openwater GitHub repos mapped to tracks |
| `docs/OPENWATER.md` | What Openwater builds and how they frame it, from the opening pitch |
| `docs/OPEN-QUESTIONS.md` | Decisions not yet made |
| `sources/` | Snapshots of the source documents with provenance |

## Sources

| Source | Owner | State captured |
| :- | :- | :- |
| [Neurotech Hackathon](https://docs.google.com/document/d/1cJZHhlRC_0MSVPyy0UUCK1wsy3OVbCZ8YyEajoXiuQI/edit) (Google Doc) | raymond.ym.mak@gmail.com | Modified 2026-10-24 10:20 PT |
| [Openwater Tracks](https://docs.google.com/document/d/1EZLYCaoG85xlRGpJDvhnk7DNJXzRvOD0-C6tjOzwKH4/edit) (Google Doc) | Openwater | Read 2026-10-24 |
| [Openwater Opening Pitch](https://docs.google.com/presentation/d/11Ts-xtMeraUTatn430w1W6sz4zQGGy8b/edit) (slides) | Openwater | Read 2026-10-24 |
| [github.com/OpenwaterHealth](https://github.com/OpenwaterHealth) | Openwater | Repo list read 2026-10-24 |
| [Event SOW](https://github.com/OpenwaterHealth/openwater-docs/blob/ebb3db0/docs/Student%20Hackathon-%20Open-Motion%20%26%20Open-LIFU%20Development%20Platforms.md) in openwater-docs | Openwater | Draft v0.1, October 20; read at ebb3db0 |

The Google Docs are live and may change during the event. Re-read them before relying on device lists or track details.

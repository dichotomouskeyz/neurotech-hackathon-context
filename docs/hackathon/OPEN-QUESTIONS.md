# Open questions

- **Team:** who is on it. Raymond Mak owns the planning doc; other members are not recorded.
- **Platform:** Open-Motion (decided 2026-10-24). Station access for the whole weekend.
- **Track:** not chosen. Candidates are tracks 1 to 4 and 7; see OPEN-MOTION.md.
- **Provided datasets:** the SOW promises pre-recorded and synthetic P-SCOS, BFI, and BVI data. Only the 30 s `sample_scan.csv` is public in the repos. Ask Openwater for the full set, especially anything labeled by task or condition if going for Track 3.
- **Phantoms and fixtures:** what Openwater brought, and whether any phantom has controllable flow. Without flow, phantom BFI is mostly static.
- **SDK demo mode:** produced no BFI/BVI in the Mac test. Ask whether synthetic generation lives elsewhere.
- **`opw_bloodflow_gen2_ai`:** listed in the SOW as a reference repo but not visible on GitHub. Probably private; ask.
- **Consumer EEG devices:** the Muse, Emotiv, Neurosity, g.tec, and Mentalab devices are on the shared list, but Openwater's rules say no device on a person and no human data. The SOW's no-human rule is written for Openwater devices. Ask organizers before planning live EEG.
- **Which Openwater repos to fork** to Jahlon's GitHub: likely `openmotion-sdk` and `openmotion-bloodflow-app`.
- **Unidentified blue box:** contents unknown.
- **Prompt fit:** the event prompt is cognitive potential, while Openwater tracks center on blood flow and ultrasound. Track 3 (cognitive load from hemodynamics) and Wildcard are the closest direct fits.

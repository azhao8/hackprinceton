# Overview

**Miguel.exe** is a two-wheeled self-balancing robot with an iPhone "head" that sees, shows a face, and takes instructions by gesture and voice instead of a controller. It's built for HackPrinceton Fall 2026 (Nov 13-15). This file wins over every other doc.

## Status

- Hacking started 8 pm ET, Fri Nov 13. The submission deadline is 8 am ET, Sun Nov 15.
- Hardware is bought, printed and being assembled (John). Software hasn't started.
- Current focus: four lanes working in parallel (hardware, motion + integration, vision + understanding, misc), each against the mock robot or a desk rig until the robot is ready (see `01-build-plan.md`).
- Next milestone: the message contract and mock robot (overdue), then the first end-to-end slice at Sat 4 am (T+8).

## Decided

The full list is in `decisions/` (one file each). In short:

- **Body:** two-wheeled, self-balancing; iPhone on top as camera, screen, mic and speaker.
- **Control:** no handheld controller. People speak in their own words (an LLM understands them) and use gestures. Anyone nearby can direct it.
- **Character:** named Miguel.exe, with a light personality (name, eyes, voice).
- **Plan shape:** a general core first. "Follows you, carries things, responds to gestures" is the must-work floor. The specific use case is picked around Sat noon.
- **Autonomy:** the human says what; the robot works out how.
- **Product:** remembers things while it's running (world memory is in the build); a companion panel if it's not too much effort; trust features (stop gesture always works, says what it's about to do, camera-on indicator); favors low tasks (floor, seated people, kids).
- **Arm:** nothing attached yet; gestures only (wave, point) unless an attachment is ready after balancing works. The laptop drives it on the desk; the ESP32 drives it on the robot. Pitched as modular, with concept modules in the demo.
- **Team:** John on hardware. Vision + understanding and motion are equal priority, one person each; the motion person also writes the firmware and tunes balancing. Lanes and owners are in `01-build-plan.md`.
- **Build:** everything is built on the desk or against the mock robot first. Balancing goes simulation, then desk rig, then the real robot.
- **LLM:** Claude, behind a thin layer so Gemini can be swapped in.
- **Head:** an iPhone 18 Pro or similar (has LiDAR).
- **Prizes:** aim to win 1-2 tracks for sure; enter only tracks that fit naturally. Tracks aren't chosen yet.
- **Code:** Python server, Next.js web app (dashboard and phone page), ESP32 firmware on PlatformIO. Folders: `contract/`, `firmware/`, `server/`, `web/`, `sim/`, `docs/`.
- **Workflow:** tasks are GitHub Issues with a lane label; Alex's master agent merges and pushes; everyone else opens pull requests. Questions and blockers go in issue and PR comments. Agents ask instead of guessing on anything that affects the product, and the team decides together. Rules are in `CLAUDE.md`; `AGENTS.md` points Cursor and Codex users to it.

## Open

See `open-questions.md`. The big ones: the use case and main track (Sat noon), and how the phone's camera reaches the server.

## Map of the docs

| File | What's in it |
| --- | --- |
| `01-build-plan.md` | Lanes and owners, how each builds without the robot, interfaces, timeline by lane, how we work, risks |
| `02-robot.md` | Hardware design, materials, technical specs, images |
| `03-software.md` | Contract, motion, arm, vision and understanding, architecture |
| `04-product.md` | Concept, principles, use cases, capability menu |
| `05-event.md` | Rules, judging, tracks and prizes, demo notes |
| `milestones.md` | Checkpoints and the before-submission list |
| `open-questions.md` | Everything still open, with recommendations |
| `decisions/` | Settled decisions, one file each |
| `reference/` | Background notes and John's raw archive (not decisions) |
| `assets/` | Images and diagrams |

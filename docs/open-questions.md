# Open questions

Everything not yet decided, with a recommendation. When one is settled, add a file to `decisions/` and remove it here.

## Build plan

| # | Question | Recommendation |
| --- | --- | --- |
| B1 | Build everything on the desk or against a mock robot, and plug in the real robot as each part passes a bench test? | Yes |
| B2 | Priority: vision + understanding, then motion, then arm, then panel? | Yes |
| B3 | First milestone: a person in camera, the laptop decides, the command reaches the mock robot and a loose wheel turns? | Yes |
| B4 | Camera: start on Continuity Camera; build the phone page (camera + face) in parallel? | Yes |
| B5 | Arm: the laptop drives it on the desk; the ESP32 drives it on the robot; the laptop sends pose names? | Yes |
| B6 | Who writes the firmware and tunes the balancing on the real robot? | John tunes it, with an agent writing the code |
| B7 | Which LLM? | Claude, behind a thin layer so it can be swapped; Gemini only if the MLH Gemini prize matters |

## Product

| # | Question | Recommendation |
| --- | --- | --- |
| P-1 | Which use case? | Pick around Sat noon. Without a gripper, the strongest fits are fetch-and-carry with a tray, find-my-things, the robot pet and telepresence (see `04-product.md`) |
| P-2 | Which main track and special tracks? | Healthcare as the main track; Best Hardware, Best Physical AI and Amazon Practical AI as extras (see `05-event.md`) |
| P-3 | Is the arm in the demo, and with what end attachment? | Core first; gestures only (wave, point) unless an attachment is ready after balancing works |
| P-4 | Memory details (what it stores, conversation timeouts, named places)? | Start with no stored memory; add it only if the demo needs "where are my keys?" |

## Technical

| # | Question | Recommendation |
| --- | --- | --- |
| T-1 | PlatformIO for the firmware? | Yes (standard, command-line, pinned libraries); the firmware owner confirms |
| T-2 | Which spare iPhone model? Only a Pro has LiDAR | Check with John |
| T-3 | Does the BusLinker board have a USB port for desk testing? | Check with John |
| T-4 | How the phone streams video to the server: Continuity Camera first, then the HTTPS phone page | As in B4 |

## Team

| # | Question | Recommendation |
| --- | --- | --- |
| W-1 | How the three software people split the work | Decide when delegating; one agent does everything for now |
| W-2 | Add an `AGENTS.md` pointing to `CLAUDE.md` for teammates using Cursor or Codex | Only if someone uses those tools |

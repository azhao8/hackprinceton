# Open questions

Everything not yet decided, with a recommendation and where it came from. Add a question here as soon as it comes up (chat, issue or PR). When one is settled, add a file to `decisions/` and remove it here.

## Product

| # | Question | Recommendation | Raised in |
| --- | --- | --- | --- |
| P-1 | Which use case? | Pick around Sat noon. Without a gripper, the strongest fits are fetch-and-carry with a tray, find-my-things, the robot pet and telepresence (see `04-product.md`) | Planning |
| P-2 | Which main track and special tracks? | Pick around Sat noon. Leading idea: Healthcare as the main track; Best Hardware, Best Physical AI and Amazon Practical AI as extras (see `05-event.md`) | Planning |

## Robot contract and safety

| # | Question | Recommendation | Raised in |
| --- | --- | --- | --- |
| C-1 | The robot contract. Three versions now differ: the v0 in `03-software.md`, what John's working firmware speaks (`firmware/README.md`), and Alex's proposal: JSON over UDP; `type` instead of `t`; modes `off`/`balance`/`kickstand`; `seq`/`ack`; an `arm` field in each command; live parameters (`set`, `save`, `params`); position (`x`, `y`, `yaw`), `ms` and `dbg` in telemetry; faults `tilt`/`imu`; SI units + ROS REP 103; the robot clamps speeds; mDNS | Re-check Alex's proposal against the firmware that already balances before building anything. Keep what the firmware does unless a change buys something real; covers T-6 | Alex's chat, Sat; T-6 |
| C-2 | Does the e-stop stay on until someone releases it, and can a gesture release it? | It stays on until released on the dashboard. The stop gesture can trigger it but not release it. Releasing doesn't resume the task; the task is cancelled | PR #2 (Nick); issue #8 |
| C-3 | Should "motors off" (mode `idle`/`off`) be a dashboard button? | Yes, separate from STOP and behind a confirm (hold to confirm or a second click) | PR #2 (Nick); issue #8 |
| C-4 | Review of the server-web messages in `contract/web/` | Alex and Grant review them once the robot contract (C-1) is settled; the web side then matches it (issue #8) | PR #2 (Nick) |
| C-5 | How does the server start balancing? Today only a plain `g` packet does it, and only while the robot is held within 6° of upright | Add a JSON command that does exactly what `g` does, keeping the upright check, so the server only speaks JSON. Keep `g` for the bench tools | Alex's chat, Sat (firmware review) |
| C-6 | Should "turn by an angle" and "move by a distance" be contract commands? The firmware already does exact 90° turns and 50 cm moves, closed loop on the gyro, as one-letter commands | Yes, for any angle and distance. A closed loop on the robot at 200 Hz beats steering it from the laptop over Wi-Fi; skills like `turn(degrees)` call it directly | Alex's chat, Sat (firmware review) |
| C-7 | What happens at the 5-minute run limit? Today the motors cut and the robot tips over | Park on the kickstand instead (John's agent has this queued), and send a warning in telemetry 30 s before | `firmware/README.md`; Alex's chat, Sat |
| C-8 | Self stand-up from the kickstand with the phone on fails 3 of 5 times. Does the demo need it? | Not for the demo: a person lifts it upright and the server starts balancing. Retry stand-up over something soft only if time allows | `firmware/README.md`; Alex's chat, Sat |
| C-9 | Kickstand mode (drive on the kickstand without balancing) isn't in the firmware. It's fallback tier 2 and where the arm should work | Add it before the 2 pm go/no-go so the fallback really exists | `firmware/README.md`; Alex's chat, Sat |
| C-10 | Battery voltage: the firmware reports `batt: null` because nothing measures it. Measuring needs a voltage divider into a free ADC pin (hardware) | Add the divider if John has two resistors; otherwise watch the buck's display and stop below ~10 V | `firmware/README.md`; Alex's chat, Sat |
| C-11 | The arm on the ESP32 (decision 0035: BusLinker on GPIO 17/18, laptop sends pose names) isn't in the firmware yet. Moving the arm shifts the balance point | Add named poses after the go/no-go. Re-check the trim with the arm on, and move the arm only while parked or in kickstand mode at first | Alex's chat, Sat (firmware review) |
| C-12 | The Wi-Fi link (UDP 4210) is written but untested. The product path depends on it | Test it on a hotspot first; it's the link the server will use | `firmware/README.md`; Alex's chat, Sat |

## Technical

| # | Question | Recommendation | Raised in |
| --- | --- | --- | --- |
| T-4 | What runs on the phone, and how its camera reaches the server: a web page over HTTPS, or a native iOS app? (was B4) | A thin native iOS app. It sends video, LiDAR depth and ARKit position to the laptop and shows the face; perception stays on the laptop. Depth gives follow-me a real distance, and ARKit gives position without wheel drift. A web page gets neither. Vision works on a desk camera behind a frame-source interface meanwhile. John's follow tool already uses Continuity Camera with Apple Vision on his Mac | Planning; Alex's chat, Sat |
| T-5 | Firmware build: PlatformIO (0040) or arduino-cli? The working firmware uses the ESP32 core 3.x timer API; PlatformIO's official platform ships core 2.x | Keep arduino-cli for the weekend (it builds and uploads from the command line); see `firmware/README.md` | John's firmware |
| T-6 | Contract differences between the firmware and `03-software.md`: no kickstand mode, 20 Hz telemetry, no battery reading, degrees | Decide each one; the mock follows the winner. List in `firmware/README.md`. Settled together with C-1 | John's firmware |
| T-7 | How the server handles concurrency | Python asyncio in one process. Vision runs in its own worker and hands over the latest result; each skill is an async task, so the stop gesture can cancel it | Alex's chat, Sat |
| T-8 | The skill API: what a skill reads, how it requests motion, how it reports, how it's cancelled | Draft it with Grant in the server skeleton PR: skills read perception and memory, send targets to the arbiter, return success or failure, and can be cancelled at any time | Alex's chat, Sat |
| T-9 | Scanning for secrets before the repo goes public | A gitleaks pre-commit hook now, and GitHub secret scanning once the repo is public. A leaked key stays in git history | Alex's chat, Sat |

## Team

| # | Question | Recommendation | Raised in |
| --- | --- | --- | --- |
| W-4 | How cross-lane questions reach the team | A `question` issue label and issue template (question, options, recommendation, who it affects); the team decides in the comments. This file stays the list of what's open | Alex's chat, Sat |
| W-5 | Who owns the firmware? John wrote and tuned the working firmware; the build plan and 0036 give firmware to Alex | John keeps the firmware he tuned. Alex owns the contract and the server side and reviews contract changes | John's firmware |

# Build plan and collaboration

How four people and their agents build Miguel.exe between now (Sat 1 am) and the deadline (Sun 8 am). It covers who owns what, how each part gets built before the robot is ready, how the parts connect, the timeline for each lane, and how we work together. Checkpoints are in `milestones.md`. Tasks are GitHub Issues.

## Principles

- **One seam:** the message contract between laptop and robot. The mock robot and the real robot use the same messages, so swapping one for the other changes nothing else.
- **Bench before robot:** each part is proven on the desk (loose motor, loose IMU, loose arm, a camera on the desk) before it goes on the robot.
- **Lanes don't wait on each other:** each lane builds against the mock robot or a stand-in, so nobody is blocked on hardware or on another lane.
- **Always demoable:** every stage leaves something to show (see Fallback demo tiers below).
- **Vision and motion are equally important:** each one gets a full-time owner.
- **Standard and simple:** use the common convention or library first; prefer the simpler way. For any real choice, list the alternatives, critique each, then pick one.

## Who does what

Four lanes. Software lanes are owned by folder, so agents rarely touch the same files.

| Lane | Person | Owns | Folders |
| --- | --- | --- | --- |
| Hardware | John Huang | Frame, wiring, power, the physical robot. At the robot for every real-robot test | (none) |
| Motion + integration (master) | Alex Zhao | Runs the master agent that merges. Firmware: balancing, drive, kickstand mode, safety cutoffs, the robot end of the link, arm on the ESP32. The balance simulation. Tuning on the real robot with John. The contract, the mock robot, the server's robot link and arbiter, the run script | `firmware/`, `sim/`, `contract/`, `server/` mock, link, arbiter |
| Vision + understanding | Grant Ji Kim | Camera input, person tracking, gestures, follow-me, speech to text, the LLM brain, the skill runner and skills, memory | `server/` vision, speech, brain, skills, memory modules |
| Misc | Jialang "Nick" Zhao | The server's web API, dashboard, phone page (camera + face), arm poses on the desk, companion panel, pitch, Devpost, backup video, demo path. Picks up whatever is blocking another lane | `server/` API, `web/` |

Motion and firmware belong to the same person because balancing *is* the firmware: the control loop, IMU filter, step timing and safety cutoffs all run on the ESP32 together. The contract and mock robot sit with them too, since the contract is the firmware's other half.

## How each lane builds without the robot

### Motion + integration: seams first, then balancing

- **Contract and mock robot first** (overdue). Every other lane builds against them, so they come before anything else.
- **Simulation (`sim/`, about an hour, mostly agent work).** A Python model of the robot as an inverted pendulum on wheels, using the CAD numbers: 2.21 kg, center of mass 93 mm above the axle, 85 mm wheels. It settles the controller shape, the sign conventions (which way is "forward", which way positive tilt is) and ballpark gains, and checks that the 300 ms timeout and the tilt cutoff behave. Steppers take speed commands, so the usual setup is two loops: an inner loop turns tilt and tilt rate into wheel acceleration, and an outer loop turns the speed error into a target tilt.
- **Desk rig (spare ESP32, driver, stepper and IMU).** This is the real firmware running on real parts. The steps spin a loose wheel at the commanded speed; tilting the IMU by hand gives the right angle and sign; the loop holds its rate; the UDP link talks to the server; the timeout and tilt cutoff trip. This rig is the loose wheel in the first end-to-end slice.
- **Server robot link and arbiter:** the UDP link and the arbiter (e-stop > manual joystick > skills), so the same server drives either the mock or the real robot.
- **Real robot, with John.** Flash the same firmware, start from the simulated gains, and tune on a tether. Only this step needs the assembled robot. Kickstand mode (same commands, no balancing) is ready before tuning starts, so it's always there as a fallback.

### Vision and understanding: on the desk

- **Camera:** a laptop webcam or a second camera, behind a frame-source interface. The phone page or Continuity Camera plugs in later without changing anything else (the camera route is still open, see `open-questions.md`).
- **Perception:** MediaPipe person and hand tracking on every frame, with a debug window showing boxes and the recognized gesture.
- **Follow-me and gestures:** the person's position and size become speed and turn targets that go to the arbiter. The result shows on the mock robot and the dashboard. Walk around the desk to test it.
- **Skill runner:** runs one skill at a time and sends its targets to the arbiter.
- **Speech and the brain:** push-to-talk on the laptop mic, then speech to text, then Claude picking skills. Gemini sits behind the same interface.
- **Memory:** the world memory store from `03-software.md`. Perception and skills write to it, and a summary goes into every LLM call.

### Misc: everything people see, plus filling gaps

- The server's WebSocket API and the dashboard (e-stop, joystick, telemetry plots), built against the mock robot.
- The phone page: camera stream and face, over HTTPS.
- Arm poses from the laptop over the BusLinker's USB port.
- The companion panel, the pitch, Devpost, the backup video and the demo path.
- When a lane is blocked or behind, take one of its issues.

## Interfaces between lanes

Agree on these first, write them down, and change them only in a PR that every affected lane looks at.

| Interface | Between | Owner | Where |
| --- | --- | --- | --- |
| Robot messages: drive, mode, arm pose, telemetry | Motion + integration (both ends) | Alex | `contract/`, with samples. A change updates the mock and the firmware in the same PR |
| Arbiter input: speed/turn targets and arm poses, tagged by source (e-stop, joystick, skill) | All three software lanes | Alex | `server/` |
| Skill API: a skill gets perception and memory and sends targets to the arbiter | Vision and Motion + integration | Grant | `server/` |
| Frame source: anything that hands out camera frames | Vision and Misc (phone page) | Grant | `server/` |
| Server and web messages: telemetry, what the robot sees, e-stop, joystick, tasks | Misc (both ends) | Nick | `contract/web/` |
| Arm pose names: wave, point, push, tuck | Misc (desk) and Motion (ESP32) | Alex | `contract/` |

## Timeline by lane

Times are Sat/Sun ET. Checkpoints in bold come from `milestones.md`.

| When | Motion + integration (Alex) | Vision + understanding (Grant) | Misc (Nick) |
| --- | --- | --- | --- |
| Sat 1-2 am | Contract + mock robot (unblocks everyone); the agent starts the simulation | Frame source on the webcam; MediaPipe person + hands with a debug view | Web API and dashboard skeleton against sample telemetry |
| Sat 2-4 am | Firmware on the desk rig: wheel follows commands, IMU sign and filter, UDP link, timeout; server link and arbiter | Follow-me and the stop gesture; skill runner into the arbiter (straight to the mock if the arbiter isn't ready) | Dashboard e-stop, joystick and live telemetry |
| **Sat 4 am** | **First end-to-end slice:** a person walks in front of the camera, the laptop decides, the mock gets the command and the loose wheel turns the right way | | |
| Sat 4-6 am | Firmware onto the robot with John; kickstand mode first, then a tether | Speech to text; the LLM brain picking skills; `say()` | Phone page over HTTPS (camera + face) |
| **Sat 6 am** | **Tethered balance (10 s)** | | |
| Sat 6 am-12 pm | Tuning; driving by joystick; merges at each check-in | More gestures (come here, point); `look_for` and `describe_scene`; memory | Arm poses on the desk; companion panel; run-script help |
| **Sat 12 pm** | **Use case and main track picked** | | |
| Sat 12-2 pm | Server link pointed at the real robot; driving with skills | Skills for the chosen use case | Whatever the use case needs on screen; pitch outline |
| **Sat 2 pm** | **Go/no-go on balancing:** keep balancing or demo in kickstand mode | | |
| Sat 2 pm-Sun 5 am | Arm on the ESP32; robustness, falls, battery; run script | Use-case skills; tuning in a noisy room | Demo path; Devpost draft; backup video |
| **Sun 5 am** | **Feature freeze:** bug fixes only | | |
| Sun 5-7 am | Rehearse the demo; fix only what breaks it | | Submit on Devpost by 7 am |
| **Sun 9:30 am** | **Judging:** in-person demo, max 2 min | | |

Sleep in shifts. Alex and John sleep at the same time, since tuning needs both of them. Grant and Nick cover the other shift.

## How we work

- **Everyone runs their own agent.** Claude Code reads `CLAUDE.md`; Cursor and Codex read `AGENTS.md`, which points to it.
- **One task = one issue = one branch = one PR** that says "Closes #N". Tasks are 1-3 hours. Each issue has a lane label (`lane:motion`, `lane:vision`, `lane:misc`); assign yourself before starting. Branch name: `<lane>/<N>-short-name`.
- **Pull main before each task.** Keep PRs small; tests pass before opening one.
- **Stay in your lane's folders.** A PR that touches another lane's folder says so and gets that lane's OK.
- **Main is protected:** only Alex's master agent pushes or merges to main, and only with Alex's OK for each one. Branches, PRs, issues and comments need no permission. Merges happen in batches at check-ins while Alex is at the robot. Main always runs against the mock robot. Pull main after any merge your lane depends on.
- **Contract changes** update the contract, the mock and the firmware in one PR.
- **Real robot:** commands go to it only when someone is with it.
- **Secrets** live in `.env` (not in git); their names go in `.env.example`.
- **Where we talk:** blockers, questions and interface changes go in issue and PR comments, so every agent can read them; the group chat is for quick pings. Read an issue's comments before working on it.
- **Ask, don't guess:** when an agent hits a question that could affect the product (decisions, architecture, interfaces between lanes, product details, UI/UX, demo behavior), it stops and asks its human, with the options and a recommendation. The human raises it with the team in an issue comment and pings the group chat, and the team decides together. Trivial choices (names, file layout inside a lane, small refactors) don't need asking.
- **Check-ins:** five minutes at each checkpoint: what works, what's blocked, what's next.
- **Decisions:** the team decides; Alex's master agent records them in `decisions/` and updates the docs. Questions still open go in `open-questions.md`.

## Fallback demo tiers

1. Balances and follows.
2. Kickstand mode: it rests on the printed kickstand and drives with the same commands.
3. "Smart mast" on the table: the phone tracks the judge, plus the dashboard and recorded clips.

## Risks

The top risk is balancing eating the whole weekend, leaving no time for the parts judges actually see.

| Risk | Fallback |
| --- | --- |
| Balance tuning takes too long | Kickstand mode, so every other feature still demos |
| Alex carries motion, the seams and merging, and is at the robot most of Saturday | Contract and mock land first, before any robot time; merges wait for check-ins; Nick takes server or run-script issues when Alex is behind |
| Vision needs a camera while the iPhone is on the robot | A second camera for the desk: a teammate's phone or an MLH Logitech webcam |
| Arm motion knocks it over | Kickstand down before using the arm; keep the arm light and close to the mast |
| Wi-Fi lag or drops at the venue | Own hotspot; the robot balances on its own and stops after 300 ms without commands |
| Robot falls and breaks the phone | Crash bars at the top, kickstand when idle, test with a dummy weight first |
| LiPo damage | Fuse, low-voltage cutoff, charge in a LiPo bag |
| Crowded demo floor | Short scripted demo in a cleared ~2 m square |
| Speech in a loud venue | Push-to-talk or a mic close to the speaker |

# Build plan and collaboration

How four people and their agents build Miguel.exe between now (Sat 1 pm; the robot balances) and the deadline (Sun 8 am). It covers who owns what, how each part gets built and tested, how the parts connect, the timeline for each lane, and how we work together. Checkpoints are in `milestones.md`. Tasks are GitHub Issues.

## Principles

- **One seam:** the message contract between laptop and robot. The mock robot and the real robot use the same messages, so swapping one for the other changes nothing else.
- **Bench before robot:** each part is proven on the desk against the mock robot (a camera on the desk, the dashboard, the server) before it drives the real robot.
- **One server is the hub:** the phone and the dashboard feed one Python server, which steers the robot (see `03-software.md`).
- **Lanes don't wait on each other:** each lane builds against the mock robot or a stand-in, so nobody is blocked on hardware or on another lane.
- **Always demoable:** every stage leaves something to show (see Fallback demo tiers below).
- **Vision and motion are equally important:** each one gets a full-time owner.
- **Standard and simple:** use the common convention or library first; prefer the simpler way. For any real choice, list the alternatives, critique each, then pick one.

## Who does what

Four lanes. Software lanes are owned by folder, so agents rarely touch the same files.

| Lane | Person | Owns | Folders |
| --- | --- | --- | --- |
| Hardware + firmware | John Huang | Frame, wiring, power, the physical robot. The firmware he wrote and tuned, and its bench tools (ownership open: W-5). At the robot for every real-robot test | `firmware/` |
| Motion + integration (master) | Alex Zhao | Runs the master agent, which organizes the work. The server skeleton, the contract, the mock robot, the server's robot link and arbiter, the run script, CI. Firmware changes the contract needs, together with John | `contract/`, `server/` skeleton, mock, link, arbiter |
| Vision + understanding | Grant Ji Kim | Camera input, person tracking, gestures, follow-me, speech to text, the LLM brain, the skill runner and skills, memory | `server/` vision, speech, brain, skills, memory modules |
| Misc | Jialang "Nick" Zhao | The server's web API, dashboard, phone page (camera + face), arm poses on the desk, companion panel, pitch, Devpost, backup video, demo path. Picks up whatever is blocking another lane | `server/` API, `web/` |

John wrote and tuned the firmware overnight, so he knows it best; who owns it from here is open (W-5). The contract and mock robot sit with Alex, who owns the server end of the link.

## How each lane builds and tests

### Motion + integration: seams first

- **Server skeleton first:** the Python project, a folder per lane, and stubs for the arbiter and the skill API, so Grant and Nick don't each create `server/` (decision 0050).
- **Contract v1 with John,** starting from what the firmware already speaks (C-1). `contract/` gets schemas and samples captured from the real robot.
- **Mock robot** that behaves like the firmware, including needing a start command before it balances.
- **Server link and arbiter:** the UDP link and the arbiter (e-stop > manual joystick > skills), so the same server drives either the mock or the real robot.
- **Firmware changes with John:** JSON start, park and exact turns; park at the run limit; telemetry in radians; fixed fault names; kickstand mode (C-5 to C-9). Every change passes CI and the bench check in `firmware/README.md`; `fw-known-good` is the way back.

### Vision and understanding: on the desk

- **Camera:** a laptop webcam or a second camera, behind a frame-source interface. The phone page plugs in later without changing anything else (T-4, T-10).
- **Perception:** MediaPipe person and hand tracking on every frame, with a debug window showing boxes and the recognized gesture.
- **Follow-me and gestures:** the person's position and size become speed and turn targets that go to the arbiter. Start from John's follow gains and upper-body tracking (`firmware/README.md`, "Next, by lane"). The result shows on the mock robot and the dashboard. Walk around the desk to test it.
- **Skill runner:** runs one skill at a time and sends its targets to the arbiter.
- **Speech and the brain:** the phone's mic through the phone page (T-13), or push-to-talk on the laptop until then; speech to text, then Claude picking skills. Gemini sits behind the same interface.
- **Memory:** the world memory store from `03-software.md`. Perception and skills write to it, and a summary goes into every LLM call.

### Misc: everything people see, plus filling gaps

- The server's WebSocket API and the dashboard (e-stop, joystick, telemetry plots), built against the mock robot.
- The phone page: face, camera frames, mic and motion sensors to the server, and Miguel's voice back, over HTTPS.
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
| Arm pose names: wave, point, push, tuck | Misc (desk) and the firmware | Alex | `contract/` |

## Timeline by lane

Times are Sat/Sun ET, from Sat 1 pm. Checkpoints in bold come from `milestones.md`.

| When | Alex (motion + integration) | Grant (vision + understanding) | Nick (misc) | John (hardware + firmware) |
| --- | --- | --- | --- | --- |
| Sat 1-3 pm | Server skeleton; contract v1 agreed with John | #3: frames + MediaPipe on the skeleton | Server WebSocket API; phone page started | Hotspot + `linktest.py` (first Wi-Fi test); tilt the phone up 15-20° |
| **Sat 2 pm** | **Go/no-go on balancing:** effectively go; it balances hands-off | | | |
| Sat 3-6 pm | `contract/` + mock robot; server link + arbiter | Follow skill (John's gains); stop gesture | Phone page: camera + face; dashboard joystick; #8 once the contract lands | Firmware changes for contract v1; kickstand mode |
| **Sat 6 pm** | **First end-to-end slice:** a person in front of the phone, the server decides, the mock follows; then the real robot over Wi-Fi | | | |
| Sat 6 pm-12 am | Real robot through the server; run script | Agent (Claude picks skills); speech | Mic and voice on the phone page; companion panel | Battery reading; arm mount; trim re-check |
| Sun 12-5 am | Robustness; demo path | Use-case skills; tuning in a noisy room | Pitch, Devpost draft, backup video | Robot spares, charged batteries |
| **Sun 5 am** | **Feature freeze:** bug fixes only | | | |
| Sun 5-7 am | Rehearse the demo; fix only what breaks it | | Submit on Devpost by 7 am | |
| **Sun 9:30 am** | **Judging:** in-person demo, max 2 min | | | |

The use case and main track (P-1, P-2) were due at noon: pick them as soon as possible, since the evening's skills depend on them.

Sleep in shifts. John sleeps when the robot isn't needed; someone who knows the server is awake at each checkpoint.

## How we work

- **Everyone runs their own agent.** Claude Code reads `CLAUDE.md`; Cursor and Codex read `AGENTS.md`, which points to it.
- **One task = one issue = one branch = one PR** that says "Closes #N". Tasks are 1-3 hours. Each issue has a lane label (`lane:motion`, `lane:vision`, `lane:misc`); assign yourself before starting. Branch name: `<lane>/<N>-short-name`.
- **Pull main before each task.** Keep PRs small; tests pass before opening one.
- **Stay in your lane's folders.** A PR that touches another lane's folder says so and gets that lane's OK.
- **Merging to main:** anyone may push or merge to main, but only when their human asks for that action. Branches, PRs, issues and comments need no permission.
- **Alex's agent is the master agent:** it organizes the work: issues, milestones, decisions and keeping the docs in sync. Main always runs against the mock robot. Pull main after any merge your lane depends on.
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
| Alex carries the seams, the server core and organizing | Skeleton and contract land first; anyone can merge their own PRs; Nick takes server or run-script issues when Alex is behind |
| A firmware change breaks balancing | CI compiles every PR; the five-minute bench check after every upload; reflash `fw-known-good` |
| Vision needs a camera while the iPhone is on the robot | A second camera for the desk: a teammate's phone or an MLH Logitech webcam |
| Arm motion knocks it over | Kickstand down before using the arm; keep the arm light and close to the mast |
| Wi-Fi lag or drops at the venue | Own hotspot; the robot balances on its own and stops after 300 ms without commands |
| Robot falls and breaks the phone | Crash bars at the top, kickstand when idle, test with a dummy weight first |
| LiPo damage | Fuse, low-voltage cutoff, charge in a LiPo bag |
| Crowded demo floor | Short scripted demo in a cleared ~2 m square |
| Speech in a loud venue | Push-to-talk or a mic close to the speaker |

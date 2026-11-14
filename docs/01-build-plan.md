# Build plan

Draft. Software doesn't wait for the robot: every piece is built and tested on the desk or against a mock robot, then moves onto the real robot once it passes a bench test. Vision and understanding come first, because without them there is no project.

## Principles

- **One seam:** the laptop-robot message contract. The mock robot and the real robot speak the same messages, so swapping one for the other changes nothing else.
- **Bench before robot:** each part is proven on the desk (loose motor, loose IMU, loose arm, phone in hand) before it goes on the robot.
- **Always demoable:** every stage leaves something to show (see Fallback demo tiers below).

## Workstreams

| Priority | Workstream | Build now, without the robot | Bench test passes when | Then on the robot |
| --- | --- | --- | --- | --- |
| 1 | Vision + understanding | Phone or webcam on the desk streaming to the laptop; the mock robot shows the commands | It follows a person, obeys gestures and acts on one spoken request, all visible as commands on screen | Phone in the mast cradle |
| 2 | Motion (balance + drive) | One motor, driver and ESP32 on the desk, wheel spinning in the air; the IMU on the desk, tilted by hand; a small balance simulation using the CAD numbers | Wheel speed follows commands; tilt reads correctly; the simulated robot stays up | Tethered balance (T+10), then driving before the T+18 go/no-go |
| 3 | Arm | Servos and the BusLinker on the desk, driven from the laptop | Named poses work: wave, point, tuck | Mounted on the mast, commanded through the robot |
| 4 | Panel + glue | Dashboard against the mock: e-stop, joystick, live plots, companion panel | One command starts everything against the mock | The same, pointed at the real robot |

**First milestone (proposed T+8, Sat 4 am):** a person walks in front of the phone, the laptop decides, and the command reaches the mock robot while a loose wheel on the desk turns the right way. That proves the whole chain before any balancing.

**Already overdue:** the contract and mock robot (planned for T+1). They come first, since every workstream builds against them.

**What could sink the project:** vision and understanding not working (start now, desk-only, simplest pipeline first); balancing not working (kickstand mode keeps the demo alive).

## Team

John Huang owns the whole hardware stack; three people (Grant Ji Kim, Jialang Zhao and a third) write the software. The split among the three isn't decided; for now one agent does everything and work gets delegated when needed.

Proposed role split (from John's brief, not decided):

| Role | Owns | Person |
| --- | --- | --- |
| Hardware | Frame, wiring, power, the physical robot | John Huang |
| Firmware / controls | Balancing, motors, safety cutoffs, robot-laptop link, kickstand mode | TBD (maybe John) |
| Robot software + integrator | Robot service, dashboard (e-stop, joystick, live plots), merges, run script, demo path | TBD |
| Vision / AI + pitch | Video from the phone, follow-me, gestures, voice/language, Devpost, demo script, backup video | TBD |

## Timeline

Checkpoints are in `milestones.md`; tasks are GitHub Issues.

## Fallback demo tiers

1. Balances and follows.
2. Kickstand mode: it rests on the printed kickstand and drives with the same commands.
3. "Smart mast" on the table: the phone tracks the judge, plus the dashboard and recorded clips.

## Risks

The top risk is balancing eating the whole weekend, leaving no time for the parts judges actually see.

| Risk | Fallback |
| --- | --- |
| Balance tuning takes too long | Kickstand mode, so every other feature still demos |
| Arm motion knocks it over | Kickstand down before using the arm; keep the arm light and close to the mast |
| Wi-Fi lag or drops at the venue | Own hotspot; the robot balances on its own and stops after 300 ms without commands |
| Robot falls and breaks the phone | Crash bars at the top, kickstand when idle, test with a dummy weight first |
| LiPo damage | Fuse, low-voltage cutoff, charge in a LiPo bag |
| Crowded demo floor | Short scripted demo in a cleared ~2 m square |
| Speech in a loud venue | Push-to-talk or a mic close to the speaker |

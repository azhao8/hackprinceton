# 0053: The phone page is the robot's eye; every control is on the control page

- Date: 2026-11-14
- Status: accepted
- Source: Alex, robot session Sat afternoon; issue #39
- Agreed by: Alex

The phone is mounted on the robot, so nobody can reach its screen. The phone page only connects the phone's camera, tracking and speaker to the server (one Start tap, because Safari needs a tap before it allows the camera and sound). Every control lives on the control page on the laptop: STOP/Release, follow on/off and its settings (mode, speed cap, stop distance), voice on/off, lines to say, and driving.

## Alternatives

| Option | Critique |
| --- | --- |
| **Controls on the control page; phone is sensors only** | Reachable while the robot moves; one place to look; the phone screen is free for the face |
| Controls on both | Two places that can disagree; the phone's can't be reached anyway |
| Controls on the phone | Unreachable once it's mounted |

## Reversibility

Easy: settings live on the server, and either page can show them.

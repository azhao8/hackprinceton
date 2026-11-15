# 0059: Start waits until the robot is upright and steady; the phone can start, park and recalibrate

- Date: 2026-11-15
- Status: accepted
- Source: Alex, Sun 3 am; issue #79
- Agreed by: Alex

Start can be pressed any time, on the control page or the robot's phone. The server then waits, up to 60 s, until the robot is held upright and steady (tilt within 3° of the trim and its rate low, for 1 s), and sends `g` itself. No confirm box. STOP, Park, Cut motor power and Cancel start end the wait. The firmware's own 6° check still applies.

The server watches for a drifting tilt sensor (a steady gyro rate while the tilt stays put, motors off; `server/app/robot_watch.py`). While it drifts, Start is refused and Miguel says why out loud. The control page and the phone show a warning with a Recalibrate button.

The robot's phone (on the hotspot, never through a tunnel) can Start, Cancel start, Park and Recalibrate (`POST /phone/action`). This replaces decision 0054's "this laptop only" for these four. Skills, the agent and the follow loop still can't send `g`.

Also from this round: the voice agent's `move` skill may take a speed, but only when the person asked for one; the server clamps it (0.05 to 3.2 m/s, 0.1 to 1.5 rad/s). This bends the rule "the LLM never sends speeds": the LLM still picks skills, and the skill drives through the arbiter, so STOP and the joystick win.

## Alternatives

| Option | Critique |
| --- | --- |
| **Server waits for upright and steady, then sends g** (standard: no) | Start works from anywhere, and a person is still holding it when it starts |
| Immediate g with a confirm (0054) | Needs the press at the exact moment someone holds it upright |
| Firmware arms itself when upright | Firmware change and a bench check, and it's still the same check |

| Option | Critique |
| --- | --- |
| **Phone controls on the hotspot** (standard: yes, like `/auto` and `/frame`) | The person at the robot can act; anyone on the hotspot could too, the same trust `/auto` already has |
| Laptop only | Can't do what was asked |

## Why this one

The person tapping the phone is at the robot, and `/auto` already lets a hotspot device drive it. The drift signature can't come from a real rotation: the tilt would move with it. It was checked on recorded patterns in tests (`server/tests/test_robot_watch.py`), not yet on the real robot (guess: thresholds may need tuning).

## Reversibility

Easy: one route, one watcher module, and the Start button's message.

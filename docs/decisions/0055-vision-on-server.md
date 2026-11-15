# 0055: Vision runs on the server; the phone is the robot's eye and face

- Date: 2026-11-14
- Status: accepted
- Source: Alex, Sat afternoon (T-11, T-10); issue #46
- Agreed by: Alex

The robot's phone page shows Miguel's face, streams its camera to the server (JPEG frames, ~12 a second, 640 px) and plays the voice. It does no tracking. The server runs the vision (Grant's pipeline) and the one follow skill, which drives through the arbiter like everything else. The control page shows the server's view: the phone's frame with the server's boxes. John's bench tool keeps its on-phone tracking for tuning only.

## Alternatives

| Option | Critique |
| --- | --- |
| **Vision on the server** | One brain: follow, the agent and the control page share one view; any Python model on the laptop's GPU. ~150-250 ms from camera to robot (uploading frames is the extra) |
| Vision on the phone (John's page) | ~100 ms, already worked on the robot, but two follow systems and the server can't see |
| Both (phone follows, server sees for the agent) | Lowest follow lag, but two pipelines to keep in sync |

## Reversibility

Moderate: the phone page keeps its tracking code for the bench tool, so going back is a mode switch.

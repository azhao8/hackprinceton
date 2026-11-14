# 0049: Commands carry seq; telemetry echoes it as ack

- Date: 2026-11-14
- Status: accepted
- Source: issue #13
- Agreed by: Alex

Every JSON command may carry `seq`, a counter the laptop raises on each command. Telemetry carries `ack`, the last `seq` the robot received (0 until one arrives). It tells the laptop whether its commands reach the robot (telemetry alone only proves the other direction), plus round-trip lag. `seq` is optional, so older senders keep working.

## Alternatives

| Option | Critique |
| --- | --- |
| **seq/ack** (standard: MAVLink and TCP number messages the same way) | Shows commands arriving, lag and gaps; a few lines of firmware |
| `cmd_age` in telemetry (ms since the last command) | Even simpler and shows whether commands arrive, but can't measure lag |
| Separate ping messages | More messages for the same result |
| Nothing | The dashboard can look connected while the robot ignores every command |

## Reversibility

Easy: both fields are optional and additive, so anything that doesn't know them ignores them.

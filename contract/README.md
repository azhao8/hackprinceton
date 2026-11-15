# Robot contract (v1)

The messages between the laptop server and the robot's ESP32. **v1 is exactly what the firmware speaks today** (`firmware/balance/balance.ino`, plus `seq`/`ack` from #14). Changes still being discussed are listed at the bottom; none of them is applied.

Only the server's link code (`server/app/link/`) and the mock robot (`server/mock/`) speak this. A change here updates the mock and the firmware in the same PR (CLAUDE.md). The messages between the server and the web app are separate, in `web/`.

## Transport

| | Wi-Fi (the product path) | USB (bench) |
| --- | --- | --- |
| Where | UDP port **4210**; the robot is `balancebot.local` (mDNS) on our own hotspot | Serial, 115200 baud |
| Framing | One message per packet, no trailing newline | One JSON object per line |
| Telemetry | 20 times a second, to whoever sent the last packet | One line per `J` command |

The mock robot (`cd server && uv run python -m mock`) speaks the same UDP messages on `127.0.0.1:4210`.

## Laptop to robot

**`cmd`**, about 20 times a second while the laptop wants control. Schema: `schema/cmd.schema.json`.

```json
{"t":"cmd","seq":812,"v":0.3,"w":0.0,"mode":"drive"}
```

| Key | Meaning |
| --- | --- |
| `seq` | Optional counter, raised on every command. Telemetry echoes it as `ack` |
| `mode` | `drive` (default): follow `v` and `w`. `balance`: stop and hold here. `idle`: motors off |
| `v` | Forward speed, m/s, + forward. Clamped to ±3.2 (`VMAX`: only the step generator's ceiling; the steppers stall sooner) |
| `w` | Turn rate, rad/s, + turning left. Clamped to ±1.5 |

- **No `cmd` starts balancing.** If the robot isn't balancing, `drive` and `balance` are ignored. `idle` always turns the motors off.
- **Watchdog:** if `drive`/`balance` commands stop for 300 ms, speed and turn go to 0 and the robot holds position.
- **E-stop** (decision 0043) is the server sending `v` = `w` = 0 (or `mode: balance`); the robot keeps balancing.

**One-letter commands.** A UDP packet that doesn't start with `{` is read as one-letter commands, the same as on USB. The ones the server may send:

| Letter | What it does |
| --- | --- |
| `g` | Start balancing. Only works while the robot is held within 6° of upright; a person must be holding it |
| `x` | Motors off now |
| `P` | Park: lean back onto the kickstand, then motors off. **The kickstand was removed (Nov 14, 9 pm): Park tips the robot over** until the firmware is changed; hold it and send `x` instead |
| `5` | Stop and hold here |
| `L` / `R` | Turn exactly 90° left / right on the gyro |
| `F` / `B` | Drive exactly 0.5 m forward / back |
| `c` | Recalibrate the tilt sensor (gyro zero); only while not balancing, robot still for 2 s |
| `t` / `y` | Raise / lower the balance angle (trim) by 0.25°. Several in one packet shift it several steps. Lost when the robot reboots |

The rest (gain tuning, tests) are for the bench; see the top of `balance.ino`.

## Robot to laptop

**`tel`**, 20 times a second over UDP. Schema: `schema/tel.schema.json`.

```json
{"t":"tel","pitch":5.71,"rate":-1.8,"vl":0.000,"vr":0.000,"batt":null,"state":"balance","fault":null,"x":0.012,"yaw":0.4,"ack":814}
```

| Key | Meaning |
| --- | --- |
| `pitch` | Tilt, **degrees**, + leaning forward. Balances near the trim: −3.65 since the kickstand came off (Nov 14, 9 pm) |
| `rate` | Tilt rate, **degrees per second** |
| `vl`, `vr` | Left and right wheel speed, m/s, + forward |
| `batt` | Battery volts. Always `null` today (C-10) |
| `state` | `idle` (motors off, also when parked), `balance` (holding), `drive` (moving or turning) |
| `fault` | Why the motors last turned off, free text (`"stop command"`, `"fell over (tilt > 30 deg)"`); `null` after `g` |
| `x` | Distance driven since `g`, m (not a room coordinate) |
| `yaw` | Heading since `g`, **degrees**, + left |
| `ack` | `seq` of the last JSON command received; 0 until one arrives |

Directions follow ROS REP 103: x forward, y left, z up. **Front = the battery side.** Readers ignore keys they don't know, so new keys can be added without breaking anyone.

## Safety (on the robot, no Wi-Fi needed)

- Motors cut if the tilt is more than 30° from the trim.
- Each `g` run parks itself after 30 minutes.
- Agents never send `g`, motion, or turn/move commands unless their human says someone is at the robot (CLAUDE.md, `firmware/README.md`).

## Samples and tests

- `samples/` has one file per message variant. They follow the firmware's format strings; recapture `tel` samples from the robot with `J` when it's next on the bench.
- `server/tests/test_contract.py` checks every sample and the mock's telemetry against the schemas, and drives the mock over real UDP.
- `firmware/balance/linktest.py` works against both the robot and the mock.

## Proposed changes (C-1, not applied)

Each needs the team's OK and a firmware change with John, and then updates the schema, the mock and the samples in one PR.

1. Telemetry angles in radians (`pitch`, `rate`, `yaw`), matching SI and what the dashboard expects (#8).
2. `fault` from a short fixed list (`tilt`, `run_limit`, `stop`, `idle`) instead of free text.
3. JSON forms of `g`, `P` and exact turns/moves (C-5, C-6), so the server sends only JSON.
4. Kickstand mode (C-9).
5. Battery volts (C-10, needs hardware).

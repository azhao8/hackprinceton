# Firmware and bench tools: start here

_Updated Sat Nov 14, around noon ET, by John (hardware) and his Claude. Everything here was written at the event and tested on the real robot._

## Where the robot is
- **It balances hands-off with the phone mounted.** Tilt stays within ~1° and drift under 5 cm. It balances for minutes on the USB tether, so the "Tethered balance" milestone is met.
- **It drives** from a keyboard web page on a laptop, over USB:
  - up to 0.6 m/s
  - 90° gyro turns and 50 cm moves
  - it parks itself on the kickstand
- **It follows a bright yellow object** through the iPhone (Continuity Camera and Apple Vision, on John's Mac).
  - It locks onto one object and ignores other yellow things.
  - Its longest run was ~10 m, and it has driven ~75 m of hallway in total.
- **It speaks the contract from `docs/03-software.md`:** `{"t":"cmd",...}` in, `{"t":"tel",...}` out.
  - Over USB serial: works now.
  - Over UDP port 4210: written but untested, because it needs a hotspot.
- **Not done yet:**
  - self stand-up with the phone on (disabled)
  - kickstand mode
  - battery voltage reading
  - Wi-Fi (needs a hotspot)
  - person following (the camera angle is wrong, see below)

## Files
| Path | What |
| --- | --- |
| `balance/balance.ino` | The firmware on the robot now (ESP32-S3, Arduino core 3.3.12): balance loop, drive, turns, moves, park, USB and UDP JSON link, 300 ms watchdog, tilt cutoff. Every command is listed at the top of the file |
| `balance/secrets.example.h` | Copy to `balance/secrets.h` (git-ignored) and type in the hotspot name and password yourself. Without it, the firmware builds with Wi-Fi off |
| `balance/drive.py` | Bench tool: hold-to-drive keyboard page at http://localhost:8765, over USB. It's also the bridge that `follow` posts to |
| `balance/teleop.py` | Bench tool: keyboard driver in the terminal, over Wi-Fi (UDP 4210). Untested |
| `balance/follow/` | Bench tool: `follow.swift`, camera follow (a yellow object or a person) using Continuity Camera and Apple Vision. Build with `./build.sh` |
| `bringup/bringup.ino` | The first bring-up sketch: prints the IMU, spins the motors |
| `bringup/HARDWARE-NOTES.md` | **Read this before changing gains, trim or wiring.** Every setting, test and lesson from bring-up |

The bench tools talk to the robot directly. They're for testing and tuning only. The product path is still the server's link and arbiter (see `CLAUDE.md`), speaking the same messages.

## Robot frame (it differs from the CAD)
- **Front = the battery side.** That's also the kickstand side and the direction the phone's rear camera faces. The CAD drew it the other way round, so the CAD's left and right are swapped too.
- **Axes follow ROS REP 103** (x forward, y left, z up):
  - Pitch positive = leaning forward. Yaw positive = turning left.
  - `v` is in m/s. `w` is in rad/s, with left positive.
  - In telemetry, `pitch` and `yaw` are in degrees and `rate` is in deg/s.
- **Pins:**
  - Right wheel: STEP IO4, DIR IO5 (forward = DIR high).
  - Left wheel: STEP IO6, DIR IO7 (forward = DIR low).
  - EN: IO15 for both drivers (LOW = on).
  - MPU-6050: SDA IO8, SCL IO9, address 0x68.
  - 1/16 microstepping = 3200 steps/rev. Wheels are 85 mm.
- **Power:** 3S LiPo → 15 A fuse → 12 V Wagos → the drivers and the buck converter (5.0–5.1 V) → the ESP32's 5Vin, through a red jumper.
  - **While USB is connected, pull that jumper out.** The ESP32 then runs from USB.
  - Never have both connected at once.

## Run it (a Mac, the robot on USB, someone at the robot)
1. Plug in the battery. Run USB-C from the laptop to the ESP32's **COM** port (CH343 chip, shows up as `/dev/cu.usbmodem…`). Pull the red jumper out.
2. Run `cd firmware/balance && python3 drive.py`. The page opens at http://localhost:8765. Click it so it has focus.
3. Hold the robot upright, press **G**, and let go once it's holding itself. Then:
   - W A S D / arrows: drive (hold to go). Space: stop.
   - Q / E: turn 90°.
   - P: park. X: motors off.
   - Top-speed slider: 0.1–0.6 m/s (starts at 0.3).
4. **Follow (John's Mac only):** run `cd firmware/balance/follow && ./build.sh && ./follow --yellow`, then press **F** on the page.
   - Holding a drive key overrides it. X stops it and turns Follow off.
   - Knobs: `--distance` (bigger = stops closer, default 0.35) and `--speed` (default 0.4).
   - The camera is John's iPhone, on his Apple ID, with Wi-Fi and Bluetooth on.
   - A person has to start `follow` in Terminal. macOS gives the camera only to programs a person starts, so a copy launched by an agent gets "Camera access denied".

## Build and upload
- **Toolchain:** `arduino-cli` with the `esp32:esp32` core **3.3.12** (`arduino-cli core install esp32:esp32@3.3.12`). Not PlatformIO yet (see the open questions).
- **Stop `drive.py` first.** Only one program can hold the USB port.
- **Upload:** `cd firmware/balance && arduino-cli compile --upload --fqbn esp32:esp32:esp32s3 -p <port> .` (`arduino-cli board list` shows the port).
- **After every upload or reboot,** keep the robot still for 3 s. It calibrates the gyro at boot.

## Before merging a firmware change
- **Leave the balance loop alone** unless the change is about balancing. Change the command handling and telemetry around it.
- **Keep the USB status line exactly as it is.** `drive.py` reads it.
- **CI compiles every PR** (`.github/workflows/ci.yml`). A PR that doesn't compile doesn't merge.
- **Bench check after every upload,** about five minutes, with someone at the robot:
  1. Keep it still for 3 s at boot (gyro calibration).
  2. `g`: balances hands-off for 30 s.
  3. `drive.py`: forward, back, left, right; Space stops and holds.
  4. `L` / `R`: 90° turns.
  5. `P` parks on the kickstand; `X` turns the motors off.
  6. Write the result in the PR.
- **If something regresses, go back to the last known-good firmware:** `git checkout fw-known-good -- firmware/balance/balance.ino`, then upload. The tag `fw-known-good` points at John's firmware that balances with the phone on (Sat noon). Move the tag only after a change passes the bench check.

## The link it speaks today
It listens on USB serial at 115200, and on UDP port 4210 over Wi-Fi (mDNS name `balancebot.local`).
- **In:** `{"t":"cmd","v":0.3,"w":0.0,"mode":"drive"}`, about 20 times a second.
  - `v` is clamped to ±0.6 m/s and `w` to ±1.5 rad/s.
  - `mode` is `drive`, `balance` (hold position) or `idle` (motors off).
  - If no cmd arrives for 300 ms, speed and turn go to 0 and it holds position. That's the e-stop behavior from decision 0043.
- **Arming is separate.** The plain one-letter packet `g` starts balancing, but only while the robot is held within 6° of upright. Other one-letter commands:
  - `x`: motors off. `P`: park. `5`: stop and hold.
  - `L` / `R`: 90° turns. `F` / `B`: 50 cm moves.
  - `c`: recalibrate the gyro (robot still). `p`: print gains.
  - `i`: telemetry. `h`: 50 Hz CSV log.
- **Out (UDP only, 20 Hz, to whoever sent the last packet):** `{"t":"tel","pitch":..,"rate":..,"vl":..,"vr":..,"batt":null,"state":"idle|balance|drive","fault":null,"x":..,"yaw":..}`. Over USB, `i` prints a readable line instead, which drive.py parses.
- **Differences from `docs/03-software.md`:**
  - no `kickstand` mode
  - telemetry is 20 Hz, not 50
  - `batt` is always null (no voltage sensing)
  - angles are in degrees
  - UDP packets have no trailing newline

## Safety rules (people and agents)
- **Agents: never send motor commands** (`g`, `G`, `T`, `F` / `B`, `L` / `R`, or drive JSON) unless your human says someone is at the robot and ready to catch it.
  - End every scripted test with `x`, even when it fails.
  - Once, a script without a final `x` let the robot chase across the floor for 2.4 m.
- **Press X or P before anyone touches it.** Past 30° of tilt, the motors cut by themselves.
- **One `g` run lasts 5 minutes** (`RUN_MS`). Then the motors cut and it tips over, so park or re-arm before then.
- **No self stand-up (`G`) with the phone on.** It failed 3 of 5 times, so drive.py and teleop.py block it.
- **Keep the USB cable slack.** A tug reboots the ESP32. After a reboot, keep it still for 3 s, then restart drive.py. It doesn't reconnect by itself.
- **Re-check the trim whenever anything is added** (the arm, a tray). A few mm of center-of-mass shift moves the balance point by degrees. Use the locked-wheel test in `bringup/HARDWARE-NOTES.md`.
- **LiPo:** charge in balance mode (3S, 2.2 A), with someone watching. Below ~10 V on the buck's IN display, stop and charge.

## Tuned values (phone on, no arm)
- **Gains:**
  - KT 0.443 m/s² per deg
  - KW 0.072 per deg/s
  - KV 3.0
  - KX 2.0
  - KI 0.77 (only while holding still)
- **Trim and lean:** trim −1.25°, FF_RR 0.5°, FF_CREEP 0.6°.
- **Tilt estimate:** complementary filter 0.99 with a/g compensation, gyro-only during hard moves. Accelerometer at ±4 g.
- **Timing:** 200 Hz loop, 40 kHz step interrupt.

## Open questions for the team
1. **PlatformIO (decision 0040).** The code uses the core 3.x timer API, and PlatformIO's official ESP32 platform ships core 2.x. Options:
   - the pioarduino platform (core 3.x)
   - a port to core 2.x / FastAccelStepper
   - arduino-cli for the weekend

   John's pick: arduino-cli until after the demo, since it already builds and uploads from the command line. It's easy to reverse.
2. **The contract differences** (listed above): change the doc or the firmware? The mock should match whichever wins.

## Next, by lane
- **Motion + integration (Alex):**
  - `contract/` and the mock, from the messages above
  - the server link over UDP, once there's a hotspot
  - kickstand mode and battery reading
  - park at the run limit instead of cutting the motors (John's Claude has this queued)

  The balance sim and the desk rig probably aren't needed for balancing anymore.
- **Vision (Grant):**
  - **The camera angle:** it sits ~40 cm off the floor and aims low, so it sees a standing person only from the waist down. Tilt the phone up 15–20°: as built, the hinge tilts it down, so tilt it the other way, or flip the phone and use `--camera-back`. Or track legs and feet instead.
  - **Follow gains that worked on the robot:**
    - turn `w = −2.5·(cx − 0.5)`, with a 0.06 dead zone, capped at ±1.2 rad/s
    - speed proportional to how far off the target is (0.35 m/s when it's twice as far as wanted), with a 0.08 dead zone, from −0.15 to +0.4 m/s
    - 0.6/0.4 smoothing
    - stop after 0.5 s without the target
- **Misc (Nick):**
  - The dashboard can show the real telemetry fields above.
  - Material for the demo and the backup video: the yellow follow, the push test, the square drive.
- **Hardware (John):** at the robot for every real test.

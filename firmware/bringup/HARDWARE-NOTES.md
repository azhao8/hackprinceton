# Hardware facts for the firmware (tested Nov 14, 2026, overnight)

_Paths in this file are relative to `firmware/`. Start with `firmware/README.md` for the current state._

**Front of the robot = the BATTERY side.**

| What | Pin / value | Tested |
|---|---|---|
| Right wheel (driver board A) | STEP = IO4, DIR = IO5, forward = DIR HIGH | yes |
| Left wheel (driver board B) | STEP = IO6, DIR = IO7, forward = DIR LOW | yes |
| Enable, both drivers | IO15, LOW = motors on. Set HIGH at boot | yes |
| Microstepping | 1/16 (MS1 + MS2 on), 200-step motors = 3200 steps/rev | yes |
| IMU | MPU-6050 on I2C, SDA = IO8, SCL = IO9, address 0x68, 400 kHz | yes |
| Pitch axis | tiltY = atan2(-ax, sqrt(ay² + az²)); gyro Y. Leaning toward the front (battery side) = POSITIVE | yes |
| Gyro offsets at rest | gyro X ≈ -9 °/s (subtract it); Y and Z ≈ 0–2 °/s | yes |
| Level reading | raw tiltY ≈ -4° when sitting level, so calibrate the zero | rough |
| Driver logic power | driver boards' V pins wired to ESP32 3.3 V | yes |

Note on the pitch sign: in the raw readout from `bringup.ino`, tilting toward the battery side made `tiltY` go **positive**. Use that directly.

**Power and USB**
- Battery: 3S LiPo through a 15 A fuse to the +12 V Wago. Read 10.8 V at the first power-up, so charge it. Stop below about 10 V.
- The buck converter is set to 5.0–5.1 V and feeds the ESP32's 5Vin through a red jumper.
- **When a laptop is on USB, pull that red jumper out of the buck's OUT+.** Never have USB and the buck's 5 V connected at the same time.
- Upload through the ESP32's **COM** USB-C port (CH343 chip, shows up as /dev/cu.usbmodem…). The other port is not detected by the laptop.
- Build: `arduino-cli compile --fqbn esp32:esp32:esp32s3 --upload -p /dev/cu.usbmodem5CBB0253961 bringup`

**Wiring changes from the CAD/guide**
- The Wagos are stuck to the mast (not in the printed Wago frame), because the wires were too short.
- On the driver boards the DIP switches are labeled MS3, MS2, MS1 from left to right: MS3 off, MS2 on, MS1 on.

## First balance test (Nov 14, overnight): IT BALANCES
Program: `balance/balance.ino`. Steppers take an acceleration command `a = KX*x + KV*v + KT*(pitch - trim) + KW*rate`
(KT 0.785 m/s² per deg, KW 0.105 per deg/s, KV 3.0, KX 2.0), integrated into wheel speed; 40 kHz timer interrupt makes the steps.
The complementary filter (0.99) adds back `a/g` to the accelerometer angle; without that the simulation fell in about 2 s.
- Ran the full 20 s on the USB tether, battery 11.3 V. Pitch stayed within about ±1.5° of trim, speed within ±0.3 m/s, drift under 35 cm.
- Mean pitch error +0.5° with trim -2.5°, so the real balance point is about **-2.0°**.
- Gyro Y bias at rest about 1.5 °/s (calibrated at boot; send `c` to redo it while still).
- Rate noise about 10 °/s RMS: some fast wobble. Tune KW down a little if it buzzes.
- ~~Damping sweep said KW 0.127–0.153 was calm~~: **wrong**, those calm stretches were John's hand on the mast. Hands-off at KT 0.785 / KW 0.139 it wobbles at about **5 Hz, ±1.3°** (never fell). Simulation matches if the motors respond 30–50 ms late (likely the TMC2209 StealthChop mode).
- Next try (set live): **KT 0.443/deg, KW 0.054/(deg/s)**, the most delay-tolerant pair in simulation.
- It also drifted backward ~45 cm per 25 s and ignored a 0.1 m/s forward command, so the trim is about 1° off and/or KX is too weak.
- **Softer gains work:** hands-off at KT 0.443 / KW 0.054 the wobble is gone (rate 1.3–1.5 °/s RMS, tilt within ±0.3°). It still crept backward ~17 cm in 17 s; trim moved to **-1.25°** (now the default in balance.ino).

## Mass properties as actually built (no phone, no arm): recomputed Nov 14
The first gains used the full CAD (phone + arm on). Without them:

| | Full CAD (phone + arm) | As tested (no phone, no arm) |
|---|---|---|
| Body mass | 1.96 kg | 1.52–1.58 kg |
| CoM above axle | 93 mm | **37–45 mm** (the 780 g of motors sit on the axle) |
| Effective pendulum length | 0.25 m | **0.12–0.15 m** (falls ~1.5× faster) |
| Balance point shift per 1 cm of battery slide | ~0.6° | **~1.9°** |

What that explains: the ~5 Hz wobble at the original gains (faster pendulum + 30–50 ms motor lag), and the "leaning but not moving" behavior (any small shift of the battery or wires moves the balance point by degrees).

Gains from simulation with 30–50 ms motor lag:
- **No phone/arm:** KT 0.26–0.44/deg with KW ≈ 0.052/(deg/s). Narrow window: KW 0.07 already wobbles.
- **With phone + arm (or ~200 g taped at the mast top):** KT 0.35–0.52/deg with KW 0.07–0.105. A much wider stable window, and 3× less sensitive to battery shifts. **Mount the phone for balancing tests.**

## The balance point was wrong by about 2° (found Nov 14)
John noticed that, held, the robot stays put when leaning slightly **toward the battery side**: the as-built CoM sits a little toward the Wago side of the axle (the opposite of the CAD's -2.6 mm, which assumed the phone and arm and the original Wago/wire placement).
The locked-wheel test agrees: it stood still for 8 s at **+0.65°** and fell toward the Wago side from +0.2°.
The program had trim -1.25°. A 1.9° trim error exactly explains the repeated "parks 30–40 cm behind its target, leaning forward ~1.7–1.9°" result: at equilibrium KT·1.9° ≈ KX·0.42 m, so the robot is really balanced, just in the wrong place.
- **Trim is now +0.5°** (live and the default in balance.ino).
- With the CoM only ~40 mm above the axle, **1 mm of CoM shift moves the balance point ~1.4°**, so re-check the trim whenever anything is added, moved or re-taped.

## Driving works (Nov 14, ~5 AM)
Final settings (defaults in balance.ino): KT 0.443, KW 0.054, KV 3.0, KX 2.0, **KI 0.77** (only while holding still), **trim +0.5°**, **FF_RR 1.25°**, speed ramp 0.4 m/s².
Drive test, hands-off, on the USB tether, commanded 0.2 m/s for 3 s each way:

| | Target | Result |
|---|---|---|
| Forward | 56 cm, then stop | 49 cm during the drive, stopped 6 cm past target |
| Back | 56 cm, then stop | 54 cm during the drive, max 0.26 m/s, stopped 5 cm short |
| Hold during turn + stop | 0 | ended 4 cm off |

How it got there: wrong trim (-1.25 → +0.5) made it park 30–40 cm short; smooth stops plus an integral that only runs while holding killed the overshoot; a lean feedforward (atan(a/g) + 1.25° rolling-resistance lean) removed the 1.5–3 s start lag.

## Stands up and parks by itself (Nov 14, ~6 AM)
- **`G` = stand up from the kickstand:** the target angle swings from the kickstand angle (measured each time, 10.6–13° depending on the surface) to trim over 0.4 s. It is upright in ~0.7 s, overshoots ~1–2°, and rolls 10–22 cm toward the battery side. Aborts if still on the kickstand after 1.2 s or if it hits top speed.
- **`P` = park:** quick 1 s lean toward the kickstand, then **lock the wheels** (motor holding torque) as soon as it passes kickstand−4°, exceeds 0.25 m/s, or 1.5 s pass, then release the motors 1.5 s later. It settles on the kickstand in under 1 s and moves ~1 cm.
- Two failed versions, for the record: cutting the motors at contact let it bounce off the kickstand and fall over backward; a slow 1.5 s lean made it chase the lean across the floor (~2.4 m). Leaning onto the kickstand needs sustained forward acceleration, so it has to be quick and end with locked wheels.
- teleop.py keys: `g` start while held upright, `p` park (`u`, the self stand-up, is disabled while the phone is mounted).

## Keyboard driving and faster limits (Nov 14, morning)
- `balance/drive.py` serves a hold-to-drive page at http://localhost:8765 (W/A/S/D or arrows; G start while held upright, P park, X off, Space stop, Q/E 90° turns, F follow). It sends the team's JSON drive command over USB at 20 Hz; the robot's 300 ms watchdog now runs without Wi-Fi too. Only one program can hold the USB port at a time.
- Wheel spin test (`T`, robot held up): both wheels smooth up to **1.0 m/s** (~225 rpm) at ~11 V battery. So VMAX (balance speed cap) is now 1.0 m/s, the drive top speed is 0.6 m/s, and the speed ramp is 0.5 m/s².
- Swapping the USB cable reboots the ESP32 (it runs from USB while the 5 V jumper is out): park first, keep it still for 3 s after plugging in.

## Phone mounted (Nov 14, morning): retune and stand-up trouble
- Balance point with the phone: **-1.25°** (locked-wheel test: stood still 5 s at -1.25°). Kickstand angle 11.3–11.7°.
- Gains with the phone: KW 0.072 (from 0.054); leans cut to FF_RR 0.5° and FF_CREEP 0.6° (the no-phone 1.25°/1.75° made it rock at 0.45 Hz). Hands-off result: tilt -1.2..0°, gyro 1.3 °/s RMS, drift < 5 cm. Best balance yet.
- **Self stand-up (G) with the phone failed 3 of 5 times; it is disabled on the drive page (use g, hand start).** Causes found in the logs:
  1. The a/g accelerometer correction fed back on itself: when the wheels were told to accelerate but the body did not move (kickstand drag or motor skip), the correction made the estimate say "leaning more", so it pushed harder (up to +35° of fake lean).
  2. The raw accelerometer went wild (±50–80°) during stand-ups: shaking and the ±2 g limit.
  3. A 3 m/s² stand-up cap made it rise too slowly, then hit the 1.0 m/s speed cap and fall.
  Fixes in balance.ino: gyro-only estimate during stand-up, hard acceleration, fast rotation, or when |acc| is not ~1 g; accelerometer at ±4 g; stand-up guard for 2.5 s (abort if > 0.7 m/s, tipping > 4° past the kickstand angle, or > 12° back). Simulation says a stand-up with the phone needs a fast 0.4 s ramp and peaks near 0.8 m/s, so it stays marginal; test it again only over something soft.

## Phone tilted up for person-follow (Nov 14, ~1:45 PM): new balance point +5.6°
- Tilting the phone up so the camera sees head and shoulders moved the balance point by about +7° (from −1.25°).
- Locked-wheel stands were at +2.7..+5.0°. That's a wide range, probably because the tire's contact patch lets it stay put over a few degrees.
- Hands-off balancing with trim +3.5° averaged **+5.66°** (range +5.2..+6.1) while holding position, which is the real balance point. Trim is now **+5.6°**, the default in balance.ino.
- Lesson: after any change on the mast, balance hands-off and average the pitch while it holds still. That's quicker and more accurate than the locked-wheel test.

## Camera follow (Nov 14, morning)
- Video: the robot's iPhone as a **Continuity Camera** ("John's iPhone Camera"): no hotspot or network needed, but the phone must be on John's Apple ID, nearby, with Wi-Fi and Bluetooth on. Programs need an Info.plist with `NSCameraUseContinuityCameraDeviceType` to see it (built into `follow/`). Frames are 1920x1080, upright; the rear camera faces the battery side (robot front).
- `balance/follow/follow` (Swift, `./build.sh`): Apple Vision upper-body person detection, or `--yellow` for a bright yellow object (hue 45–70°, saturation ≥ 0.5; 0 false pixels in this room). Posts speed and turn to drive.py's `/auto`; drive.py passes them on only while **Follow is ON (F)**; held keys override; X stops. Flags: `--dry`, `--turn-only`, `--distance`, `--camera-back`, `--rotate`.
- Person following is weak right now: the camera is ~40 cm off the floor and aims low, so a standing person shows only from the waist down. Tilt the phone up 15–20° (hinge screw; the hinge's designed direction tilts the rear camera DOWN, so tilt the other way or flip the phone and use `--camera-back`).
- **Yellow follow, turn-only: works.** The log shows the object pulled from offset -0.43 to ~0 in ~3 s. Yellow patch size: ~0.07 far, 0.12–0.20 at arm's length, up to 0.38 close.
- **Yellow full follow works** (~10 m in one run): default `--distance 0.35` (stops closer; 0.28 was still too far), `--speed 0.4`; speed scales with how many times too far the target is.
- **Target lock** (Nov 14): yellow pixels are split into blobs; it locks onto one and only accepts a blob near the last position (within 0.22 of the frame) with a similar size (0.45–2.2×). Other yellow things are ignored (seen ignoring up to 11 at once). If the target is hidden it holds still, and re-acquires the biggest blob after 0.7 s. Tiny blobs (size < 0.045) are never acquired, and a locked target smaller than 0.025 is dropped: before this it once chased a distant yellow speck at full speed.
- **"No iPhone camera found" (Nov 14, noon):** a `follow` left running for hours had stopped getting frames, but it still seemed to hold the iPhone camera, so a new run couldn't find it. Stopping the old one fixed it. `follow` now keeps looking for the camera for up to 20 s. If that fails, open FaceTime, pick the iPhone under Video, quit FaceTime, and run it again.
- **Black frames mid-demo (Nov 14, noon):** `follow` found the iPhone camera, but every frame was solid black, in FaceTime too.
  - Ruled out: the phone's own Camera app worked, Continuity Camera was on, and restarting the phone didn't help.
  - Cause: the Mac's peer-to-peer Wi-Fi link (`awdl0`), which carries the Continuity Camera video, was down. `ifconfig awdl0` showed no `UP` flag.
  - Fix: `sudo ifconfig awdl0 up` brought the video back immediately.
  - Meanwhile the robot just held position, because the 300 ms watchdog did its job.

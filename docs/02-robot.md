# Robot

The robot is assembled and balancing (Sat Nov 14). Measured values and the firmware's conventions are in `../firmware/README.md` and `../firmware/bringup/HARDWARE-NOTES.md`; where they disagree with this file, they win. This file covers what the parts mean for the product, the technical facts software needs, and what's still missing.

![Miguel.exe render](assets/hero.png)

## Design

| Part | What it means for the product |
| --- | --- |
| 2 NEMA 17 steppers, 85 mm rubber wheels | Smooth indoor floors; precise slow moves; fine for a short demo area, not carpet or ramps |
| ESP32-S3 + MPU-6050 | Balancing runs on the robot itself |
| 3S 2200 mAh LiPo x2 (about 24 Wh each) | Swap packs between runs; a 12 V desk supply tethers it while testing |
| 240 mm printed mast + phone cradle (70-81 mm wide phones) | 495 mm from floor to phone top, 2.21 kg, footprint 188 x 130 mm: about knee-to-thigh height, phone face on top, tilts back 0-20° |
| iPhone 18 Pro or similar | Camera, screen, mic, speaker; LiDAR |
| 3 HTD-45H bus servos + BusLinker | In the CAD, a two-link arm on the mast's right side that ends in a ball: no gripper. It can wave, point, push or tap. Any other end attachment can be added later |
| Printed kickstand | It rests leaning 11.3-11.7° toward the battery side (measured, phone on) when idle or while the arm works; also the fallback "kickstand mode" |
| No extra sensors | Everything it perceives comes from the phone |

Product consequence: low jobs (carrying small things in a tray, interacting with seated people or kids, looking at the floor) fit the body. Grabbing anything needs an end attachment that isn't built yet.

## Technical facts

- **Mass:** 2.21 kg (CAD). Measured: center of mass ~40 mm above the axle without the phone, ~80-90 mm with it; with the phone it balances at -1.25° (leaning slightly away from the battery side).
- **Front = the battery side** (also the kickstand side), as the firmware sees it. The CAD was drawn the other way round, so left and right below are the firmware's.
- **Drive:** steppers at 1/16 microstepping on TMC2209 drivers, step/dir only.
- **ESP32-S3 pins:**

| Pin | Connects to |
| --- | --- |
| GPIO 8 / 9 | MPU-6050 SDA / SCL (I2C) |
| GPIO 4 / 5 | Right wheel's driver STEP / DIR (forward = DIR high) |
| GPIO 6 / 7 | Left wheel's driver STEP / DIR (forward = DIR low) |
| GPIO 15 | EN on both drivers (LOW = motors on) |
| GPIO 17 / 18 | Reserved for the BusLinker (arm) |

- **Power:** battery through a 15 A fuse; a buck converter gives the ESP32 5 V. Unplugging the XT60 is the off switch.
- **Spares:** a second ESP32, two extra drivers, a third stepper and two extra IMUs. Enough for a desk test rig without taking parts from the robot.

## Materials and setup still needed (confirm with John)

- [ ] M3 screws, heat-set inserts and battery straps (still to buy as of Nov 10)
- [ ] USB cable for the ESP32-S3; USB lead for the BusLinker (it has a USB port)
- [ ] A second camera for vision work while the spare iPhone is on the robot: a teammate's phone or an MLH Logitech webcam
- [ ] 12 V for the arm on the desk while the bench supply tethers the robot
- [ ] An LLM API key
- [ ] A phone hotspot for the robot link

## Images

- [Exploded view](assets/exploded.png)
- [Spec sheet](assets/spec-sheet.png)
- [Drawing](assets/drawing.png)

CAD files, STLs, the 3D viewer and the assembly guide are in `reference/john-pack/` (raw archive).

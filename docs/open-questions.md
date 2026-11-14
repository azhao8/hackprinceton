# Open questions

Everything not yet decided, with a recommendation. When one is settled, add a file to `decisions/` and remove it here.

## Product

| # | Question | Recommendation |
| --- | --- | --- |
| P-1 | Which use case? | Pick around Sat noon. Without a gripper, the strongest fits are fetch-and-carry with a tray, find-my-things, the robot pet and telepresence (see `04-product.md`) |
| P-2 | Which main track and special tracks? | Pick around Sat noon. Leading idea: Healthcare as the main track; Best Hardware, Best Physical AI and Amazon Practical AI as extras (see `05-event.md`) |

## Technical

| # | Question | Recommendation |
| --- | --- | --- |
| T-4 | How the phone's camera reaches the server (was B4 and T-4) | Go straight to the phone page over HTTPS: agents make the certificate or tunnel cheap, and it keeps the face on screen. Vision develops on a desk camera behind a frame-source interface meanwhile, so this can be settled later |
| T-5 | Firmware build: PlatformIO (0040) or arduino-cli? The working firmware uses the ESP32 core 3.x timer API; PlatformIO's official platform ships core 2.x | Keep arduino-cli for the weekend (it builds and uploads from the command line); see `firmware/README.md` |
| T-6 | Contract differences between the firmware and `03-software.md`: no kickstand mode, 20 Hz telemetry, no battery reading, degrees | Decide each one; the mock follows the winner. List in `firmware/README.md` |

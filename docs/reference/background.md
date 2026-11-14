# Background

Condensed notes from other sources. These are inputs, not decisions; settled items are in `../decisions/`.

## Teammate's computer-vision plan

From a teammate's agent notes; inspiration, not a spec.

- **Pipeline:** the iPhone streams video to a laptop running OpenCV + MediaPipe; the laptop sends drive commands to the ESP32 over Wi-Fi.
- **Messages:** the same JSON contract as in `../03-software.md`.
- **Safety:** the robot balances on its own and stops driving if no command arrives for 300 ms.
- **Network:** a shared phone or laptop hotspot, not venue Wi-Fi.
- **Phases:** setup; iPhone video into OpenCV (network webcam app vs Continuity Camera vs a Safari WebSocket page that can also show the face); person tracking at 320-640 px; follow-me with dead zone, limits and smoothing; gestures; one-page notes.

## Style reference: Bracket Bot

[Bracket Bot](https://bracketbot.com/?panels=). The site now shows only a hiring page, so it gave no specs. From memory, unverified: a startup that built a tall, open-source two-wheeled balancing robot on hoverboard hub motors with a single-board computer. A look-and-feel reference only. Credit it as inspiration on Devpost; don't reuse its code or CAD.

## Hardware brief (John's, condensed)

- **Robot:** 495 mm to the phone top, 2.21 kg; center of mass 93 mm above the axle; balances at about a 1.3° lean. Servo arm on the side of the mast.
- **Pitch in the brief:** a low-cost helper that follows you, carries things and responds to gestures (palm = stop, beckon = come, thumbs up = deliver).
- **Fallback:** kickstand mode if balancing isn't reliable by T+18; same commands.
- **Wiring and contract:** see `../02-robot.md` and `../03-software.md`.
- **Way of working in the brief:** one shared repo; contract and a mock robot in the first hour; folder ownership per role; small branches; no API keys in commits; credit open-source libraries.

## Earlier team planning (John's pack, Nov 9-13, condensed)

- **Idea scoring (Nov 9):** 1st robot + follow-me-and-fetch care module (Healthcare, 25/30); 2nd Photon iMessage agent for international-student paperwork (24); 3rd CV physical-therapy coach (23); then robot as telepresence "passport" (22), Pi citizen-science kit (22), student money copilot (21), bare modular platform (20). Takeaway: a bare platform scores low on utility and charity; platform + one useful module scores high.
- **Original concept:** a modular robot. Modules bolt on and appear on the dashboard when plugged in, without touching the balancing code. The planned demo moment was a live module swap.
- **Fallback demo tiers:** see `../01-build-plan.md`.
- **Draft demo and past-winner patterns:** see `../05-event.md`.

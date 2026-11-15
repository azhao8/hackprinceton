# 0060: The check-in is a two-way WebRTC video call, ended from either side

- Date: 2026-11-15
- Status: accepted
- Source: T-23; issue #118
- Agreed by: Alex (asked for it Sun morning)

Once she says yes, the family member and Mom see and hear each other: plain WebRTC, peer to peer
between the family app and the robot's phone page, with the server relaying only the setup (`rtc` on
`/family/ws`, and the phone's mic socket). The phone page offers, using the camera and mic it already
has (vision and hearing keep their streams). During the call Miguel neither hears nor talks, the
caller's video replaces his face in the top half of his screen, and either side's End button ends it
for both. No STUN or TURN on the demo hotspot. Details: `contract/web/family.md`.

## Alternatives

| Option | Critique |
| --- | --- |
| **WebRTC, server relays the setup** (standard: yes) | Low lag, both ways, nothing through the server; needs https for the app's camera and TURN beyond one network |
| JPEG frames through the server plus recorded `talk` clips (the old plan for Sunday) | One way video, push-to-talk voice, ~5 fps; no https needed. Kept as the picture until the call's video plays |
| A hosted video service (Daily, LiveKit, Twilio) | Handles TURN and many devices, but an account, a key and the internet for a call across the room |

## Why this one

Alex asked for a real two-way call (issue #118). Browsers ship WebRTC; on one Wi-Fi it needs no
extra servers, and the server's existing sockets carry the setup.

## Reversibility

Easy: the call is `firmware/balance/phone/call.js`, `web/lib/family/call.ts` and the relay in
`server/app/family.py`; the JPEG relay is still there. Reaching a family member on cellular needs a
TURN server (T-25).

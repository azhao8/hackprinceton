# 0054: Start balancing from the control page, on this laptop only

- Date: 2026-11-14
- Status: accepted
- Source: Alex, Sat afternoon (all controls on the control page, 0053); issue #42
- Agreed by: Alex

The control page can send `g` (start balancing) with a "someone is holding it upright" confirm. The server accepts it only from this laptop (localhost), only as an explicit `arm` message, and stops follow, skills and the joystick first. Skills, the agent and the follow loop can never send it; the link's `send_letter` still refuses `g`.

## Alternatives

| Option | Critique |
| --- | --- |
| **Control page button, localhost only, with a confirm** | Everything in one place (0053); the confirm and the firmware's 6° rule keep a person in the loop |
| A terminal command (`sendto(b'g')`) | Works, but it's a second tool to find during a demo |
| Never from the server | Safest on paper, but the phone is mounted and USB is unplugged, so nothing else can start it |

## Reversibility

Easy: one message type on the server and one button.

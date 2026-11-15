# 0058: The family app connects over Nick's /family/ws, through a thin family layer

- Date: 2026-11-14
- Status: accepted
- Source: Alex's redesign, Sat night (#57, #60, #61); issue #68
- Agreed by: Alex

The family app talks to the server over one WebSocket, `/family/ws`, with the messages in `contract/web/family.md` (Nick, #60), cut to what the demo needs. On the server, `app/family.py` translates: app requests become agent messages (Claude still picks the tools), and the app's state comes from what the server already knows (the link, bring's stages, agent events, vision). Fixed code, not Claude, for the note read word for word and the check-in consent lock. Sign-in: one shared `FAMILY_TOKEN` in the first message; without it only the laptop can connect.

## Alternatives

| Option | Critique |
| --- | --- |
| **Nick's WebSocket + a thin layer** | Already written down with tested samples; pushes state; no proxy needed for the token |
| Grant's `/family/*` HTTP routes, polled | Smaller, but needs a server-side proxy to keep the token off the page |
| The app reads `/agent/*` directly | No server code, but the agent's internals leak into the app and break when prompts change |

## Why this one

It reuses Nick's tested contract, keeps the app a client that only asks, and keeps one brain. Cut for Sunday: WebRTC (JPEG relay instead), push notifications, routines, invites, voice clips to her.

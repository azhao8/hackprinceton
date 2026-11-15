# Texting Miguel on iMessage (Photon), setup for people

Family members text Miguel like a person: "how's mom?", "bring her water", and he texts back:
answers, delivery updates with a photo, and fall alerts. It runs on Photon 2.0's Beta (the
hackathon's Photon track, issue #67). Code: `server/bridge/`.

Do these in order. Sections 1 and 2 take about 10 minutes, and only a person can do them.

## 1. Photon account and keys (Alex, once)

1. Open https://app.beta.photon.codes and sign up. Create an organization and a project (any
   name, for example "Miguel"). The Free plan is enough.
2. **Project ID:** Project → Settings, copy the **Project ID** (starts with `pho_prj_`).
3. **API key:** Project → API keys → Create key → **Custom**. Expiry: 7 days. Tick
   `project:read` and `project:write`. Copy the key (`pho_sk_…`); it's shown only once.
4. Put both in the main checkout's `server/.env` (git-ignored; never paste them in chat or a PR):

   ```
   PHOTON_PROJECT_ID=pho_prj_...
   PHOTON_API_KEY=pho_sk_...
   ```

## 2. Give each family phone a Miguel number (once per phone)

Photon's free shared iMessage line only talks to phones added here, and only after that phone
texts first.

1. Project → Platforms → **iMessage** → **Add**: the phone's number in `+1XXXXXXXXXX` form (or the
   person's iMessage email).
2. **Assign a number from the shared pool.** Copy the number it gives: that's Miguel's number
   for this phone. Save it in that phone's contacts as **Miguel**. Different phones may get
   different numbers; that's fine.
3. Repeat for the second demo phone (David and Sarah in the demo).

## 3. Tell Miguel whose phone is whose (the family app or the control page)

Miguel only answers phones that are linked to a family member. Anyone else gets a polite no and
nothing reaches the robot.

- **Family app:** Manage → "Text Miguel" → type your number → **Link**. It links the phone to
  whoever is signed in (Sarah or David in the demo).
- **Control page** (`http://localhost:8080/control` on the laptop): **Family phones** → pick the
  person, type the number → **Link**. Remove unlinks it. **Test fall alert** is in the same section.

Both need the server with this change (merge the PR, then restart the server once). Until then,
`server/.env` can carry the same list for the bridge only:
`PHOTON_FAMILY=+1XXXXXXXXXX:m2,+1XXXXXXXXXX:m1` (m1 Sarah, m2 David).

## 4. Start the bridge

On the laptop, with the Miguel server already running (live robot or mock):

```bash
cd ~/workspace/hackprinceton/server && uv run --env-file .env python -m bridge
```

The log should say `photon: connected`, `miguel: connected as Sarah` (and David, Lin) and the
linked phones. It only reads from
the server over `localhost`; starting or stopping it never touches the robot or the server.

## 5. Text first, from every demo phone

From each phone, text Miguel's number **"hi"**. He answers. Photon won't let Miguel send the
first message, so a phone that has never texted him gets no alerts. Do it again right before
judging.

## 6. Check it before the demo (2 minutes)

| Text | Expect |
| --- | --- |
| "how's mom?" | Typing dots, then 1–3 lines about her day |
| `bring her water, say "love you, Mom"` | "On it" → "On the way" → "Delivered 6:12" + photo; she hears "love you, Mom" |
| Control page → **Test fall alert** | Both phones: "Margaret may have fallen…" + photo |
| "got it" from one phone | The other phone: "Sarah is on it" |
| A text from an unlinked phone | "I only talk with Margaret's family." |

## If something's off

| Symptom | Fix |
| --- | --- |
| `photon: 401` in the log | Wrong or expired key; make a new one (section 1.3) |
| Texts arrive in the log but no reply on the phone | That phone hasn't texted since its number was assigned: text "hi" again. Also check Project → Activities in Photon's dashboard |
| "not linked" in the log | Link the phone (section 3) or add it to `PHOTON_FAMILY` |
| `miguel: can't connect` | The server isn't running on port 8080, or `FAMILY_TOKEN` differs: run the bridge with the same `.env` as the server |
| Miguel says his brain is off | The server has no `ANTHROPIC_API_KEY` (or the local brain is off) |
| Photon is down or the venue internet is out | Show the same flow in the family app (it's the same server), and the screen recording |

## Not done tonight

Phone calls with Miguel (Photon's voice channel) need a paid SMS number, SIP setup with ElevenLabs
and a public tunnel. See issue #67.

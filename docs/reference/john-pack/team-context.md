# HackPrinceton F26 robot: full team context

_Compiled Fri Nov 13, 2026 from John's project folder and our chats. It includes everything that's still useful, but not every file word for word: superseded drafts, raw code and logs are left out or moved into the zip (see 'What's in the zip' and 'Left out on purpose' at the end). **Part 1** is the current state, written fresh. When an older doc disagrees with it, Part 1 wins. **Part 2** has the current source documents in full, each tagged with its date and how current it is. Personal items (John's classes, flight booking codes, email addresses) were removed._

**How to use this:** split it into a `docs/` folder in the team repo (layout in section 1.12). Then point every teammate's Claude at `docs/` in the repo's `CLAUDE.md`.

---

# Part 1. Current state (source of truth, Nov 13)

## 1.1 Event

| | |
|---|---|
| Event | HackPrinceton Fall 2026, theme "Passport to Innovation". In person at the Julis Romo Rabinowitz Building (JRR), Princeton University. MLH member event, so the MLH Code of Conduct applies. |
| Dates | Fri Nov 13 – Sun Nov 15, 2026 (Eastern time) |
| Hacking | **Inferred** from the last two events: starts about **Fri 8:00 PM ET** and ends with a **hard Devpost deadline around Sun 8:00 AM ET**. Judging about Sun 9:30 AM–2:00 PM, as table demos of about 2 minutes. **Confirm all times in the hacker packet** (portal sign-in needed). |
| Tracks | Six main tracks; you enter **one**: Education, Entertainment, Sustainability, Healthcare, Business + Enterprise, Science + Discovery. Sponsor prizes stack on top. |
| Judging (past rubric) | Creativity, Utility, Charity (societal need), Avidity (enthusiasm and polish) |
| Hardware on site | MLH lists a Digi-Key Hardware Lab. No soldering iron confirmed: the team is setting heat-set inserts with a lighter and a screw. |

## 1.2 Team and roles

| Person | Role | Owns |
|---|---|---|
| John Huang | **The entire hardware stack**: mechanical build, wiring, power, the physical robot | `/hardware` |
| Grant Ji Kim | Software (pick a role below) | |
| Jialang Zhao | Software (pick a role below) | |
| 4th teammate | Unknown / TBD | |

The software roles below are a proposal. Firmware could also stay with John; that's not decided.

1. **Firmware / controls** (`/firmware`, ESP32): IMU filter, step generation, balance loop, UDP link, safety, kickstand mode.
2. **Robot software + integrator** (`/robot`, laptop Python): a robot service with one arbitrated `drive()`, the dashboard, live gain tuning. Owns `main`, merges, the run script and the demo path.
3. **Vision / AI + pitch** (`/vision`, laptop Python): phone → laptop video, MediaPipe follow-me, gestures, the Devpost write-up, the demo script and a backup video.

## 1.3 The project

- **One-liner:** a low-cost, half-size self-balancing helper robot that follows you, carries things, and responds to gestures. An iPhone on the mast is its camera.
- **Recommended track:** Healthcare, as "a helper robot for people with limited mobility". Not formally locked; alternatives are Education and Science + Discovery.
- **Cross-track and sponsor targets:** Best Hardware Hack and Best Overall. Sponsor prizes from past events to check against the F26 list: Best Hardware + AI, MLH Best Use of Gemini, and Photon (a "text the robot" iMessage module). Details are in `research.md` and `robot-plan.md` §5.
- **Behaviors:** follow-me (keep a set distance); gestures (open palm = stop, beckon = come here, thumbs up = deliver); carry a small payload. Stretch goals: modules that appear on the dashboard when plugged in (the original "modular robot" idea), voice or natural-language commands via Gemini, and the HTD-45H arm.
- **Fallback demo tiers:**
  1. Balancing and following.
  2. **Kickstand mode:** it rests on the printed kickstand and drives with the same commands.
  3. **"Smart mast" on the table:** the phone tracks the judge, with the dashboard and recorded clips.

## 1.4 Hardware as built (supersedes the older full-size and Pi designs)

- **Frame:** 22 printed PETG parts (Bambu P2S, white plus baby blue), all support-free.
  - Base plate 116 × 130 × 6 mm.
  - One-piece printed mast, 240 mm tall. Its top is about 316 mm above the floor datum.
  - An electronics shelf holding the board carriers.
  - Printed kickstand, battery cradle, IMU pedestal, buck holder and Wago frame.
  - A tilting phone cradle (0–20° back) for phones 70–81 mm wide, using stacking shims (1.5 mm and 3 mm).
  - An arm mount on the mast's right rail.
  - A **full spare set** of the fall-prone parts (spares plate 6), plus a spare mast and base plate.
- **Drive:** 2 × NEMA 17 steppers (STEPPERONLINE 84 oz·in, 48 mm, 200 steps/rev) on 2 × BIGTREETECH TMC2209 V1.3 drivers. They're in expansion boards set to **1/16 microstepping** (MS1 and MS2 on), step/dir only. Wheels are 85 mm solid rubber on 5 mm clamping hubs, with a 3 mm gap to the motor mounts.
- **Brain and sensing:** ESP32-S3 DevKitC-1 N16R8 on a screw-terminal board, and an MPU-6050 (GY-521) on a stiff printed pedestal.
- **Power:** OVONIC 3S 2200 mAh 35C LiPo, XT60. There are 2 packs, about 24 Wh each.
  - Path: battery → 15 A inline fuse → Wago +12 V and GND distribution → both driver boards' VM, plus an LM2596 buck set to **5.0 V** → ESP32 5V.
  - 5 A fuses on the branches.
  - **There's no switch: unplugging the XT60 turns it off.** A 12 V 5 A desk supply is the tether for tuning.
- **Arm (stretch):** HTD-45H bus servos on a BusLinker board, with serial on GPIO 17/18 if the ESP32 drives it. Whether the ESP32 or the laptop drives the arm isn't decided yet.
- **Mass properties (CAD):**
  - Total 2207 g, of which 325 g is printed parts.
  - Center of mass 125 mm above the floor, which is **93.4 mm above the axle**.
  - It balances at about a **1.3° lean**. The left/right load split is 47/53.
  - Gravity torque is 1.79 N·m per rad. Torque needed per motor: 0.078 N·m at 5° of tilt, 0.156 at 10° and 0.307 at 20°.
  - Parked on the kickstand it leans back 13.1°. It can tip forward 60° before anything hits the floor.
- **Fasteners:** 34 × M3×6 and 21 × M3×8 socket head screws, 47 M3 heat-set inserts in Ø4.0 × 5.5 mm holes, and one 2.5 mm hex key.

**ESP32-S3 pins (fixed):**

| Pin | Connects to |
|---|---|
| GPIO 4 / 5 | Left driver STEP / DIR |
| GPIO 6 / 7 | Right driver STEP / DIR |
| GPIO 15 | EN on both drivers (LOW = motors on) |
| GPIO 8 / 9 | MPU-6050 SDA / SCL (I2C, 3V3 power) |
| GPIO 17 / 18 | (stretch) BusLinker TX / RX |
| Avoid | GPIO 0, 3, 45, 46 (boot), 19/20 (USB), 35–37 (PSRAM on the N16R8) |

## 1.5 System contract (v0; change it only if everyone agrees)

- The phone streams video to the **laptop**. The laptop runs OpenCV + MediaPipe, the dashboard, and the logic that decides where to go. **There's no Raspberry Pi anymore.**
- **Laptop → ESP32**, newline-delimited JSON over UDP at 20–50 Hz:
  `{"t":"cmd","v":0.3,"w":0.0,"mode":"drive"}`
  - `v` = forward speed in m/s
  - `w` = turn rate in rad/s
  - `mode` = `idle | balance | drive | kickstand`
- **ESP32 → laptop** at about 50 Hz:
  `{"t":"tel","pitch":1.2,"rate":-0.4,"vl":0.28,"vr":0.31,"batt":11.6,"state":"balance","fault":null}`
- **Safety lives on the ESP32:**
  - If no command arrives for 300 ms, it holds position.
  - Past a set tilt angle, it cuts the motors (EN high).
  - Balancing never depends on Wi-Fi.
- **Arbitration on the laptop:** e-stop > manual joystick > autonomous behaviors. Behaviors and modules can only *request* motion.
- **Network:** a laptop or phone hotspot, not the venue Wi-Fi.
- **Hour-1 deliverables:** this contract plus sample messages in `/shared/contracts`, and a mock robot script that accepts commands and sends fake telemetry, so all software can start before the robot works.

## 1.6 Plan and checkpoints (T = hacking start, about Fri 8 PM ET)

| Time | Checkpoint |
|---|---|
| T+1 | Repo, contract and mock robot are in |
| T+10 | Balances for 10 s while tethered |
| **T+18** (about Sat 2 PM) | **Go/no-go on balancing.** If not reliable, demo in kickstand mode and keep tuning until about T+28 |
| T+26–33 | Demo-path rehearsals (×5), Devpost draft, backup video |
| **T+33** | **Feature freeze**: bug fixes only |
| T+35 | Submit, with a 1-hour buffer before the hard deadline |

Bring-up order for the robot: motors spin open-loop → the IMU reads sensible pitch → it balances 10 s while tethered → it holds position → it drives on commands.

## 1.7 Rules (summary; details in `research.md` §"Rules: AI tools and pre-written code")

- AI coding tools are allowed **if disclosed** on Devpost. Credit open-source libraries, for example FastAccelStepper.
- Past events required most code (85 %) to be written during the event. Write all project code after hacking starts.
- Per John's Nov 9 note, the organizers OK'd pre-building hardware and testing software at home. Save the screenshot, and disclose the pre-event hardware work on Devpost.
- Inspiration: open-source balancing robots such as BracketBot. Don't reuse their code or CAD.

## 1.8 Status (Nov 13)

- **Done:**
  - All parts bought (Amazon, picked up Nov 10).
  - CAD v3 finished, with zero interference and every part support-free.
  - All printed parts and a spare set printed.
  - Assembly guide with 21 illustrated steps (`assembly-guide.html` / `cad/out/guide/`).
  - Parts list.
  - Teammate prompts: CV practice and team context.
- **In progress:** John is setting the heat-set inserts (with a lighter and a screw) and assembling.
- **Not done / unknown:**
  - The team repo may not exist yet.
  - Firmware and software code (written at the event).
  - Whether the CV practice happened, and what it found.
  - M3 screws, inserts and battery straps were still to buy as of Nov 10.

## 1.9 Stale or superseded info in Part 2 (read Part 2 with this list in mind)

| Where | Says | Now |
|---|---|---|
| `robot-plan.md` "Bottom line", §1–2, §3 roles table, `timeline.md`, `drafts/discord-organizer-question.md` | Full-size 70 cm robot, Raspberry Pi 5, geared DC motors, Cytron driver, 2020 extrusion mast | Half-size printed robot, ESP32 + laptop, NEMA 17 steppers (see 1.4). The "Nov 9 update" at the top of `robot-plan.md` is the closest match. |
| `robot-plan.md`, discord draft | LiPo "about 55 Wh" | 2 × 24 Wh 3S packs |
| `robot-plan.md` Nov 9 update | 10 A fuse, a rocker switch, a 400 mm 2020 mast, 35–40 cm tall, about 1.5 kg | 15 A fuse, no switch (pull the XT60), 240 mm printed mast, about 2.2 kg |
| `robot-plan.md`, `ideas.md` | Caster for "kickstand mode", hoverboard base | Printed kickstand; the hoverboard is dropped |
| `shopping-list-full.md` | Long option lists | Earlier drafts, never bought. `shopping-list.md` is what was bought. |
| `research.md` schedule | Hacking and judging times | Mostly inferred from past events. Confirm in the hacker packet. |
| `build-guide.md` §9, `timeline.md` | "Before the event" tasks | Historical: hacking has started |
| `cad/out/guide/assembly-guide.md` step 21 | "Remaining parts: shim L, shim R" | A generator artifact. The shims are covered in steps 18–19. |
| `cad/params.py` `MEASURE` comments | "Measure this" | Nothing was measured; listing sizes are used, with slack built in |
| Packing and travel docs | Pre-trip tasks | Historical. Return-trip notes still apply. |

## 1.10 Open questions

1. Hacker packet: exact hacking, submission and judging times; final sponsor prize list; LiPo and charging rules at the venue; sleeping arrangements.
2. Who owns firmware: John or a software teammate?
3. Does the ESP32 or the laptop drive the arm's BusLinker? Is the arm in the demo at all?
4. Who creates the team repo, and its URL? Who is the integrator?
5. Who is the 4th teammate, and what are their skills?
6. Track lock: Healthcare (recommended), or something else?
7. Which phone → laptop streaming method won in the CV practice (Continuity Camera, an IP webcam app, or a Safari WebSocket page)? Measured delay?

## 1.11 Where things live (John's machine; copy into the repo as needed)

| Thing | Path |
|---|---|
| CAD source (build123d; `params.py` holds every dimension) | `cad/`, `cad/parts/*.py` |
| STEP assembly, STLs, renders, interactive viewer | `cad/out/assembly.step`, `cad/out/stl/`, `cad/out/renders/`, `cad/out/viewer.html` |
| Assembly guide with images | `assembly-guide.html` (single offline file), `cad/out/guide/` |
| Spec sheet for Devpost | `cad/out/spec-sheet.png`, `cad/out/drawing.png` |
| Print plates (3MF) | `cad/out/print/plates/` |
| Team repo template | `team-setup/template-repo/` |

## 1.12 Suggested `docs/` layout for the repo

```
docs/
  00-current-state.md     ← Part 1 of this file (keep it updated; it wins over everything else)
  01-event-and-rules.md   ← research.md
  02-project-and-pitch.md ← ideas.md + robot-plan.md §5 (tracks, prizes, demo script)
  03-hardware.md          ← build-guide.md + parts-list.md + cad/design-review.md
  04-assembly-guide.md    ← cad/out/guide/assembly-guide.md (+ images)
  05-contracts.md         ← section 1.5 (mirror it in /shared/contracts)
  06-plan-and-timeline.md ← robot-plan.md §3–4 + section 1.6
  07-team-workflow.md     ← team-setup/README.md, first-hour-plan.md, kickoff-prompts.md
  archive/                ← superseded docs (shopping-list-full.md, the old full-size plan, travel)
CLAUDE.md                 ← from team-setup/template-repo/CLAUDE.md, plus "read docs/00-current-state.md first"
TASKS.md, MESSAGES.md     ← from team-setup/template-repo/
```

## 1.13 Decisions and details that were only in chat (Nov 9–13)

**Design approach**
- **Nothing was measured** (John's call, Nov 10). Every part uses the listing size, with slack built in:
  - **Phone cradle:** takes phones 70–81 mm wide and 5.5–13.5 mm thick (in a case). Stack the shims per side: none for 79–81 mm, 1.5 mm for 76–78, 3 mm for 73–75, 1.5 + 3 for 70–72. The CAD's model phone is 72 × 155 × 8.5 mm, which uses both shims.
  - **Battery cradle:** takes packs up to 108 × 36 mm (a 3S 2200 is about 105 × 34).
  - **Board carriers:** if a board's holes don't line up, use double-sided foam tape.
- **Frozen interfaces:**
  - The printed shelf's carrier bays and screw holes come from `ESP_*` / `DRV_*` in `params.py`. Freeze them in `parts/shelf.py` before changing those values, or reprinted carriers won't fit the printed shelf.
  - The base's holes for the buck holder, IMU pedestal, battery cradle and Wago frame are hard-coded.
- **Phone mount base, reshaped Nov 10** after Bambu Studio flagged a "floating cantilever":
  - The pivot-pin slot's back wall leans at 45°.
  - The full-height key tongue became a 49° wedge.
  - The fin's front flank stops at y = 14.5.
  - It now passes the support check cleanly and still clears the 0–20° tilt.
- **Printability check** (`parts/_qa.py`): faces steeper than 45° fail. A flat ceiling passes if its short side is within the bridge limit. The check doesn't detect cantilevers, which is why Bambu caught the phone-base issue it missed.

**Printing (Bambu P2S, PETG Matte, white plus baby blue)**
- Each plate uses one setting. Per-object overrides live in Process → Objects (brim type, infill density).
- What was printed:

  | Plate | Contents | Settings | Time | Filament |
  |---|---|---|---|---|
  | 1 | Coupons | Skipped, so the insert holes stay Ø4.0 mm | | |
  | 2 | Base, mast, shelf (white) | 4 walls, 25 % gyroid, brim on the mast | 8.8 h | 262 g |
  | 3 | Motor mounts, arm mount and clamp, kickstand (blue) | 4 walls, 40 % | 2.6 h | |
  | 5 | Carriers, buck holder, Wago frame, phone base, IMU pedestal and clamp, 1.5 mm shims (blue) | 4 walls, 40 %; 100 % on the IMU parts | 2 h 40 min | 68 g |
  | 4 | Cradle, battery cradle, 3 mm shims (white) | 3 walls, 20 % | 1 h 13 min | 38 g |
  | 6 | Spares, 12 parts (white) | 4 walls, 40 % (spares are capped at 40 %), brim on the mast spare | 11 h 20 min | 331 g |

- Plate 6 holds: phone base and cradle, kickstand, arm mount and clamp, motor mounts L/R, mast, base plate, IMU pedestal and clamp, buck holder.
- The IMU pedestal's first layers came out slightly rough, which is cosmetic only.
- The mast fit well when test-fitted.

**Assembly**
- There's no soldering iron, so the heat-set inserts go in with a lighter and an M3 screw:
  1. Thread the insert 2–3 turns onto the screw.
  2. Heat it 10–15 s, keeping the flame off the plastic.
  3. Press it in square until flush, and hold it about 10 s while it cools.
  4. Practice on a spare part first.
- **Insert size:** M3, 4–5 mm long, 4.5–5.0 mm across the knurl. For example M3×4×5 or M3×5×4.5. The standard M3×5.7×4.6 also works if pressed flush. Avoid anything over 6 mm long or 5 mm across. Buy 50 or more.
- Screwing straight into the 4.0 mm holes won't hold. Don't use oversized self-tappers on the motor mounts.

_[Removed before publishing: travel or private email details.]_

**Software practice and prompts**
- Pre-event software practice was treated as personal project work. `team-setup/cv-practice-prompt.md` covers:
  1. Setup.
  2. iPhone → OpenCV: compare a webcam app with Continuity Camera.
  3. MediaPipe person tracking at 320–640 px.
  4. Follow-me, sending UDP to a mock robot at 20 Hz.
  5. Gestures.
  6. One page of notes.
- `team-setup/team-context-prompt.md` is the short version of this file for teammates' Claude.

**Team coordination model** (from John's earlier "Multi-agent collaboration architecture" chat)
- Don't build a complex multi-agent system. Use one repo as the shared brain:
  - `CLAUDE.md` holds roles, directory ownership and contracts.
  - Write contracts first, in `/shared/contracts` in hour 1, then build against mocks.
  - One integrator owns `main`, CI and the demo path.
  - Coordinate through committed `TASKS.md` and `MESSAGES.md`, which every Claude pulls and reads before working.
- Upgrade to a small MCP "team bus" (`team-setup/optional-team-bus.md`) only if there's time.
- Never commit secrets: keys go in local `.env` files.


_[Removed before publishing: travel or private email details.]_

---

# Part 2. Current source documents


---

## A. Event, rules and pitch

### 📄 `research.md`

> **Last edited:** Nov 09. **Status:** Nov 9 research brief: tracks, prizes, judging, rules on AI and pre-written code. Schedule times are inferred; confirm in the hacker packet.

### HackPrinceton Fall 2026: research brief

*Compiled Mon Nov 9, 2026. Sources are at the bottom. Labels used: **[confirmed]** = published for Fall 2026; **[inferred]** = based on how past HackPrinceton events ran, not yet published for Fall 2026; **[past]** = data from Fall 2025 or Spring 2026 only.*

> **Big caveat:** The official Fall 2026 prize list, schedule, rules and Devpost page are **not public yet**. The Fall 2026 Devpost page doesn't exist (several URL guesses return 404, and Devpost search finds nothing). They are probably in the **hacker packet**, which is behind John's sign-in to the portal. Much of the detail below is inferred from Fall 2025 and Spring 2026, which used nearly the same rules text both times.

---

#### Bottom line (what matters most for choosing a project)

1. **Pick one of 6 tracks; you can only enter one.** The tracks are Education, Entertainment, Sustainability, Healthcare, Business + Enterprise, and Science + Discovery [confirmed]. In past events you could enter **one** main track plus **any number** of sponsor prizes [past]. Science + Discovery is **new** this term, and Education and Entertainment are now separate tracks. That should mean less competition per track.
2. **You win by stacking prizes. Plan for one main track plus 2–3 sponsor prizes from the start.** Nearly every past top winner took 2–3 prizes at once. Examples: MindPad (F25) won Best Overall, Amazon's prize and Gemini. Asclepius (S26) won Best Overall, d_model and Regeneron [past]. The confirmed sponsors to target are **Photon** (agents in iMessage/WhatsApp; it ran a prize at both F25 and S26), **Amazon** and **Capital One** (both ran $1K prizes at F25), **Justin Bojarski** (ran "Best Hardware + AI" at S26), plus new sponsors **LangChain, Scale AI, Arlequin, ChatOverflow, D. E. Shaw, Salesforce, CoStar (title sponsor), and Peri** [confirmed sponsors; their F26 prizes are unknown].
3. **The judging rubric rewards a clear social-good story and visible passion, not only technical depth.** Past rubric: **Creativity, Utility, Charity (societal need), and Avidity (team enthusiasm and polish)** [past; the same at F25 and S26]. Judges watch a **2-minute in-person demo**, and at least 3 general judges see each project.
4. **Plan around a ~36-hour build and a hard Sunday-morning deadline.** In past events hacking ran **Fri 8:00 PM ET to Sun 8:00 AM ET**, and the submission deadline was a **hard stop**. Judging ran **Sun 9:30 AM–2:00 PM** [past]. MLH lists the F26 event window as Fri Nov 13 4:00 PM ET to Sun Nov 15 4:00 PM ET [confirmed event window; hacking times not published].
5. **Every winner has a working, demoable artifact, and the most common pattern is AI agents plus something physical or visual.** Recent winners used computer vision and gestures (MediaPipe/OpenCV), voice (ElevenLabs), agents acting through iMessage (Photon), and hardware such as a Raspberry Pi or Jetson. Their stacks were mostly Gemini, Claude, OpenAI, Dedalus and FastAPI with React [past]. A **public GitHub repo created during the event** was mandatory [past].

---

#### Key dates & schedule

| Item | Date / time | Status | Source |
|---|---|---|---|
| Applications closed | Sep 28, 2026, 11:59 PM ET | confirmed | Email Sep 24 & Sep 28; hackprinceton.com |
| Discord + hacker packet released (portal) | Oct 26, 2026 (email 01:51 UTC Oct 27) | confirmed | Email Oct 27 |
| Event weekend | Fri Nov 13 – Sun Nov 15, 2026 | confirmed | hackprinceton.com; MLH |
| MLH event window | Fri Nov 13 4:00 PM ET (21:00 UTC) – Sun Nov 15 4:00 PM ET (21:00 UTC) | confirmed listing, but this is the overall event window, not hacking times | mlh.com event page |
| Check-in | Probably Fri afternoon, about 4 PM ET | **inferred** from MLH start time; not published | MLH |
| Opening ceremony | Unknown, probably early Fri evening | **inferred** | — |
| Hacking start | Probably ~Fri 8:00 PM ET | **inferred** (F25 and S26 both started 8 PM ET Fri) | F25/S26 Devpost rules |
| Hacking end / **submission deadline** | Probably **Sun Nov 15, 8:00 AM ET (EST)**, hard stop, Devpost only | **inferred** (F25: "Sunday, November 9 at 8:00 AM… HARD stop"; S26: "Sunday, April 19 at 8:00 AM"). Devpost's own schedule listed the close as 8:15 AM (F25) and 8:30 AM (S26), slightly after the rules deadline. | F25/S26 Devpost rules & dates pages |
| Judging / expo | Probably Sun ~9:30 AM – 2:00 PM ET | **inferred** (identical at F25 and S26) | F25/S26 Devpost |
| Closing ceremony / awards | Probably Sun afternoon, before ~4 PM ET (MLH window end) | **inferred** | MLH |
| Online winner announcement | F25: Nov 10 (day after); S26: Apr 23 | past | Devpost dates pages |

Timezone: Princeton is on **EST (UTC−5)** in mid-November.

---

#### Venue, check-in, what's provided

- **Venue:** **Julis Romo Rabinowitz Building (JRR)**, Princeton University [confirmed, hackprinceton.com]. S26 used "JRR and LAS" (the Louis A. Simpson Building next door); F25 used the Friend Center [past].
- **Format:** Entirely in person [confirmed FAQ]. It is an MLH 2027-season Official Member Event, so the **MLH Code of Conduct** applies [confirmed].
- **Scale:** The site claims 800+ hackers, 400+ schools and $15K+ in prizes [confirmed site stats; probably cumulative or marketing figures]. F25 had 596 Devpost participants and S26 had 411 [past].
- **Cost:** Free [confirmed FAQ].
- **Travel:** "Some admitted hackers may receive a travel stipend that covers part of their travel expenses" [confirmed FAQ].
- **Hardware:** MLH lists a **Digi-Key Hardware Lab** as an event sponsor [confirmed, MLH page]. MLH tags the event focus as "Software, Hardware." Details on the kit inventory and how to borrow it are unknown.
- **Food, sleeping, showers, parking, check-in ID requirements:** **Not published** on the site or MLH. These are probably in the hacker packet.
- **Speaker:** Stephen Wolfram (Wolfram Research; Mathematica, Wolfram|Alpha) [confirmed]. His session time is unknown.
- **Team formation events** will be held [confirmed FAQ].

---

#### Tracks / main prizes

**Fall 2026 tracks [confirmed, hackprinceton.com]:**

| Track | Official description |
|---|---|
| Education (EDU) | Make learning more accessible, personal, and engaging. Tools for students, educators, lifelong learners. |
| Entertainment (ENT) | New ways to play, tell stories, and connect. Games, music, media, interactive experiences. |
| Sustainability (SUS) | Build for a healthier planet. Energy, conservation, waste reduction, sustainable everyday choices. |
| Healthcare (MED) | Help people live healthier lives. Accessible care, wellbeing, tools for patients and care teams. |
| Business + Enterprise (BIZ) | Help people work better together. Tools for organizations, small businesses, and the people who run them. |
| Science + Discovery (SCI) | Turn curiosity into discovery. Research tools, scientific data, new ways to understand the world. **(New for F26)** |

**Prize amounts for F26: not published** (the site only says "$15K+ in prizes").

**Likely cross-track prizes [inferred from past events]:** Best Overall Hack, Best Rookie Hack, Best Hardware Hack, and (S26 only) Best Game.
- F25 prizes: Best Overall was sponsored by Amplitude, Anthropic and OpenAI. It had 3 winners and paid a Switch 2 per member, a $100 gift card plus an Amplitude internship with no interview, 1K Claude credits, and $10K/$5K/$1K in OpenAI credits. Track prizes were hardware: a 3D printer, a drone, a projector, a speaker plus $3K cash, a Polaroid, and an NVIDIA Jetson Orin Nano.
- S26 prizes: Best Overall won a PS5. Track prizes were an Apple Watch, a DJI drone, Meta glasses, a JBL speaker, a projector, an Instax camera, a Bambu 3D printer and an arcade cabinet.
- S26 rule: "track winners are not eligible to win Best Overall Hack." F25 did not enforce this (TerraLink won both Overall and Sustainability). Confirm the rule in the F26 packet.

---

#### Sponsor prizes

##### Confirmed for Fall 2026: MLH prize categories (8)

Source: mlh.com/events/hackprinceton-fall-2026. These are MLH's standard rotating prizes, usually small (swag or gadgets).

| Sponsor | Prize name | Requirement | Reward |
|---|---|---|---|
| xAI ("SpaceXSI") | Build Your Hackathon A-Team with SpaceXSI | Use **Cursor** as the core AI coding agent and integrate a **Grok Bot** automation. Describe both in the project description and opt in to the raffle. | Raffle: custom Cursor mechanical keyboard per team member |
| Google (via MLH) | Best Use of Gemini API | Build with the Gemini API | MLH swag kits |
| Solana | Best Use of Solana | Build on Solana | "Unruggable" hardware wallets per member |
| Tiger Data | Best Use of Tiger Data | Use Tiger Data (PostgreSQL extension for time-series and real-time data) | Stream Deck Mini |
| Vultr | Best Use of Vultr | Deploy on Vultr (free cloud credits offered) | Assorted prizes |
| MongoDB | Best Use of MongoDB Atlas | Use Atlas ($50 student credit or free tier) | M5Stack IoT Kit per member |
| GoDaddy Registry | Best Domain Name from GoDaddy Registry | Register a domain through GoDaddy Registry | Digital gift card |
| DEV | DEV Writing Challenge | Publish a write-up of the project on DEV (judged monthly) | $100 |

##### Confirmed F26 sponsors whose prizes are not yet published

Source: hackprinceton.com sponsor section, by tier.

| Tier | Sponsor | What they do / past HackPrinceton prize (if any) |
|---|---|---|
| Title | **CoStar Group** | Commercial real-estate data and analytics. No past HP prize seen. A real-estate or data track is plausible (inferred). |
| Gold | **Amazon** | F25: "Best Practical AI Innovation by Amazon," $1,000 total, 3 winners ($125/$75/$50 per person) [past] |
| Gold | **Salesforce** | No past HP prize seen |
| Gold | **Peri** (peri.so) | Unknown; the site had no description |
| Gold | **Arlequin** (arlq.ai) | "AI native platform for critical decision making and action" (from its site) |
| Silver | **D. E. Shaw** | Quant/tech firm. No past HP prize seen. |
| Silver | **Capital One** | F25: "Best Financial Hack by Capital One," $1,000, 1 winner [past] |
| Silver | **Photon** (photon.codes) | Open-source framework for bringing agents to iMessage, WhatsApp, Slack and similar apps. F25: "Exploring Hybrid Intelligence" (winner got $400 cash, $600 credits, and a fast-track to final interview). S26: "Agents in iMessage" ($400 cash + $400 credits; runner-up $100 + $100) [past] |
| Silver | **Scale AI** | No past HP prize seen |
| Silver | **LangChain** | No past HP prize seen |
| Silver | **ChatOverflow** (chatoverflow.dev) | "The network where coding agents learn from each other" (from its site) |
| Partner | **Justin Bojarski** (individual) | S26: "Best Hardware + AI Hack," $500 gift card, 4 winners [past] |
| Partner | Projects Board, Princeton COS Dept | Funding partners; prizes unlikely |

##### Past sponsor prizes not on the F26 sponsor list (for pattern only) [past]

These sponsors are **not** listed for F26: YC (guaranteed interview), X API / xAI ($15K credits each), Knot API ($850; S26 $850 across 3 prizes), Dedalus Labs ($850 + API credits), Telora (startup track; S26 offered $40K to start a startup), Regeneron (clinical trials, $2K pool), Eragon (Mac Mini for an internal AI agent), d_model (alignment research), MBZUAI K2 Think, Orchids, Sonar ("Beautifully Engineered Nonsense"), Enter Pro, Vibe Kanban, Chestnut Forty, Daylight Health, EaglePlan.

---

#### Judging criteria and format

**Criteria [past; identical wording at F25 and S26, so likely reused]:**
- **Creativity:** How unique is the concept? Is there an "ah-ha" moment?
- **Utility:** Does it work? How deep is the functionality? Would you use it often in its current state?
- **Charity:** Does it address a specific societal need, and how well? Contribution to "the nation's service and the service of humanity" (Princeton's motto).
- **Avidity:** How excited the team is about the final project, shown through the presentation, the Devpost write-up, future plans, and polish.
- Judging is holistic. Each project is seen by **at least 3 general judges**, plus extra visits for any sponsor prizes you opt into [past].

**Format [past]:**
- **In-person table judging (expo style).** Table numbers are assigned during the hackathon.
- Each team gives a **presentation of at most 2 minutes**. Judges visit "multiple times" during the Sun 9:30 AM–2 PM window.
- The pitch should state the problem and walk through how the hack works. "You may not embellish project presentations."
- Some sponsor prizes had their own rubrics. Example: Eragon at S26 scored 30% depth of action, 30% context quality and 40% workflow usefulness.

---

#### APIs, credits, hardware on offer

*Do not sign up for anything without John's OK.*

**Confirmed via MLH for F26:**
- **Gemini API:** free tier through Google AI Studio. MLH also lists an "Intro to Google AI Studio" session and a "Gemini Demo."
- **MongoDB Atlas:** $50 student credit or the free tier (no card needed).
- **Vultr:** free cloud credits ("claim your free cloud credits"), including cloud GPUs.
- **Tiger Data:** free-tier cloud Postgres/time-series.
- **Solana:** devnet is free.
- **GoDaddy Registry:** domain registration. MLH events usually give out a free domain code (claimed by logging in at MLH).
- **xAI / Cursor / Grok Bot:** the MLH page shows "Log In To Claim Code," so a promo code may be offered through MLH login.
- **Digi-Key Hardware Lab:** hardware to borrow at the event. The inventory is unknown.

**Likely but unconfirmed:** credits or API access from Photon, LangChain (LangSmith), Scale AI, Arlequin, ChatOverflow and Amazon (AWS). These are usually announced in the hacker packet, the Discord, or at the opening ceremony.

**How to claim:** usually through MLH's prize page (mlh.com/events/hackprinceton-fall-2026/prizes, which needs an MLH login) or through links in the Discord. **Not done; that is John's call.**

---

#### Team & submission rules

Rules below are **[past]** (F25/S26 Devpost rules) unless marked otherwise.

- **Team size: up to 4** [confirmed FAQ]. "Maximum Team Size of 4 for prizes. No exceptions." All members must be added to the Devpost submission.
- **Eligibility:** matriculated undergrad or grad students; no separate age minimum [confirmed FAQ]. You must have **registered and checked in** to submit.
- **Submission:** **Devpost only**, before the hard deadline. Add **Discord usernames** to the submission.
- **Repo:** a **public GitHub repo created during the event**, linked in Devpost. All code must be pushed before the deadline. A working demo with no uploaded code is disqualified.
- **Video:** **optional**, at most 2 minutes (YouTube or similar). The in-person demo is required either way.
- **Libraries and frameworks:** allowed, but they must be credited in the README and on Devpost, and your own contributions must be clearly separated. Submitting only copied code means disqualification.
- **One project per hacker. No cross-posting** to other hackathons during the event.
- **One main HP track** plus any number of sponsor tracks.
- **No overstating your contributions** in Devpost, GitHub or the pitch.
- Organizers, sponsors and mentors cannot submit.
- MLH asks for the **MLH Code of Conduct, MLH Contest Terms, and Privacy Policy** to be accepted. This usually happens at registration or check-in.

##### AI tools / pre-written code
See the full section **Rules: AI tools and pre-written code** below.

#### Rules: AI tools and pre-written code

*Researched Nov 9, 2026. Note: the HackPrinceton Fall 2026 Devpost page is not public yet (hackprinceton-fall-2026 returns 404, hackprinceton-fall-26 returns 403). The HackPrinceton rules below come from the Fall 2025 and Spring '26 Devpost pages, which were almost identical. Expect Fall 2026 to be similar, but check it once it goes up.*

##### Bottom line

- **AI coding tools (Claude Code, Copilot, Cursor, ChatGPT) are allowed**, as long as you disclose them. HackPrinceton's past rules don't mention AI. MLH's standard rules allow AI tools if teams are "honest and transparent" about them, and MLH's organizer guide says undisclosed AI use means disqualification plus a report to cheating@mlh.io. **List every AI tool in the Devpost write-up and the README.**
- **No project work before hacking starts.** Past HackPrinceton rules required the project to be "built during" the hacking window (Fri 8:00 PM ET to Sun 8:00 AM ET). They also required a **public GitHub repo "created between"** the event dates. **Don't create the team's submission repo before Fri Nov 13.**
- **Spring '26 added an 85% rule:** "At least 85% of code should be written, by you, during the event." Libraries and frameworks are allowed but must be credited in the README *and* on Devpost. It's unclear whether AI-generated code counts as "written by you". This is the #1 thing to ask the organizers.
- **Safe before Nov 13:** ideas, research, design sketches, contracts written as prose, dev-environment setup, API signups, and generic team-coordination templates kept as local notes. **Not safe:** any project-specific code, or a repo with commits made before the event.
- **Other limits:** up to 4 people per team, one project per hacker, no cross-posting to other hackathons, one HackPrinceton track (any number of sponsor tracks), and an in-person demo of 2 minutes or less on Sunday. Be ready to explain any part of the code, including the parts AI wrote.

##### What HackPrinceton says

**hackprinceton.com (Fall 2026 FAQ):**
- Teams may have up to four members, and solo hackers are allowed.
- The event is fully in person, Nov 13–15, 2026, with 36 hours of hacking.
- Participants must be matriculated undergraduate or graduate students. There's no separate age minimum.
- It follows the MLH Code of Conduct and is an MLH 2027-season member event (shown by the trust badge).
- The FAQ says **nothing about AI, pre-written code, hardware or judging**. The landing letter says students build "real software and hardware" over the weekend.

**Devpost rules, Fall 2025 and Spring '26 (essentially the same text):**
- Participants must agree to the MLH Code of Conduct, the "MLH rules", the MLH Contest Terms and the MLH Privacy Policy. Because of that, MLH's standard rules apply by reference.
- Any rule violation means "immediate disqualification of your team and project."
- **Timing:** the project must be built during the hacking window. In Spring '26 that was 8:00 PM ET Fri to 8:00 AM ET Sun, and projects outside the window are disqualified.
- **Repo:** the code must be in a **public GitHub repo** linked on Devpost, and all code must be uploaded before the deadline. The overview page also requires a repo "created between" the event dates.
- **Libraries and frameworks:** public frameworks and libraries are allowed, but submitting only copied code means disqualification. You must credit them in README.md **and** on Devpost and "clearly distinguish your contributions."
- **The 85% rule (Spring '26 only, not in Fall 2025):** at least 85% of the code must be written by you during the event.
- **Honesty:** "Overly embellishing your contributions" in Devpost, GitHub or the pitch can lead to disqualification, and so can embellishing a presentation during judging.
- **Teams:** a maximum of 4 for prizes, every member must be added to the Devpost submission, each hacker can contribute to only one project, and there's no cross-posting.
- **Tracks:** opt into one HackPrinceton track plus any number of sponsor tracks. Past events also had Best Hardware Hack, Best Rookie Hack and Best Game awards.
- **Judging:** an in-person demo of 2 minutes or less on Sunday (9:30 AM to 2 PM in past events), seen by at least 3 judges. The criteria are Creativity, Utility, Charity and Avidity. An optional demo video of up to 2 minutes was allowed.
- **AI:** neither page mentions AI, Copilot or generative tools.
- **Hardware:** there are no hardware-specific rules beyond the Best Hardware Hack prize.

##### What MLH says

**Standard Hackathon Rules** (github.com/MLH/mlh-policies, last updated Mar 2026; HackPrinceton adopts them by reference):
- "All work on a project should be done during the period of the hackathon."
- Teams can use an idea they had before the event, or an idea they worked on before, as long as they don't reuse code or other project materials. Ideas don't need to be original.
- Libraries, frameworks and open-source code are allowed. **However, building something before the event and open-sourcing it just to use at the event is not allowed.** This rules out a "generic" starter that is really your project in disguise.
- Teams stop hacking when time is up. Small bug fixes during demos are fine, but new features are not.
- The code must be public and stay public after the event.
- **AI Tools and Code Gen section:** MLH encourages the use of AI, but the best projects "ultimately be created by humans." Teams may use code completion, code generation, image generation and similar tools. Teams must be honest about the AI tools they used, list them in their submission, and answer questions about them from organizers and judges.

**MLH Organizer Guide, "Rules for Your Hackathon"** (the template MLH recommends to organizers; it shows how MLH enforces the rules):
- You may use LLMs, but you "must state how you did so in your Devpost submission."
- Credit your tools and use a detailed README to show what you made versus what was generated. The project shouldn't be "a reskin of an existing AI tool."
- If you don't credit your AI use, you'll be "disqualified and reported to cheating@mlh.io."
- No reusing code from previous projects, and remove API keys before sharing.

**MLH Contest Terms** (the version on GitHub still says "Fall 2025 – Spring 2026", so it may not have been updated for the 2027 season):
- All work must happen during the event window, and earlier work can lead to disqualification.
- You must own all content or use public-domain or properly licensed material. This covers AI-generated images, music and voices, and third-party assets.
- One clause voids applications "generated by a script, macro, bot, or any other automated means." I read this as aimed at automated or bulk entries rather than AI-assisted coding, since the standard rules explicitly allow code generation, but it's the strictest wording anywhere. That's one more reason to keep humans clearly in charge and disclose everything.

**MLH cheating-response policy and cheating-check guide:**
- An on-site MLH staffer reviews suspected cheating discreetly.
- They look at:
  - the GitHub history (one big commit at the start, or a team that "started before the event")
  - whether every member contributed
  - pushes made after the deadline
  - timestamps on any video
  - mentions of other events
  - similar past projects on Devpost profiles
- They ask team members to explain specific parts of the code.
- Making a repo private to hide evidence can mean disqualification. Cases are reported to MLH and can lead to warnings or bans.

**MLH Code of Conduct:** it covers behavior only (harassment, sexualized content in hacks or at the event, and reporting). It has nothing on AI or code reuse.

##### What Devpost says

- Devpost doesn't set a single platform-wide rule on original work. Each hackathon writes its own rules page, and for HackPrinceton those are the rules above, plus MLH's by reference.
- Devpost's sponsor-run hackathons use an "Official Rules" template. It comes in a strict "newly created during the Submission Period" version and a looser version that allows existing projects if they're "significantly updated" and the update is explained. HackPrinceton uses the strict approach.
- **How projects are checked:** Devpost's tools let organizers flag a submission as "Don't Judge" or "Maybe", message teams and export submission data. I found no Devpost feature that scans git history automatically. In practice organizers and MLH staff check by hand:
  - when the repo was created
  - the first-commit timestamp
  - the shape of the commit history
  - who committed
  - whether someone can explain the code
- Third-party tools such as ".gitcheck" and "HackFair" exist to automate these checks. *Uncertainty:* I couldn't find a Devpost help article that describes enforcement, so this part is inferred from MLH's guide and Devpost's organizer docs.

##### Safe to prepare before Nov 13 / Not safe

**Safe (ideas, research, environment):**
- Brainstormed and ranked ideas, research on tracks and sponsor APIs, and competitor or prior-art notes. MLH explicitly allows ideas you had before the event.
- Design sketches, wireframes and a demo storyline. Keep them as notes, sketches or Figma frames that aren't part of the codebase.
- API and data contracts written **as prose or bullet notes** in the local planning folder. Write the actual `/shared/contracts` files during hour 1.
- Dev-environment setup:
  - installing Node, Python and SDKs
  - Claude Code, its settings, user-level `~/.claude` config and general-purpose MCP servers
  - editor extensions
  - checking that `npm create vite`, `pip` and similar commands work offline or on campus Wi-Fi
- API account signups and free-tier credits, so you aren't stuck waiting on approval. Each person pastes keys into a local `.env` themselves.
- Generic team-coordination templates kept as **local notes**: a CLAUDE.md skeleton with roles, ownership and conventions, plus TASKS.md and MESSAGES.md formats. These are process documents, not project code.
- Practice runs on throwaway toy code that **won't go into the submission**, for example rehearsing the git or Claude Code workflow in a scratch repo you delete afterwards.
- A packing and logistics checklist.

**Gray area (allowed in principle; do it carefully and disclose it):**
- A generic starter, such as an empty `create-vite` app or a FastAPI hello-world. **Don't pre-commit it.** Regenerate it with the official CLI at kickoff, which takes about 1 minute, so it shows up as a during-event commit labelled as framework boilerplate.
- Copying the coordination templates into the repo at kickoff. Do it in one clearly labelled commit, for example "Add team coordination templates (prepared before the event; no project code)", and mention it in the README.
- Project-specific Claude prompts or skills prepared in advance. Keep them generic. A prompt that contains the project's design is still fine, since it's planning, but code it produced before the event is not.

**Not safe:**
- Any project-specific code: components, endpoints, data pipelines, model code, prompts wired into code, or mock servers for *your* idea. This holds even if a teammate or Claude writes it "just to try."
- Creating the **team submission repo** or pushing any commits to it before hacking starts. The repo-creation dates and first-commit times are the first things anyone checks.
- Publishing a "generic" open-source library of your own before the event so you can import it. MLH explicitly bans this.
- Reusing code from a past project, whether your own or a teammate's.
- Pre-generating AI assets (logos, images, audio) for the project. Generate them during the event and check their licenses.
- Pre-built hardware assemblies or pre-written firmware for the hack. Owning or bringing components is fine, but the build has to happen at the event. *(No HackPrinceton hardware rule found, so this is an inference.)*

##### Recommendations for the team

1. **Kickoff sequence (Fri, right after hacking opens):**
   - John creates a new public GitHub repo, for example `hackprinceton-f26-<name>`.
   - Commit 1: the official framework scaffold (`npm create vite@latest`, and so on).
   - Commit 2: the coordination templates (CLAUDE.md, TASKS.md, MESSAGES.md), labelled as prepared before the event.
   - Then write `/shared/contracts` together.
2. **Commit small and often, from every teammate's own GitHub account.** Each person's Claude commits under its human's identity, with no bot accounts. That gives a natural history showing all 4 contributing, which is exactly what MLH reviewers look for. Don't squash the history.
3. **Keep a running `AI_USAGE.md`, or a README section.** It should cover which tools were used, what they generated, and what humans designed, reviewed and changed. It takes 10 minutes at the end if you've been jotting notes.
4. **Every teammate should be able to explain their own area's code** without opening Claude. Judges and MLH staff may ask.
5. **Credit everything:** frameworks, libraries, APIs, AI tools and any third-party or AI-generated assets. Do it in the README **and** on Devpost, as HackPrinceton requires both.
6. **Don't overstate your work.** Past rules disqualify embellishment, so phrase AI-assisted work honestly ("we designed X; Claude Code helped implement Y").
7. **Feature freeze about 3 hours before the Sunday 8 AM deadline** (assuming the same schedule as before). Push everything before the deadline, and only make small fixes after it.

**Draft disclosure for Devpost ("How we built it" or a "Tools & AI use" section):**

> **AI tools used.** Our team used Claude Code (Anthropic) as an AI pair programmer throughout the hackathon, [plus GitHub Copilot / Cursor / ChatGPT if used]. We designed the product, architecture, API contracts and UI ourselves. We split the work by area (frontend, backend, AI/data, integration), and each of us used Claude Code to help write, debug and refactor code in our own area. We reviewed, tested and integrated every change. [Optional: Images/audio in the demo were generated with ___.] All code was written during HackPrinceton Fall 2026 (Nov 13–15). The only material prepared beforehand was our idea notes and a generic team task-tracking template, added in commit `<sha>`. Frameworks and libraries are credited in our README.

A short version for the README: "Built during HackPrinceton Fall 2026 with help from Claude Code (AI coding assistant). Human-designed; AI-assisted implementation. See *AI usage* below for details."

##### Open questions (confirm in the hacker packet, or ask organizers on Discord)

1. **The 85% rule and AI:** Is the "at least 85% of code written by you" rule still in effect for Fall 2026? Does code generated by an AI assistant that the team directs and reviews count as "written by you"? *(The most important question. MLH's standard rules allow AI code generation, but HackPrinceton's wording is ambiguous.)*
2. Is there an explicit Fall 2026 AI policy? Is a specific disclosure field or format required on Devpost?
3. What are the exact hacking start and end times? (Past events ran Fri 8:00 PM to Sun 8:00 AM ET, but that isn't confirmed for Fall 2026.) Must the repo be *created* inside the window, as in past events?
4. Can we bring generic, non-project templates (CLAUDE.md, TASKS.md) and add them in the first commit?
5. Hardware: can we bring our own components? Is there a hardware lab or checkout? Do any rules apply to pre-owned kits?
6. Are there any sponsor-track rules (for example the Anthropic, OpenAI or MLH "Best Use of" prizes) with their own requirements on AI usage or disclosure?
7. When will the Fall 2026 Devpost page go live? Re-run this check against its /rules page as soon as it does.

##### Sources

- HackPrinceton Fall 2026 site and FAQ: https://www.hackprinceton.com/ (FAQ at #faq)
- HackPrinceton Fall 2026 Devpost (not live as of Nov 9): https://hackprinceton-fall-2026.devpost.com/rules (404) and https://hackprinceton-fall-26.devpost.com/rules (403)
- HackPrinceton Spring '26 rules: https://hackprinceton-spring-26.devpost.com/rules ; overview and requirements: https://hackprinceton-spring-26.devpost.com/
- HackPrinceton Fall 2025 rules: https://hackprinceton-fall-2025.devpost.com/rules ; overview and requirements: https://hackprinceton-fall-2025.devpost.com/
- Devpost listing of HackPrinceton events: https://devpost.com/hackathons?search=hackprinceton
- MLH Standard Hackathon Rules: https://github.com/MLH/mlh-policies/blob/main/standard-hackathon-rules.md
- MLH Organizer Guide, Rules for Your Hackathon: https://guide.mlh.com/general-information/judging-and-submissions/rules-for-your-hackathon
- MLH Organizer Guide, Cheating Check: https://guide.mlh.com/general-information/judging-and-submissions/cheating-check
- MLH cheating response policy: https://github.com/MLH/mlh-policies/blob/main/cheating-response.md
- MLH Contest Terms: https://github.com/MLH/mlh-policies/blob/main/contest-terms.md
- MLH Code of Conduct: https://github.com/MLH/mlh-policies/blob/main/code-of-conduct.md (PDF: https://static.mlh.io/docs/mlh-code-of-conduct.pdf)
- Devpost organizer docs: https://help.devpost.com/article/102-managing-submissions , https://help.devpost.com/article/64-judging-public-voting
- Third-party repo-check tools (context only): https://devpost.com/software/gitcheck , https://devpost.com/software/hackfair

#### What won before (pattern guide; **past-event data only**)

| Event | Project | Prize(s) won | What it is | Stack highlights |
|---|---|---|---|---|
| F25 | [MindPad](https://devpost.com/software/mindpad) | **Best Overall**; Amazon Practical AI; MLH Gemini | Gesture-driven learning ("one gesture at a time") | MediaPipe, OpenCV, Gemini, OpenAI Agents SDK |
| F25 | [TerraLink](https://devpost.com/software/terralink-h5vuel) | **Best Overall**; Best Sustainability | Multi-agent AI plus Google Earth Engine for renewable-energy site selection | Gemini, Earth Engine, Flask, React |
| F25 | [Watt's Up](https://devpost.com/software/watt-s-up) | **Best Overall** | Rooftop solar potential from imagery | SegFormer, NASA POWER API, Google Maps, Dedalus |
| F25 | [Synovia](https://devpost.com/software/presurg) | Best Healthcare | "See surgical outcomes before the first incision" | Gemini, FastAPI |
| F25 | [Jigsaw](https://devpost.com/software/jigsaw-make-your-pcb-board-click) | Best Business + Enterprise ($3K) | AI-assisted PCB part-hunting and spec-checking | Dedalus, Flask, React |
| F25 | [Lume](https://devpost.com/software/lume-zrlypk) | Best Education + Entertainment; MLH ElevenLabs | Voice on-screen tutor for seniors (Chrome extension) | Claude, OpenAI, ElevenLabs |
| F25 | [FoodBridge](https://devpost.com/software/foodbridge-ac6nei) | Best Rookie | Restaurant food-waste to shelters, with tax incentives | Next.js |
| F25 | [Interactive DAW](https://devpost.com/software/interactive-daw) | Best Hardware | Webcam plus ultrasonic-sensor music instrument | Raspberry Pi, MediaPipe |
| F25 | [Recall](https://devpost.com/software/recall-cf0dp9) | xAI Grok; MLH Arm | Face and memory aid for dementia patients | Grok, OpenCV, Raspberry Pi |
| F25 | [doeve](https://devpost.com/software/do-eve) | Photon (Hybrid Intelligence) | Control your computer over iMessage | Claude, LangGraph, Photon, ElevenLabs |
| S26 | [Asclepius](https://devpost.com/software/asclepius-4rthsu) | **Best Overall**; d_model; Regeneron | Privacy proxy that strips PHI between clinical-trial staff and cloud AI | Claude, Gemma, differential privacy, FastAPI |
| S26 | [VITAL](https://devpost.com/software/vital-ay4d5c) | Best Healthcare | Camera/VLM that monitors waiting rooms for patient deterioration | YOLOv8, MediaPipe, Claude, ElevenLabs, Photon |
| S26 | [LEGR](https://devpost.com/software/legr) | Best Business & Enterprise; Enter Pro | Autonomous finance agents for startups | Claude, OpenAI, Dedalus, Knot, Photon |
| S26 | [Spark](https://devpost.com/software/spark-nxad1k) | Best Education | "Curiosity engine" for lifelong learners | Claude, React, Firebase |
| S26 | [Ember](https://devpost.com/software/ember-rs7j9p) | Best Hardware | Autonomous fire-suppression robot with local ML | Jetson Nano, RealSense, Arduino |
| S26 | [Hop-It](https://devpost.com/software/hop-it) | Best Rookie; **Justin Bojarski Hardware + AI** | Draw levels on paper, play them, and let AI remix them | Gemini Vision, K2 Think, React |
| S26 | [ShakeUR](https://devpost.com/software/shakeur) | MLH DigitalOcean; Sonar Nonsense | Alarm clock you can only turn off by dancing | MediaPipe, OpenCV |
| S26 | [Wavelength](https://devpost.com/software/wavelength-9bzr06) | Photon (Agents in iMessage) | Merges GCal and Canvas and sends iMessage reminders | Anthropic, Photon |

**Patterns:**
1. **Overall winners pair a concrete societal problem** (climate siting, clinical privacy, learning) **with a strong live visual demo**. That matches the Charity + Utility criteria.
2. **Computer vision and gesture or camera input wins repeatedly** (MindPad, VITAL, Interactive DAW, ShakeUR, Recall, Ember).
3. **Agents that take real actions** beat chatbots (doeve, LEGR, Wavelength). Photon iMessage agents won at both past events.
4. Hardware prizes went to small, reliable builds (Raspberry Pi or Jetson plus a sensor).
5. **Prize stacking is normal.** Choose sponsor APIs that fit naturally (Gemini, a Photon agent, MongoDB, a GoDaddy domain) instead of forcing them in.

Full winner galleries: [F25](https://hackprinceton-fall-2025.devpost.com/project-gallery?winners=true) · [S26](https://hackprinceton-spring-26.devpost.com/project-gallery?winners=true) · [S25](https://hackprinceton-spring-2025.devpost.com/project-gallery?winners=true)

---

_[Removed before publishing: travel or private email details.]_

#### Open questions / need from John

1. **Hacker packet contents.** Please open my.hackprinceton.com/dashboard, then "Hacker resources," and paste or export the packet. It probably holds the schedule, check-in time and place, the sponsor prize list, rules (AI-tool policy, repo timing), food and sleeping, and hardware.
2. **Confirm status in the portal:** are you accepted and confirmed? Is there an RSVP, waiver or MLH-terms step still pending?
3. **Teammates:** have all 3 teammates been accepted and confirmed? Each has to be checked in to be on the Devpost submission.
4. **Discord:** have you joined? Prize announcements, sponsor API codes and team channels are usually posted there first.
7. **Things to watch for in the packet:** (a) whether the S26 "85% of code written by you during the event" rule carries over and how it treats AI tools; (b) whether track winners can also win Best Overall; (c) the exact submission deadline (last year it was Sun 8:00 AM ET).
8. **Sponsor prize details** for CoStar, Amazon, Salesforce, Peri, Arlequin, D. E. Shaw, Capital One, Photon, Scale AI, LangChain, ChatOverflow and Justin Bojarski. These are not published anywhere public yet.

---

#### Sources

**Web (fetched Nov 9, 2026):**
- HackPrinceton Fall 2026 site (tracks, FAQ, sponsors, venue, speaker): https://www.hackprinceton.com (track and sponsor data read from the page and its JS bundle)
- MLH event page (event window in UTC, 8 MLH prize categories, Digi-Key Hardware Lab): https://www.mlh.com/events/hackprinceton-fall-2026 and https://www.mlh.com/events/hackprinceton-fall-2026/prizes
- MLH 2027 season list (start and end timestamps, Software/Hardware focus): https://www.mlh.com/seasons/2027/events
- Devpost search API: no Fall 2026 page found. https://devpost.com/api/hackathons?search=hackprinceton
- Fall 2025 Devpost (prizes, judges, criteria, requirements): https://hackprinceton-fall-2025.devpost.com/ · rules: https://hackprinceton-fall-2025.devpost.com/rules · dates: https://hackprinceton-fall-2025.devpost.com/details/dates · winners: https://hackprinceton-fall-2025.devpost.com/project-gallery?winners=true
- Spring 2026 Devpost: https://hackprinceton-spring-26.devpost.com/ · rules: https://hackprinceton-spring-26.devpost.com/rules · dates: https://hackprinceton-spring-26.devpost.com/details/dates · winners: https://hackprinceton-spring-26.devpost.com/project-gallery?winners=true
- Spring 2025 winners: https://hackprinceton-spring-2025.devpost.com/project-gallery?winners=true
- Individual winning project pages on devpost.com/software/... (linked in the table above), used for prize labels and stacks
- Sponsor sites, for one-line descriptions: https://photon.codes · https://arlq.ai · https://chatoverflow.dev · https://peri.so

_[Removed before publishing: travel or private email details.]_

**Not accessed:** the HackPrinceton portal (my.hackprinceton.com) and Discord, because both need John's sign-in.

### 📄 `ideas.md`

> **Last edited:** Nov 09. **Status:** Nov 9 idea scoring. The robot won; hoverboard details are stale.

### Ideas — HackPrinceton Fall 2026

_Nov 9, 2026. Scored against `research.md`: 6 tracks (Education, Entertainment, Sustainability, Healthcare, Business + Enterprise, Science + Discovery), past judging criteria (**Creativity, Utility, Charity** = societal need, **Avidity** = passion/polish), cross-track prizes (Best Overall, Rookie, **Hardware**), and sponsor prizes. Fall 2026 sponsor prizes are mostly unpublished, so the "prize stack" column uses the confirmed MLH prizes plus sponsors that ran prizes before (Photon, Amazon, Capital One, Justin Bojarski "Hardware + AI"). Theme: "Passport to Innovation."_

#### Bottom line

- **Top pick: John's modular self-balancing robot (#1), pitched with a real use case.** Use the camera "follow-me + fetch" module for Healthcare/accessibility (#2). A bare platform scores low on Utility and Charity, but a platform plus one useful module scores well on all four judging criteria. It also targets Best Hardware and Bojarski's Hardware + AI prize, and matches the past-winner pattern (CV + something physical).
- **Biggest risks are logistics, not code.** A hoverboard can't fly with you: airlines ban self-balancing boards and their lithium batteries, and your tickets are Basic Economy/personal-item only. It has to be **delivered to NJ** by Thu/Fri. Second risk: tuning the balance loop in 36 h. You need a fallback (a kickstand/caster) that still demos the CV.
- **Rules:** buying parts in advance is fine. Writing the balance controller or module code before the event isn't (the 85% rule, repo created during the event). Pre-assembling the mechanics is a **gray area: ask the organizers**. Open-source hoverboard motor firmware counts as a credited library.
- **Software fallback if hardware falls through:** #5 (Photon iMessage agent) or #6.

#### Scoring (1–5 each; Feasibility = can 4 people finish a polished demo in 36 h)

| # | Idea | Track | Creativity | Utility | Charity | Avidity / wow | Prize stack | Feasibility | **Total /30** |
|---|---|---|---|---|---|---|---|---|---|
| 2 | **Balancing robot + "follow-me & fetch" care module** | Healthcare | 4 | 4 | 5 | 5 | 5 | 2 | **25** |
| 1 | Modular balancing robot platform (bare) | Science + Discovery | 4 | 3 | 2 | 5 | 4 | 2 | **20** |
| 3 | Balancing robot as telepresence "passport" | Education | 4 | 3 | 4 | 5 | 4 | 2 | **22** |
| 4 | Pi + camera field kit for citizen science | Sustainability / Science | 3 | 4 | 4 | 3 | 4 | 4 | **22** |
| 5 | Photon iMessage agent for international-student paperwork | Business / Education | 3 | 5 | 4 | 3 | 4 | 5 | **24** |
| 6 | Gesture/CV physical-therapy coach | Healthcare | 3 | 4 | 5 | 4 | 3 | 4 | **23** |
| 7 | Student money copilot (Capital One-style) | Business + Enterprise | 2 | 4 | 3 | 3 | 4 | 5 | **21** |

Ranking: **2 > 5 > 6 > 3 = 4 > 7 > 1**. Ideas 1–3 are the same robot with different pitches. Build #1 as the platform, then pitch it as #2 (or #3).

---

#### 1. Modular self-balancing robot (John's idea)

> **Full design, BOM, 36-h plan and risks: [`robot-plan.md`](robot-plan.md).** Nov 9 update: a scaled-down build (12 V geared DC motors + ESP32 + Pi 5, ~$300–430) replaces the hoverboard, and the parts fly in personal items.

A vertical aluminum extrusion mast on a hoverboard base. An IMU measures tilt angle and angular rate, and a control loop (PID → LQR if time) keeps it upright like an inverted pendulum. Modules bolt onto the mast and plug into a simple software interface (power + USB/I²C + a "module" API) without touching the balance code. A camera at the top handles CV.

- **Architecture sketch:** microcontroller (ESP32/Teensy) runs the 200–500 Hz balance loop with the IMU (e.g. BNO085/MPU-6050). It talks over UART to the hoverboard's motor boards (open-source FOC firmware, credited) or to a separate ESC. A Raspberry Pi 5/Jetson on the mast runs CV and the module bus and sends velocity/heading setpoints to the MCU.
- **Prizes:** Best Hardware, Bojarski Hardware + AI (if it runs again), Gemini (vision), Digi-Key lab parts.
- **Weak spot:** "a platform" doesn't solve a problem, so judges score Utility/Charity low. Use #2 or #3 as the pitch.

#### 2. Platform + "follow-me & fetch" care module ⭐

Same robot. The camera tracks a person (MediaPipe pose/person detection) and the robot follows them at a set distance, carrying a tray/basket module. Voice or gesture: "come here," "stop," "bring this to the nurse station." Pitch: mobility-limited patients, elderly people, and hospital staff carrying supplies.

- **Why it wins:** a live robot following a judge around the table is the most memorable 2-minute demo possible. It scores on all four criteria and stacks Hardware + Healthcare + an AI/vision sponsor prize.
- **36-h scope:** balance + drive (P0) → person-following (P0) → tray module + one voice/gesture command (P1) → web dashboard showing the camera feed and module list (P1).
- **Fallback:** if balancing isn't stable by **hour 18**, bolt on a caster/kickstand and demo as a 2-wheel + caster robot. Following and modules still work, and you tell judges balancing is "in tuning."

#### 3. Platform as telepresence "passport"

A remote user (a hospitalized kid, a prospective student abroad) drives the robot through a web page and sees through its camera. That's a "passport" to a campus or museum. Fits the theme well and the Education track. Needs low-latency video (WebRTC). Riskier networking on hackathon Wi-Fi.

#### 4. Pi + camera citizen-science field kit

A handheld or stationary Pi + camera + sensors that identifies plants, insects or birds (vision model) and logs air quality. It uploads to a shared map (MongoDB Atlas). Hardware-prize eligible, much less mechanical risk than the robot. Pattern-matches past Hardware winners (small, reliable builds).

#### 5. Photon iMessage agent for international-student paperwork

"Passport" taken literally: an iMessage/WhatsApp agent (Photon) that walks international students through visa, I-20, OPT and SSN steps. It reads uploaded documents, tracks deadlines and drafts forms. High Utility/Charity, very feasible, and Photon ran prizes at both past events. Low physical wow, so it needs a polished conversation demo.

#### 6. Gesture/CV physical-therapy coach

A webcam app that counts reps and checks form for prescribed PT exercises (MediaPipe pose) and gives voice feedback. It sends a progress summary to the physical therapist. Strong Healthcare fit; CV demos well. Common hackathon idea, so it needs a sharp angle.

#### 7. Student money copilot

An agent that reads transaction exports, finds subscriptions/waste, and explains it in plain language, targeting a Capital One-style finance prize. Very feasible, but the idea is crowded and low on wow.

---

#### If we go with the robot: do these this week (before Nov 13)

1. **Ask organizers (Discord, once John joins):** can we bring our own hardware? Can we pre-assemble mechanics (mount the extrusion), or must all assembly happen during hacking? Can we flash stock open-source motor firmware ahead of time? What does the Digi-Key lab have?
2. **Get the hoverboard to NJ.** Order one delivered to where you stay Thu night or to Princeton (address needed: no lodging found yet). Pick a model known to work with open-source FOC firmware (check its board type before buying). Alternative: buy locally Thu evening.
3. **Order parts** (ship to NJ): 2020 extrusion + brackets, IMU, ESP32, Pi 5 or Jetson + camera, buck converter for 36 V → 5 V, kill switch, ST-Link (for flashing), zip ties, M5 hardware. Tools that fly in the checked bag (you'd need to add one).
4. **Learn, don't code:** read up on inverted-pendulum control, LQR vs. PID, and how the FOC firmware's UART protocol works. Reading is allowed; writing project code isn't.
5. **Safety:** a 36 V battery and a robot that falls over. Plan a physical e-stop and a tilt cutoff (motors off past ~30°).

#### Open questions for the team

- Is everyone on board with hardware? Who has embedded/controls experience (John's hexapod helps)?
- Budget for parts and who pays?
- Robot pitch: #2 (care/fetch) or #3 (telepresence)?

### 📄 `robot-plan.md`

> **Last edited:** Nov 09. **Status:** Only §3–§5 of the Nov 9 plan: the 36-hour plan, risks and fallbacks, tracks/prizes and the demo script. The older full-size hardware sections are left out (Part 1 replaces them).

#### 3. 36-hour plan (T = hacking start, probably Fri ~8 PM ET; submit ~T+36)

**Roles** (they map to `team-setup/` directory ownership; swap people by skill):
| Role | Owns | Who (suggested) |
|---|---|---|
| **Mech / CAD** | `/hardware` (CAD, BOM, wiring diagram), all modules' mechanics | the CAD person |
| **Controls / firmware** | `/firmware` (ESP32 balance loop, safety, tuning) | John (hexapod experience) |
| **Robot software + Integrator** | `/robot` (robotd, serial link, module manager, dashboard), `main`, demo path | strongest Python person |
| **Vision / AI + pitch** | `/vision`, module plugins, Gemini, Devpost + video | the OpenCV/Claude person |

| Time | Mech / CAD | Controls / firmware | Robot software (integrator) | Vision / AI |
|---|---|---|---|---|
| **T+0–1** | Lock dims (wheel, base, mast) | Write serial contract v0 with integrator | Create repo from kit, contracts v0, mock ESP32 | Contract for CV → `robot.drive()` |
| **T+1–6** | Base + motor mounts + mast; wiring harness; **caster holes** | IMU read + filter, motors open-loop, encoders (PCNT), e-stop/tilt cutoff | robotd: serial link vs. mock, joystick dashboard, telemetry plot | Follow-me on laptop webcam vs. mock robot |
| **T+6–10** | Finish chassis; module-plate CAD template | **First balance tries (tethered rope or outriggers)** | Real serial link to ESP32; live gain tuning UI | Port CV to Pi; measure fps |
| ✅ **T+10** | | **Checkpoint: balances 10 s tethered** | | |
| **T+10–18** | Pan-tilt head + tray mechanics | Tune; add velocity loop (holds position) + driving | Module manager + plugin API + hot-plug | Gestures; pan-tilt plugin |
| 🚦 **T+18 (Sat ~2 PM)** | **Go/no-go:** balances + drives by joystick? If not → **kickstand mode** for the demo, keep tuning in parallel until T+28 | | | |
| **T+18–26** | Module polish, cable management, looks | LQR (stretch) or PID robustness under payload | Dashboard polish; voice/Gemini command routing | Follow-me integrated end-to-end; Gemini scene/commands |
| **T+26–33** | Spares, repairs | Battery cutoff, fault handling | **Demo path rehearsals** (×5) | Devpost draft, pitch script, record backup video |
| 🧊 **T+33 freeze** | | | Bug fixes only | Final video + Devpost |
| **T+35** | | | **Submit** (1 h buffer) | |

Sleep in shifts: Controls and Vision sleep about T+12–16, Mech and Integrator about T+20–24. Never leave the robot powered while unattended.

---

#### 4. Risks and fallbacks

| Risk | Likelihood | Mitigation |
|---|---|---|
| **Balance loop won't tune** | High | Cascaded PID (angle first: raise Kp until it oscillates, add Kd, then the velocity loop). Fixed 500 Hz loop timing. IMU rigid and near the axle. Deadband compensation. Grippy tires. Live gains + θ plots. Start tethered. Go/no-go at T+18. |
| Gearbox backlash / motor saturation | Medium | 1:30 ratio (not 1:90). Keep the mast tall enough (slower fall). Watch the PWM-saturation % in telemetry. |
| Driver or motor burns out | Medium | 15 A fuse, spare driver (BTS7960), spare motor, don't stall motors for long. |
| **LiPo fire / damage** | Low, severe | LiPo bag, balance-charge attended only, firmware low-voltage cutoff, no crushed or puffy packs. Ask organizers if LiPos are allowed. |
| Runaway / falling robot near people | Medium | Physical e-stop, tilt cutoff, command watchdog, test in a cleared floor area, tether during tuning. |
| Pi 5 brownouts when motors spike | Medium | Separate 5 V/5 A buck, capacitor on the buck input, common ground, thick power wires. |
| Venue Wi-Fi flaky | High | Pi runs its own **hotspot** for the dashboard. Gemini features have an offline fallback (local MediaPipe only). |
| CV too slow on the Pi | Medium | 320×240, MediaPipe lite models, process every 2nd frame, offload to a laptop if needed. |
| Parts don't arrive by Wed | Medium | Order today with Prime 1–2 day shipping. One person tracks orders. Backup: Digi-Key lab and local stores. |
| Rules on pre-built hardware | Unknown | Ask organizers today; design a no-print path. |
| Scope creep | High | Exactly 2 modules. Modularity is shown by the live swap, not by module count. |

**Fallback demo tiers (design all three in from the start):**
1. **Target:** balances, follows a judge carrying the tray, live hot-swap of the pan-tilt head.
2. **Balancing flaky → kickstand mode:** caster down, same robot drives as differential drive. Follow-me + modules work fully. Show the best balancing clip + telemetry graph from earlier.
3. **Driving dead → "smart mast" on the table:** the pan-tilt head tracks the judge's face, module hot-swap, dashboard, recorded clips.

---

#### 5. Tracks, prizes and pitch

- **Main track: Healthcare** (recommended). Pitch: "a $400 helper robot for people with limited mobility. It follows you, carries things, and anyone can add a module." The Charity and Utility criteria reward a concrete need. Alternatives: **Education** ("an open $400 platform to teach robotics") or **Science + Discovery** ("a modular field-research rover"). Both are weaker on Charity.
- **Cross-track:** **Best Hardware Hack** (past winners were small, reliable Pi/Jetson builds, so reliability beats size), **Best Overall**.
- **Sponsor prizes to stack (check the F26 list when it's out):**
  - **Justin Bojarski "Best Hardware + AI"** (ran at S26).
  - **MLH Best Use of Gemini** (scene description / natural-language commands).
  - **Photon** (ran at both past events). A "text the robot" module: iMessage "bring my water to the couch." That's software-only, so it's cheap to add, and it shows modularity.
  - Maybe **MongoDB Atlas** (module registry/telemetry) only if it's natural. Don't force it.
- **2-minute demo script:**
  1. **0:00–0:15** The robot rolls up *following the judge*, tray on top.
  2. **0:15–0:40** Problem + what it is: balancing means a small footprint, so it fits through doorways and between hospital beds.
  3. **0:40–1:20** **Live module swap:** slide on the pan-tilt head, plug in USB, it appears on the dashboard and starts tracking, "and we never touched the balancing code."
  4. **1:20–1:45** How: 500 Hz control on the ESP32, plugin API on the Pi, show the live pitch graph, $400 BOM.
  5. **1:45–2:00** What's next: open-source module spec, community modules.
- **Credit inspiration:** say in the Devpost that it's inspired by open-source balancing robots such as BracketBot. Don't reuse their code or CAD (the 85% rule). Disclose AI-tool use.

---

## B. Hardware

### 📄 `parts-list.md`

> **Last edited:** Nov 13. **Status:** Current parts list (Nov 13).

### Self-balancing robot: parts list

A half-size two-wheel balancing robot with an iPhone on the mast as its camera. An ESP32-S3 balances it on 2 NEMA 17 steppers, and a laptop runs the vision and sends drive commands over Wi-Fi. It's a no-solder, no-crimp build: screw terminals, Wago lever nuts and Dupont jumpers. Total ≈ $285 for the bought parts.

#### Electronics and power (bought)

| Part | Qty | Price | What it does |
|---|---:|---:|---|
| STEPPERONLINE NEMA 17 stepper (84 oz·in, 48 mm) | 3 | $32.99 | Wheel motors (1 spare) |
| BIGTREETECH TMC2209 V1.3 stepper driver | 4 | $22.99 | Motor drivers (2 spares), 1/16 microstepping |
| Stepper driver expansion board (42 CH) | 2 | $7.99 | Driver socket, 12 V screw terminals, onboard capacitor |
| ESP32-S3 DevKitC-1 N16R8 + screw-terminal breakout | 2 sets | $24.99 | Main controller (1 spare) |
| GY-521 MPU-6050 IMU, pre-soldered | 3 | $14.99 | Tilt sensing (2 spares) |
| LM2596 buck converter with voltage display | 3 | $9.99 | 12 V → 5 V for the ESP32 (2 spares) |
| OVONIC 3S 2200 mAh 35C LiPo, XT60 | 2 | $34.99 | Battery (about 24 Wh each) |
| 80 W B6-type LiPo balance charger | 1 | $37.99 | Charges the 3S packs |
| XT60 pigtails, 14 AWG | 5 pairs | $11.99 | Battery leads, short power wires |
| 16 AWG inline fuse holders + fuses | 4 | $7.99 | 15 A main, 5 A branches |
| WAGO 221 lever nuts | 12 | $12.45 | 12 V and ground distribution |
| Dupont jumper wires | 120 | $6.98 | Signal wiring |
| 85 mm solid rubber wheels + 5 mm clamping hubs | 2 | $23.99 | Wheels |
| 2.1 × 5.5 mm DC barrel adapters | 5 M + 5 F | $4.99 | Bench 12 V tether, arm power |
| XT60 → 4 mm banana charge lead | 1 | ~$7 | Battery to charger |

#### Already owned

- **Arm:** HTD-45H bus servos ×3 and a BusLinker board
- **Camera:** a spare iPhone, held in the printed mast cradle
- **Printer:** Bambu P2S with PETG
- **Bench power:** 12 V 5 A desk supply, used as a tether while tuning

#### Fasteners

| Item | Needed | Buy (with spares) |
|---|---:|---:|
| M3 × 6 socket head screw | 34 | 40 |
| M3 × 8 socket head screw | 21 | 25 |
| M3 heat-set insert (for Ø4.0 × 5.5 mm holes) | 47 | 55 |
| Zip ties (100 mm) | | 20 |
| Velcro strap, 16 mm | 2 | 2 |

#### 3D-printed parts (PETG, no supports)

22 parts, about 325 g of filament and 18 hours of printing in total:

- **Base:** base plate, left and right motor mounts, kickstand, battery cradle
- **Electronics:** electronics shelf, ESP32 carrier, 2 driver carriers, buck holder, Wago frame, IMU pedestal and clamp
- **Mast:** 240 mm mast
- **Phone mount:** base, cradle, and 4 shims (2 × 1.5 mm, 2 × 3 mm) that fit phones 70–81 mm wide
- **Arm:** arm mount and clamp

#### Tools

- 2.5 mm hex key (every screw is M3 socket head)
- Soldering iron with a heat-set insert tip (about 245 °C for PETG)
- Wire stripper, flush cutters, small flat screwdriver
- Multimeter, to set the buck converter to 5.0 V

### 📄 `build-guide.md`

> **Last edited:** Nov 09. **Status:** How it works, wiring, pins, bring-up order, safety. The mechanical section predates CAD v3; the assembly guide replaces it.

### Balancing robot: how it works and how to build it

_Nov 9, 2026. Matches the parts actually ordered (`shopping-list.md`). This is a design and instruction doc, which is fine before the event. **Write all project code at the event** (the 85% rule). Do mechanical assembly at the event too unless the organizers OK pre-building._

---

#### 1. How it works (the 60-second version)

A balancing robot is an **inverted pendulum**: a stick balanced on wheels. Left alone it falls over. The trick is the same as balancing a broom on your palm: **when it starts to tip forward, move the wheels forward under it**, and the body swings back upright.

```
      tips forward ↘            wheels drive forward →        body is upright again
        ___                         ___                              ___
       /  /                        |  |                             |  |
      /  /                         |  |                             |  |
   (o)  (o)        →             (o)  (o)  →→        →            (o)  (o)
```

This happens **hundreds of times per second**:

1. **Sense:** the **IMU** (MPU-6050) measures tilt angle and how fast it's tipping.
2. **Think:** the **ESP32** runs a control loop (PID): "I'm leaning 3° forward and falling at 20°/s, so speed the wheels up forward by X."
3. **Act:** the ESP32 sends step pulses to the **TMC2209 drivers**, which turn the **NEMA 17 steppers** and wheels.
4. Repeat about 200–500 times per second.

A second, slower loop stops the robot from drifting. If it's rolling away, it leans slightly backward on purpose to slow down. **To drive**, you ask it to lean a little in the direction you want to go. **To turn**, one wheel spins a bit faster than the other.

**The "smart" layer runs elsewhere:** the **phone** on the mast streams video to a **laptop**. The laptop runs computer vision (MediaPipe person tracking) and sends simple commands over Wi-Fi, like "forward 0.3 m/s, turn left 0.2." The ESP32 keeps balancing on its own no matter what. If Wi-Fi drops, it just stops driving and stays upright.

**Modules** (the servo arm and pan-tilt head) are add-ons. They bolt to the mast and get commands from the laptop, and they never touch the balance loop.

---

#### 2. System diagram

```
POWER (thick wires)
 OVONIC 3S LiPo ─XT60─► pigtail ─► 15A fuse ─► WAGO (+12V) ──┬──► Driver board L (VM+)
                                              WAGO (GND)  ──┼──► Driver board R (VM+)
                                                            ├──► Buck in ──► Buck out 5.0V ──► ESP32 5V/GND terminals
                                                            └──► male barrel ──► BusLinker (servos)  [optional]
 (Tuning on the bench: 12V desk supply ─► female barrel ─► WAGOs instead of the battery)

SIGNALS (Dupont jumpers)
 ESP32 ──STEP/DIR──► Driver L ──► NEMA 17 L ──► wheel L
 ESP32 ──STEP/DIR──► Driver R ──► NEMA 17 R ──► wheel R
 ESP32 ──EN (shared)─► both drivers
 ESP32 ◄──I2C (SDA/SCL)── MPU-6050 IMU
 ESP32 ◄──Wi-Fi──► Laptop (vision + dashboard) ◄──video── Phone on mast
 ESP32 or laptop ──serial──► BusLinker ──► HTD-45H servos (arm / head)  [stretch]
```

All grounds (GND) connect together through the GND Wago. That shared ground is required for the signals to work.

---

#### 3. What each part does

| Part | Job |
|---|---|
| OVONIC 3S 2200 mAh ×2 | Robot power (11.1 V nominal, 12.6 V full). About 45–60 min per pack |
| B6 charger + XT60→banana lead | Charging (LiPo BALANCE mode, 3S, 2.2 A; plug in the balance lead too) |
| XT60 pigtails | Battery plugs into the robot. Spares get cut up as short power wires |
| Fuse holders (blue = 15 A) | Protect against short circuits |
| WAGO lever connectors | Split +12 V and GND to everything, no solder |
| Stepper driver expansion boards ×2 | Hold each TMC2209: 12 V screw terminals, motor plug, onboard capacitor, DIP switches |
| TMC2209 ×4 (2 spares) | Turn ESP32 step pulses into motor coil currents |
| NEMA 17 ×3 (1 spare) | Wheel motors |
| 85 mm wheels + 5 mm clamping hubs | Wheels (clamp onto the motor shaft) |
| ESP32-S3 + screw-terminal board ×2 (1 spare) | The brain: IMU, balance loop, Wi-Fi |
| MPU-6050 ×3, pre-soldered (2 spares) | Tilt sensor |
| LM2596 buck ×3 (display) | 12 V → 5.0 V for the ESP32 |
| Dupont jumpers | All signal wires |
| DC barrel adapters | Female: desk supply → Wagos. Male: Wagos → BusLinker |
| Stripper, tape, zip ties | Strip wire ends, tape LiPo plugs for the flight, tidy cables |
| Phone (owned) | Camera + screen ("face") on top |
| HTD-45H ×3 + BusLinker (owned) | Leg arm / head modules (stretch) |

---

#### 4. Mechanical build (printed on the P2S)

**Target:** about 35–40 cm to the top of the mast, about 2–2.5 kg, wheels 85 mm.

| Printed part | Notes |
|---|---|
| **Base plate** (~22 × 12 cm, 5–6 mm thick, PETG or PLA with 4+ walls) | Holds both motors under it, axles in line. Add **holes for the kickstand/caster** from day one |
| **2 motor mounts** | NEMA 17 face: **31 mm square bolt pattern, M3**, 22 mm center boss hole. Motors face outward, shafts on one common axis |
| **Mast** (printed tube or box section, ~25–30 cm) | Stiff. Put a slot or hole pattern on the front so modules bolt on. Print in 2 pieces if it's taller than the bed |
| **Electronics shelf** (on the mast, ~8–12 cm up) | ESP32 board, 2 driver boards, buck, Wagos. Leave airflow around the drivers |
| **Battery holder** (low, on the base or lower mast) | Velcro or zip-tie strap. Must be removable to charge |
| **IMU mount** | **Rigid, near the axle, centered**, with its X or Y axis pointing forward. No foam, since vibration ruins the readings |
| **Phone clamp** (top of mast) | Holds the phone in portrait, screen forward, camera clear |
| **Kickstand / skid** | Fallback "caster mode" and parking. Printed skid or ball |
| Module plates | Standard bolt pattern for the arm and head |

**Assembly order:**
1. Motors → mounts → base plate (M3 screws).
2. Wheel hubs onto the shafts: line the clamp up with the shaft's flat (D-cut) and tighten firmly. Wheels onto the hubs.
3. Mast onto the base, then the shelf, battery holder and IMU mount.
4. Check it stands on the kickstand and the wheels spin freely.

**Balance tips:**
- Keep the robot symmetric left to right.
- A **higher center of mass is easier** to balance (it falls more slowly), so the phone up top is good. A heavy *low* battery is fine too.
- Everything must be **rigid**. A wobbly mast or a loose IMU makes tuning impossible.

---

#### 5. Wiring, step by step (no solder)

**Before you start:** battery unplugged, desk supply off. Red = +, black = −, always.

##### 5a. Power
1. **Battery input:** take a pigtail that mates with the battery. Route its **red** lead → **fuse holder (blue 15 A)** → into a **5-port Wago (+12 V)**. Its **black** lead → a second **5-port Wago (GND)**.
2. **Make short wires:** cut the plugs off 2–3 spare pigtails (they're 14 AWG). Strip about 11 mm for Wagos and about 6 mm for screw terminals.
3. **Driver boards:** +12 V Wago → each board's **VM / + screw terminal**. GND Wago → each board's **GND terminal**.
4. **Buck converter:** +12 V Wago → buck **IN+**. GND Wago → buck **IN−**.
5. **⚠️ Set the buck BEFORE connecting the ESP32:** power up (desk supply is safest), watch the display, and turn the small brass screw until it reads **5.0 V**. Power off.
6. Buck **OUT+** → ESP32 board **5V** terminal. Buck **OUT−** → ESP32 **GND** terminal (use male Dupont ends in the screw terminals, or short wires).
7. *(Optional)* +12 V/GND Wagos → **male barrel adapter** (screw terminals) → BusLinker jack.
8. *(Bench tuning)* Desk supply → **female barrel adapter** → the same Wagos, **instead of** the battery. Never connect both at once.

##### 5b. Driver boards
1. **DIP switches:** **MS1 ON, MS2 ON** (1/16 microstepping). **Third switch OFF.**
2. Plug the TMC2209 into the socket **the right way round**: match the **EN** pin to the board's EN label and the **GND/VM** corner to the board's markings. **Backwards = dead driver.** Stick on the heatsink.
3. Motor cable → the board's white motor connector. If it doesn't fit, use 4 jumpers in the same order.
4. **Current:** start with the driver's factory potentiometer setting. If the motors skip or feel weak, turn the pot **clockwise 1/8 turn** at a time. If a driver gets **too hot to touch**, back it off. (With a multimeter, borrowed from the hardware lab, set Vref from BTT's TMC2209 V1.3 formula for about **1.2–1.4 A RMS**.)

##### 5c. Signals (Dupont jumpers)
Suggested ESP32-S3 pins. Avoid **GPIO 0, 3, 45, 46** (boot pins), **19/20** (USB) and **35–37** (used by the N16R8's memory).

| From ESP32-S3 | To |
|---|---|
| GPIO 4 | Driver L **STEP** |
| GPIO 5 | Driver L **DIR** |
| GPIO 6 | Driver R **STEP** |
| GPIO 7 | Driver R **DIR** |
| GPIO 15 | **EN** on both drivers (LOW = motors on) |
| GND | Each driver board's logic **GND** (it's also common through the Wago) |
| 3V3 | MPU-6050 **VCC** |
| GND | MPU-6050 **GND** |
| GPIO 8 | MPU-6050 **SDA** |
| GPIO 9 | MPU-6050 **SCL** |
| GPIO 17 / 18 | *(stretch)* BusLinker serial TX/RX for the servos |

Zip-tie every cable. A robot that falls over pulls loose wires out.

---

#### 6. Software (write this AT the event)

**ESP32 firmware (C++/Arduino or PlatformIO):**
- Read the MPU-6050 at 200–500 Hz. Combine the gyro and accelerometer with a **complementary filter**, giving the tilt angle.
- **Inner loop (angle PID):** tilt angle + tilt rate → wheel acceleration.
- **Outer loop (speed PI):** wheel speed vs. target speed → small target lean angle (stops drift, enables driving).
- **Turning:** add/subtract a little speed per wheel.
- **Step generation:** the **FastAccelStepper** library (hardware timers, smooth). Credit it on Devpost.
- **Safety:** tilt > 35° → motors off (EN HIGH). No Wi-Fi command for 300 ms → target speed 0. Live-tunable gains over Wi-Fi or serial.
- Wi-Fi: receive `{v, w}` commands (UDP/WebSocket) and send back telemetry (angle, speed).

**Laptop (Python):**
- Phone video via a webcam app (DroidCam or similar) → OpenCV → **MediaPipe** person/pose tracking.
- Person's horizontal position → turn command. Person's size → forward speed (follow at a set distance).
- A small web dashboard: live tilt graph, gain sliders, joystick, module buttons.
- A module plugin system (Python) for the arm and head.

---

#### 7. Bring-up order (test one thing at a time)

| # | Test | Pass when |
|---|---|---|
| 1 | Power only (desk supply), nothing plugged into the drivers | Buck reads 5.0 V, nothing gets hot |
| 2 | ESP32 on 5 V | Blinks an LED, prints over USB serial |
| 3 | IMU | Tilt angle changes correctly when you tilt the robot by hand (sign and axis right) |
| 4 | One motor | Spins both directions smoothly. **Jitters? Swap one coil pair** |
| 5 | Both motors | Same direction = "forward" (flip DIR in code if one is backwards) |
| 6 | Kickstand mode | Drives with laptop commands with the robot leaning on its kickstand |
| 7 | **Balance, tethered** | Hold a loose string or hover your hands. Raise the angle gain until it fights back and oscillates, add rate damping, then the speed loop |
| 8 | Untethered on the battery | Stands still for 30 s, drives slowly |
| 9 | Vision + modules | Follows a person; servo modules work |

**Tuning tips:** tune on the desk supply. Plot tilt live. Change one gain at a time. If it oscillates fast, cut the gain or add damping. If it slowly drifts away, the speed loop is too weak. Don't touch the wiring between tuning runs.

---

#### 8. Safety
- **LiPo:** charge only in BALANCE mode, attended, on a non-flammable surface. Never below about 3.3 V per cell (check on the B6). A puffy or dented pack gets retired.
- **Off switch:** unplug the XT60 (keep it easy to reach), plus the firmware tilt cutoff.
- **Never** plug the battery and the desk supply in at the same time.
- Test balancing in a clear floor area. The robot will fall many times; keep fingers out from under it.
- Flying: tape each LiPo's XT60, bag each pack separately, carry-on only.

---

#### 9. What you can do before the event (allowed)
- Pick up the parts and **check each one works**, using vendor example sketches you **throw away afterwards**: buck reads 5.0 V, ESP32 blinks, IMU prints numbers, one motor spins.
- Charge and storage-charge the batteries.
- Read up on: complementary filters, PID tuning for balancing robots, the FastAccelStepper library, MediaPipe pose tracking.
- Install the tools: Arduino IDE/PlatformIO with ESP32-S3 support, Python + OpenCV + MediaPipe, a webcam app on the phone.
- **Ask the organizers** whether you may print parts and assemble the chassis beforehand. If yes, steps 4 and 5 can happen at home.

### 📄 `cad/design-review.md`

> **Last edited:** Nov 11. **Status:** CAD v3 design review (Nov 11): checks, print order, watch items.

### Design review: balancing robot v3 (print-ready)

_Nov 10, 2026 · build123d code-CAD in `cad/`; every shared dimension and the v3 rules live in `params.py`. Rebuild everything with `.venv/bin/python assembly.py` (about 4 min): checks, STEP, STLs, renders, viewer, drawing, assembly guide, spec sheet, print sheet and 3MF plates. Nothing was measured (your call, Nov 10): the board, battery and phone sizes are listing guesses, and the parts that hold them have slack built in._

**Open these:**
- **Print first:** [`out/print/print-sheet.md`](out/print/print-sheet.md) and the plates in `out/print/plates/` (3MF files for Bambu Studio, each with a preview PNG). The 3MF files hold geometry only. Take each plate's filament, walls and infill from its row in the print sheet's Plates table.
- **Build it:** [`out/guide/assembly-guide.md`](out/guide/assembly-guide.md), 20 illustrated steps with every fastener called out, plus tools, the insert map and the wiring table.
- **Look at it:**
  - `out/viewer.html`: interactive 3D; double-click to open in a browser.
  - `out/spec-sheet.png`: one page for Devpost.
  - `out/drawing.png`: dimensioned two-view sheet.
- **Edit it elsewhere:** `out/assembly.step`, grouped into base, drive_left, drive_right, mast, shelf, head, arm and fasteners.

![Balancing robot v3](out/renders/hero.png)

| Front | Right side | Rear | Top |
|---|---|---|---|
| ![](out/renders/front.png) | ![](out/renders/side.png) | ![](out/renders/rear.png) | ![](out/renders/top.png) |

| Section at x = 0 | Exploded | Parked on the kickstand |
|---|---|---|
| ![](out/renders/section.png) | ![](out/renders/exploded.png) | ![](out/renders/parked.png) |

| Drive (wheel hidden) | Base front | Shelf and carriers | Phone head | Arm mount |
|---|---|---|---|---|
| ![](out/renders/closeup_drive.png) | ![](out/renders/closeup_base.png) | ![](out/renders/closeup_shelf.png) | ![](out/renders/closeup_phone.png) | ![](out/renders/closeup_arm.png) |

| Spec sheet (Devpost) | Assembly guide, step 2 |
|---|---|
| ![](out/spec-sheet.png) | ![](out/guide/step_02.png) |

#### Bottom line
- **It all fits and it all prints.**
  - 253 bodies: 22 printed parts, 21 bought parts (129 bodies) and 102 fasteners.
  - **Zero interference.**
  - **All 22 printed parts are support-free**, checked automatically in their print orientation.
  - Every part fits the P2S bed.
  - Five plates of PETG Matte: about **17.0 h and 465 g**, including the optional test coupons. Times and grams are real Bambu Studio slices.
- **Easier to put together.**
  - **Only two screw lengths:** 34× M3×6 and 21× M3×8, plus 47 heat-set inserts. One 2.5 mm hex key does everything.
  - Every bolted part locates on a tongue, pin or key before the screws go in, so screws only clamp.
  - Left and right parts can't be swapped, the mast and shelf only fit facing forward, and nothing hides a screw you still need.
- **Lighter and steadier than v2.**
  - The robot weighs **2.21 kg** with PETG parts (v2: 2.27 kg).
  - The body's center of mass is **93 mm above the axle** (v2: 104 mm). It balances at **1.3°** of forward lean, with a 47/53 left/right load split.
  - Each motor needs 0.08, 0.16 and 0.31 N·m to hold 5°, 10° and 20°, below v2 and well within the NEMA 17s.
- **Parking and clearances.** It parks on the kickstand at **13.1°** and can lean 60° forward before anything but the wheels touches the floor. The wheels sit 3.0 mm from the mounts.
- **Unknown board sizes no longer force reprints.** The ESP32 and the driver boards sit on small carriers (6–10 g, about 15 min each) that bolt into the shelf. The buck clips onto boards of any length from about 62 to 66 mm, and the IMU clamps in a pocket instead of using its hole pattern.

#### Print it, in this order
Everything prints in **Bambu PETG Matte**, the team's only filament: white for the body and baby blue for the functional parts.

The 3MF plates hold geometry only. For every plate, set:
- printer P2S 0.4
- the textured PEI plate (or glue stick on a smooth plate)
- `0.20mm Standard`
- the walls and infill from that plate's row in the print sheet

1. **Plate 2, printed Nov 10:** the base plate, mast and electronics shelf in white, about 8.8 h and 262 g (4 walls, 25 % gyroid, a brim on the mast).
2. **Plate 3, printed Nov 10:** the motor mounts, the arm mount and its clamp, and the kickstand in baby blue, about 2.6 h (4 walls, 40 % gyroid).
3. **Plate 5, printed Nov 10:** the board carriers, buck holder, Wago frame, phone mount base, IMU pedestal and clamp, and the 1.5 mm phone shims in baby blue, about 2 h 40 min and 68 g.
   - Set 4 walls and 40 % gyroid for the whole plate.
   - Then set 100 % infill per object (Process → Objects) on `imu_pedestal` and `imu_clamp`. The shims come out solid anyway.
   - The phone base was reshaped on Nov 10 after Bambu flagged two floating ledges on it. Its pivot-pin slot now has a 45° back wall and its key is a 45° wedge, so it prints without supports.
4. **Plate 4, printed Nov 10:** the phone cradle, the battery cradle and the 3 mm phone shims in white, about 1.2 h and 38 g, with 3 walls and 20 % gyroid.
5. **Optional, overnight Nov 10–11: plate 6, spares** (`plate6_spares_any_petg.3mf`), about 11.3 h and 331 g in whatever colour is loaded.
   - One extra of each part a fall is likely to break: phone mount base and cradle, kickstand, arm mount and clamp, and the motor mounts.
   - The two longest reprints: the mast and the base plate.
   - Small parts with a weak spot: the IMU pedestal and clamp (at 40 % infill here) and the buck holder.
   - Set 4 walls and 40 % gyroid, plus a brim on `mast_spare`. Delete `base_plate_spare` to cut it to about 9 h.

**Plate 1, the test coupons, was skipped,** so the insert holes stay Ø4.0 × 5.5 mm, which suits the usual M3 inserts (4.5–5.0 mm across the knurl).

#### What changed from v2
**Printing**
- Every part prints without supports.
- Horizontal holes are teardrops, and underside pockets are narrow enough to bridge.
- Edges that touch the bed are chamfered.
- Every part has a debossed label on a hidden face, such as "BASE v3".
- Print hints (material, walls, infill, notes) travel with each part into the print sheet.

**Assembly**
- **Mast:** one piece, printed upright; the M3×45 splice bolt is gone. It drops onto a locating rim with a rear tab on the base, and its cable windows sit at the base and the shelf.
- **Shelf:** a tongue rides in the mast's rear groove, so it only fits one way.
- **Base underside:**
  - Tongues in the motor mounts and kickstand fit recesses in the base; L and R are offset so they can't swap.
  - A channel routes the motor cables to the mast, and a 12 V channel runs to the fuse.
  - Zip-tie anchors have flush grooves.
- **Battery:** a screwless cradle; the two straps hold both the cradle and the pack, and the pack comes out in seconds.
- **Phone head (replaces the pan-tilt):** keyed to the mast cap. The tilt is one M3×8 that is both pivot and friction lock (0–20°). Shims adapt it to your phone, and the bottom stays open for USB-C. A servo pan-tilt can bolt onto the same 4-hole cap pattern later.
- **Arm mount:** a 41.0 × 20.6 servo pocket (your measured 40.30–40.55 bodies), keyed to the rail. It comes off for travel with 2 clamp screws.

**Looks**
- Two-tone PETG Matte: a white body (base, mast, shelf, cradles) with baby-blue functional parts.
- R4–R5 vertical edges, 1 mm top fillets, recessed screw heads and rounded pockets.
- An evenly spaced rail of teardrop dimples on the mast doubles as the module rail.

**Integration (code)**
- Each part module declares its own screws and inserts. Lengths are limited to 6/8/10, and each must engage at least 3 mm in at least 1.5 mm of plastic.
- New automatic overhang/support check.
- Grouped STEP export.
- The phone pose is a contract in `params.py`.
- Rebuilds take 4 minutes instead of 28.

#### Checks (from `out/checks.json`)
| Check | Result |
|---|---|
| Interference, all 253 bodies | none |
| Support-free (`print_check`) | 22/22 parts, 0 FAIL (1 small-hole WARN: the phone cradle's pivot pin, which prints fine) |
| Bed fit, P2S 256³ | all parts; tallest is the mast at 240 mm |
| Screws | M3×6 ×34, M3×8 ×21; thread engagement 4.1–5.2 mm; no head or shank collisions |
| Inserts | 47, each with ≥ 1.5 mm of plastic around it |
| Wheel to mount / coupler to mount | 3.0 / 3.07 mm |
| Parked on kickstand / forward lean to first contact | 13.1° / 60.2° |
| Mass / center of mass | 2207 g at (4.7, −1.8, 125.3) mm, with PETG parts; body 93 mm above the axle; balances at 1.3° |
| Plates | 5 (plate 1, the coupons, is optional), all PETG Matte, each re-read and re-sliced by Bambu Studio in place |

#### Watch on the first prints and assembly
1. **Insert holes** stay Ø4.0 × 5.5 mm, since the coupons were skipped. Set inserts with the iron at about 245 °C, since PETG needs more heat than PLA. If one sinks with no pressure or spins, tell me.
2. **The mast is 240 mm tall:** give it a brim, which Bambu won't add on its own.
3. **Phone head:**
   - The cradle takes phones 70–81 mm wide and up to 13.5 mm thick. Stack the shims to fill the width: per side, none for 79–81 mm, 1.5 mm for 76–78, 3 mm for 73–75, and both for 70–72.
   - The tilt lock is friction only, with no hard stops.
   - One rubber band holds the phone.
   - The jaw lips overhang 2–3 mm; check them on the first print.
   - A long straight USB-C plug may rub at 20° of tilt, so a right-angle cable is better.
4. **Arm mount:** its two-hole pattern is symmetric, so it could go on upside down. The key pin catches it, but check that the servo pocket opens toward +X.
5. **Base and holders:**
   - The fuse holder is held by zip ties only.
   - The Wago frame has no inboard wall, so put VHB tape under the Wagos.
   - The buck end walls only touch a 66 mm board; shorter boards are held by the clip fingers alone.
   - The battery cradle takes packs up to 108 × 36 mm. The straps hold the pack, so a smaller one is fine.
6. **Shelf and boards:**
   - The boards were never measured, so the carrier standoffs follow listing guesses. If a board's holes don't line up, use the screws that do and stick the board onto the standoffs with double-sided foam tape.
   - The carrier screw heads stand 3 mm proud under the shelf; there's nothing below them.
   - Fit the left collar screw before the ESP32 carrier.
7. **Motor screws:** an M3×6 threads 4.2 mm into holes that are usually 4.5 mm deep. If one bottoms out before it's tight, use an M3×5. Use Loctite 242.

#### Not measured: best guesses with slack
You chose not to measure (Nov 10). These sizes are listing guesses, and each part that holds them has room to spare:
- **Phone:** the cradle takes phones 70–81 mm wide and up to 13.5 mm thick, in a case, with stacking shims (watch item 3).
- **Battery:** the cradle takes packs up to 108 × 36 mm; the OVONIC 3S 2200 is listed at about 105 × 34.
- **ESP32 terminal board and driver boards:** the standoffs follow guessed hole patterns, with foam tape as the fallback. If anyone measures later, only the carriers need reprinting (about 15 min each). The printed shelf's bays come from the same `ESP_*` / `DRV_*` values, so freeze them in `parts/shelf.py` first.
- **LM2596 buck:** the holder takes boards about 62–66 mm long.
- **GY-521:** the pocket takes boards up to 21.6 mm wide and is open at the front.
- **Inserts:** the holes stay Ø4.0 × 5.5 mm.
- **Wheels, couplers and motor shafts:** only the wheel-to-mount clearance depends on them (3.0 mm in the model).

#### Decisions
- **Kept from your prompt:** a fixed phone mount with a tilt hinge (no servo pan-tilt yet), with the screen and selfie camera facing forward, and the arm as a removable bolt-on module.
- **Made along the way:**
  - one-piece mast
  - board carriers
  - everything in PETG Matte, your only filament, in white and baby blue (your choice). Nothing needs PLA, and the motor mounts were PETG anyway.
  - test coupons skipped to print all night, so the insert holes stay at the default Ø4.0 mm
  - nothing measured (your call): listing guesses everywhere, with slack where it matters. That means a phone cradle for 70–81 mm phones with stacking shims, a battery cradle for packs up to 108 × 36 mm, and foam tape as the fallback for the boards.
  - the overnight plate packs the base, mast and shelf together, with a 5 mm bed margin instead of 8 mm
  - two screw lengths instead of three (nothing needed an M3×10 any more)

### 📄 `cad/out/guide/assembly-guide.md`

> **Last edited:** Nov 10. **Status:** Assembly guide from the CAD (Nov 10). Step images are in `assembly-guide.html` in the zip.

### Balancing robot: assembly guide

Generated 2026-11-10 17:32 from the CAD (`cad/assembly_guide.py`). Frame: +X is the robot's right, +Y forward (screen side), +Z up. Parts being added are in color and pulled out along their insertion direction; parts already assembled are pale gray.

#### Before you start

##### Print list

| Part | Qty | Color | Material | Infill | Walls | Filament | Time | Note |
|---|---:|---|---|---:|---:|---:|---:|---|
| arm_mount | 1 | baby blue | PETG | 40 % | 4 | 17 g | 0.9 h | Top face on the bed, pocket opening up, no supports. Print a fit coupon of the 41.0 x 20.6 pocket first if unsure. 2 inserts from below. |
| arm_mount_clamp | 1 | baby blue | PETG | 40 % | 4 | 2 g | 0.1 h | Bottom face on the bed, tongue up, no supports. |
| base_plate | 1 | white | PETG | 25 % | 3 | 56 g | 3.1 h | Bottom face on the bed (pockets bridge), no supports. 14 inserts after printing. |
| motor_mount_L | 1 | baby blue | PETG | 40 % | 4 | 13 g | 0.7 h | PETG: a NEMA 17 face runs 50-70 C at ~1.5 A, PLA creeps above ~55 C. Outer face on the bed, no supports (teardrop flange holes). Bolt to the base before fitting the motor. |
| motor_mount_R | 1 | baby blue | PETG | 40 % | 4 | 13 g | 0.7 h | PETG: a NEMA 17 face runs 50-70 C at ~1.5 A, PLA creeps above ~55 C. Outer face on the bed, no supports (teardrop flange holes). Bolt to the base before fitting the motor. |
| kickstand | 1 | baby blue | PETG | 40 % | 4 | 7 g | 0.4 h | On its rear face (flat 2D profile), no supports. Teardrop screw holes. |
| battery_cradle | 1 | white | PETG | 20 % | 3 | 4 g | 0.2 h | Bottom on the bed, no supports. Takes packs up to 108 x 36 mm (a 3S 2200 is ~105 x 34). |
| esp_carrier | 1 | baby blue | PETG | 30 % | 3 | 7 g | 0.4 h | Flat, bottom down, no supports. Inserts: 4 from the top, 2 from below. |
| driver_carrier_R | 1 | baby blue | PETG | 30 % | 3 | 4 g | 0.2 h | Driver board 0 (rear). Flat, bottom down, no supports. Inserts: 4 from the top, 2 from below. |
| driver_carrier_F | 1 | baby blue | PETG | 30 % | 3 | 4 g | 0.2 h | Driver board 1 (front). Flat, bottom down, no supports. Inserts: 4 from the top, 2 from below. |
| buck_holder | 1 | baby blue | PETG | 25 % | 3 | 6 g | 0.3 h | Floor on the bed, no supports. Clips take boards up to ~4 mm shorter than BUCK_L. |
| imu_pedestal | 1 | baby blue | PETG | 100 % | 4 | 17 g | 0.9 h | Upright, 100% infill (stiff IMU mount), no supports: shoulders are 45 deg. |
| imu_clamp | 1 | baby blue | PETG | 100 % | 3 | 1 g | 0.1 h | Flat, counterbores up. |
| mast | 1 | white | PETG | 20 % | 4 | 74 g | 4.1 h | Upright, flange on the bed, no supports. 240 mm tall: 5 mm brim, 0.2 mm layers; 4 walls make the 3 mm tube solid. 8 inserts after printing. |
| phone_mount_base | 1 | baby blue | PETG | 40 % | 4 | 9 g | 0.5 h | Front face on the bed (fins stand up, 45-deg flanks), no supports. 1 insert (right fin). |
| phone_mount_cradle | 1 | white | PETG | 20 % | 3 | 25 g | 1.4 h | Back face on the bed, no supports (2 mm lip overhangs). Takes phones up to 81 x 13.5 mm (in a case). Pin and clamp hole print as horizontal teardrops; test-fit the pin in the base slot. |
| phone_mount_shim_L | 1 | baby blue | PETG | 100 % | 2 | 1 g | 0.0 h | Flat, 1.5 mm. The shims stack: per side none for phones 79-81 mm wide, 1.5 for 76-78, 3 for 73-75, 1.5 + 3 for 70-72 (the thickest set the phone still slides into). |
| phone_mount_shim_R | 1 | baby blue | PETG | 100 % | 2 | 1 g | 0.0 h | Flat, 1.5 mm. The shims stack: per side none for phones 79-81 mm wide, 1.5 for 76-78, 3 for 73-75, 1.5 + 3 for 70-72 (the thickest set the phone still slides into). |
| phone_mount_shim3_L | 1 | white | PETG | 20 % | 3 | 1 g | 0.0 h | Flat, 3 mm. The shims stack: per side none for phones 79-81 mm wide, 1.5 for 76-78, 3 for 73-75, 1.5 + 3 for 70-72 (the thickest set the phone still slides into). |
| phone_mount_shim3_R | 1 | white | PETG | 20 % | 3 | 1 g | 0.0 h | Flat, 3 mm. The shims stack: per side none for phones 79-81 mm wide, 1.5 for 76-78, 3 for 73-75, 1.5 + 3 for 70-72 (the thickest set the phone still slides into). |
| electronics_shelf | 1 | white | PETG | 20 % | 3 | 62 g | 3.4 h | Flat, collar up, no supports. No inserts (the carriers carry them). |
| wago_frame | 1 | baby blue | PETG | 30 % | 3 | 2 g | 0.1 h | Bottom on the bed, no supports (the 1.2 mm lips are short ledges). |
| **Total** | 22 | | | | | **325 g** | **18.1 h** | estimates (PETG, ~18 g/h) |

##### Heat-set inserts to melt in

M3 heat-set inserts in Ø4.0 × 5.5 mm holes. Do all of them before assembly (step 1).

| Part | Hole opens on | Count | Sites |
|---|---|---:|---|
| arm_mount | bottom face (part upside down) | 2 | arm_boss |
| base_plate | bottom face (part upside down) | 6 | base_flange, base_kick |
| base_plate | top face | 8 | base_buck, base_mast, base_wago |
| driver_carrier_F | bottom face (part upside down) | 2 | carrier_mount |
| driver_carrier_F | top face | 4 | drv_standoff |
| driver_carrier_R | bottom face (part upside down) | 2 | carrier_mount |
| driver_carrier_R | top face | 4 | drv_standoff |
| esp_carrier | bottom face (part upside down) | 2 | carrier_mount |
| esp_carrier | top face | 4 | esp_standoff |
| imu_pedestal | bottom face (part upside down) | 2 | imu_ped_bottom |
| imu_pedestal | top face | 2 | imu_ped_top |
| mast | left side (-X) | 1 | rail_L156 |
| mast | right side (+X) | 3 | rail_R156, rail_R236, rail_R256 |
| mast | top face | 4 | mast_cap |
| phone_mount_base | right side (+X) | 1 | phone_hinge |
| **Total** | | **47** | |

##### Tools

- 2.5 mm hex key (every screw is M3 socket head; ball-end helps on the under-base screws)
- Soldering iron with a heat-set insert tip (about 245 °C for PETG)
- Flush cutters (zip-tie tails, print cleanup)
- Small flat screwdriver (screw terminals, buck trimpot), wire strippers, zip ties
- Multimeter to set the buck to 5.0 V (optional but recommended)

##### Fastener kit

| Item | Needed | Pack (with spares) |
|---|---:|---:|
| M3x6 socket head screw | 34 | 40 |
| M3x8 socket head screw | 21 | 25 |
| M3 heat-set insert | 47 | 55 |
| Zip ties (100 mm) | | 20 |
| Velcro straps 16 mm | 2 | 2 |

#### Steps

##### Step 1. Melt in all 47 heat-set inserts (bench)

_Image: step step_01 in `assembly-guide.html`_

**Fasteners:** 2x inserts: arm mount; 14x inserts: base plate; 6x inserts: ESP32 carrier; 6x inserts: driver carrier R; 6x inserts: driver carrier F; 4x inserts: IMU pedestal; 8x inserts: mast; 1x insert: phone mount base  

Base plate 14 (8 on top, 6 underneath), mast 8, each of the 3 board carriers 6, IMU pedestal 4, arm mount 2, phone mount base 1. Iron at about 245 °C (PETG): set each insert square on its hole, let it sink with light pressure until flush, hold the part flat while it cools.

- *parts/arm_mount.py, step 1:* Melt 2 inserts into the bosses under the side walls of arm_mount (from below).
- *parts/base.py, step 1:* Heat-set inserts: base top 4 mast + 2 buck holder + 2 Wago frame; base underside 4 motor flange + 2 kick. IMU pedestal: 2 bottom + 2 top.
- *parts/board_carriers.py, step 1:* Melt the inserts: 4 from the top into the standoffs, 2 from below into the mounting bosses (per carrier).
- *parts/mast.py, step 1:* Melt the 8 inserts in: 4 in the cap (from the top), 1 left + 1 right at z 156, 2 right at z 236 / 256.
- *parts/phone_mount.py, step 1:* Melt 1 insert into the right fin of phone_mount_base (from the outside, x+). The 4 cap inserts are the mast's.

##### Step 2. Motor mounts onto the base

_Image: step step_02 in `assembly-guide.html`_

**Parts:** base plate, motor mount L, motor mount R  
**Fasteners:** 4x M3x6 into inserts (base plate)  

Base upside down. Each mount's tongue goes into its underside recess (L and R are keyed), then 2x M3x6 up through the flange. Do this BEFORE the motors: the flange screws sit 1.35 mm above the motor top and can't be reached once a motor is on.

- *parts/base.py, step 2:* Motor mounts: tongue into the matching underside recess (R right, L left; the tongue only fits one way), 2 x M3x6 each up through the flange counterbores. Do this BEFORE the motors (they hide these screws).

##### Step 3. Kickstand

_Image: step step_03 in `assembly-guide.html`_

**Parts:** kickstand  
**Fasteners:** 2x M3x6 into inserts (base plate)  

Tongue into its rear recess, 2x M3x6 up through the flange counterbores.

- *parts/base.py, step 3:* Kickstand: tongue into the rear underside slot, 2 x M3x6 up through its flange counterbores.

##### Step 4. IMU pedestal, IMU and clamp

_Image: step step_04 in `assembly-guide.html`_

**Parts:** GY-521 IMU, IMU clamp, IMU pedestal  
**Fasteners:** 2x M3x8 into inserts (IMU pedestal); 2x M3x6 into inserts (IMU pedestal)  

Pedestal on its pin, 2x M3x8 up from under the base. GY-521 (with its Dupont jumpers) into the top pocket, then the clamp bar with 2x M3x6.

- *parts/base.py, step 4:* IMU pedestal on its pin, 2 x M3x8 up from under the base (counterbored); GY-521 into the top pocket, clamp bar on, 2 x M3x6 (see parts/imu_mount.py).

##### Step 5. Motors onto the mounts

_Image: step step_05 in `assembly-guide.html`_

**Parts:** NEMA 17 L, NEMA 17 R  
**Fasteners:** 8x M3x6 into the motors  

Pilot boss into the mount from the inside, 4x M3x6 per motor from the outside with Loctite 242. Motor cables along the underside channel, zip-tied, then up through the wire hole.

- *parts/base.py, step 5:* Fuse holder under the base front: 2 zip ties through the slot pairs (heads under the base, ties flush in the top grooves). Motors: pilot boss into the mount from inside, 4 x M3x6 each from the outside (Loctite 242). Motor cables up behind the motors, into the underside channel, zip tie, up through the wire hole.

##### Step 6. Fuse holder under the base front

_Image: step step_06 in `assembly-guide.html`_

**Parts:** fuse holder  

Zip-tie the inline fuse holder (15 A blade fuse) under the base front: tie heads under the base, ties flush in the top grooves.

##### Step 7. Mast onto the base

_Image: step step_07 in `assembly-guide.html`_

**Parts:** mast  
**Fasteners:** 4x M3x8 into inserts (base plate)  

Mast onto the locating rim (rear tab in the notch), bore over the base wire hole, 4x M3x8 down through the flange.

- *parts/base.py, step 6:* Mast on the locating rim (rear tab in the mast notch), 4 x M3x8 down (parts/mast.py).
- *parts/mast.py, step 2:* Stand the mast on the base, bore over the 14 mm base wire hole (rear notch over the base key, once the base has one), then 4 x M3x8 down through the flange bosses into the base inserts (hex key straight down).

##### Step 8. Buck holder and buck converter

_Image: step step_08 in `assembly-guide.html`_

**Parts:** buck converter, buck holder  
**Fasteners:** 2x M3x6 into inserts (base plate)  

Holder on its pin, 2x M3x6 (the heads end up under the board), then slide the buck in between the clip fingers, display forward. Set it to 5.0 V before anything is connected to its output.

- *parts/base.py, step 7:* Buck holder on its pin, 2 x M3x6 down, then slide the buck in from above (parts/buck_holder.py).

##### Step 9. Wago frame and Wagos

_Image: step step_09 in `assembly-guide.html`_

**Parts:** Wago, Wago frame  
**Fasteners:** 2x M3x6 into inserts (base plate)  

Frame on its pins, 2x M3x6, press the two Wagos in. Battery leads: black straight to the GND Wago; red down the slot, along the channel to the fuse, and back up to the +12 V Wago.

- *parts/base.py, step 8:* Wago frame on its 2 pins, 2 x M3x6 down, press the Wagos in (parts/wago_mount.py). Battery XT60 pigtail: black straight to the GND Wago; red down the pass-through slot, along the channel to the fuse; fused lead back along the channel and up the slot to the +12 V Wago.

##### Step 10. Battery cradle, straps and battery

_Image: step step_10 in `assembly-guide.html`_

**Parts:** 3S LiPo, battery cradle, velcro strap L, velcro strap R  

Cradle on its pins, velcro straps through the cradle and base slots, battery in, straps over it. It comes out again in under 30 s: open both straps, lift.

- *parts/base.py, step 9:* Battery cradle on its 2 pins, velcro straps through the cradle + base slots (parts/battery_cradle.py). Battery in, straps over it (out again in < 30 s: open both straps, lift).

##### Step 11. Electronics shelf

_Image: step step_11 in `assembly-guide.html`_

**Parts:** shelf  
**Fasteners:** 2x M3x8 into inserts (mast)  

Slide the shelf down from the top of the mast, tongue in the mast's rear groove, until it lands. 2x M3x8 through the collar pads. Do the left collar screw before the ESP32 carrier goes on.

- *parts/mast.py, step 3:* Shelf: slide it down from the top, tongue in the rear groove, until it lands; collar screws (parts/shelf.py).
- *parts/shelf.py, step 1:* With the mast bolted to the base (and the motor cables already out of the right upper window), slide the shelf down from the top of the mast, tongue in the rear groove, until it lands (collar bottom = z 146).
- *parts/shelf.py, step 2:* 2 x M3x8 through the collar pads into the mast inserts at z 156 (left + right; hex key along X, before the ESP32 carrier goes in on the left).

##### Step 12. Cables up the mast

_Image: step step_12 in `assembly-guide.html`_


No new parts. Motor cables up the bore and out of the RIGHT upper window; 12 V in at the right lower window; 5 V and the IMU leads in at the left lower window and out at the upper windows.

- *parts/mast.py, step 4:* Cables, after the shelf (a cable hanging out of a window would jam the collar): push both motor cables up the bore from under the base and pull them out of the RIGHT upper window; 12 V (right) and 5 V + IMU (left) go in at the lower side windows and out at the upper ones; the phone USB-C cable goes down the cap slot (or the rear window) and out of the LEFT upper window to the ESP32.

##### Step 13. Boards onto their carriers (bench)

_Image: step step_13 in `assembly-guide.html`_

**Parts:** ESP32 carrier, ESP32-S3 board, driver board, driver carrier F, driver carrier R  
**Fasteners:** 4x M3x6 into inserts (ESP32 carrier); 8x M3x6 into inserts (driver carriers)  

ESP32 terminal board onto esp_carrier, driver boards onto driver_carrier_R and _F, 4x M3x6 per board. ESP32 USB at the USB mark, driver motor connector at the arrow. Set the DIP switches and seat each TMC2209 the right way round first.

- *parts/board_carriers.py, step 2:* Screw the board on: 4 x M3x6 through the PCB corner holes (ESP32: USB end at the "USB" mark; driver boards: motor connector at the arrow). The boards were never measured: if the holes don't line up, use the screws that do and stick the board onto the standoffs with double-sided foam tape.

##### Step 14. Carriers into the shelf bays

_Image: step step_14 in `assembly-guide.html`_

**Parts:** ESP32 carrier, ESP32-S3 board, driver board, driver carrier F, driver carrier R  
**Fasteners:** 2x M3x8 into inserts (ESP32 carrier); 4x M3x8 into inserts (driver carriers)  

Drop each carrier into its bay over the pin, then 2x M3x8 up from under the shelf into it.

- *parts/board_carriers.py, step 3:* Drop the carrier into its bay over the pin, then 2 x M3x8 up from under the shelf into the carrier.
- *parts/shelf.py, step 3:* Route the cables through the mast (parts/mast.py step 4), then the carriers (parts/board_carriers.py): drop each into its bay over the pin, 2 x M3x8 up from below.

##### Step 15. Arm mount on the right rail

_Image: step step_15 in `assembly-guide.html`_

**Parts:** arm mount  
**Fasteners:** 2x M3x6 into inserts (mast)  

Key pin into the rail dimple, 2x M3x6 into the rail inserts. Before the servo: the heads end up behind it.

- *parts/arm_mount.py, step 2:* Hold arm_mount on the mast's right face, key pin in the rail dimple at z 216, and drive 2 x M3x6 into the rail inserts at z 236 / 256 (hex key along -X, through the empty pocket: do this BEFORE the servo goes in).
- *parts/mast.py, step 5:* Arm mount on the right rail, phone mount on the cap (their modules).

##### Step 16. Shoulder servo and clamp

_Image: step step_16 in `assembly-guide.html`_

**Parts:** arm clamp, shoulder servo  
**Fasteners:** 2x M3x8 into inserts (arm mount)  

Slide the shoulder servo (arm attached) in from +X, push it up against the top wall, then the clamp from below with 2x M3x8.

- *parts/arm_mount.py, step 3:* Slide the shoulder servo (horn already on, femur attached) into the pocket from +X, cable out of the open bottom, rear support shaft against the back plate.
- *parts/arm_mount.py, step 4:* Push the servo up against the top wall, fit arm_mount_clamp from below (tongue into the pocket) and drive 2 x M3x8 up into the boss inserts (hex key from below, above the driver boards). Travel: remove the 2 clamp screws and slide the servo (with the whole arm) out along +X; the mount stays on.

##### Step 17. Phone mount base on the mast cap

_Image: step step_17 in `assembly-guide.html`_

**Parts:** phone mount base  
**Fasteners:** 4x M3x8 into inserts (mast)  

Tongue in the mast's rear groove, 4x M3x8 down into the cap inserts. USB-C cable down the cap slot (or along the groove and rear tab to the rear window), out of the left upper window.

- *parts/phone_mount.py, step 2:* Set the base on the mast cap, rear tongue in the mast's rear key groove (it only fits facing forward), skirt over the cap. 4 x M3x8 straight down into the cap inserts (hex key from above, the cradle is not on yet).
- *parts/phone_mount.py, step 3:* Feed the USB-C cable: down the base slot into the mast, or back along the groove to the rear tab (zip tie through the slot pair), then down to the mast's rear window.

##### Step 18. Cradle, tilt hinge and shims

_Image: step step_18 in `assembly-guide.html`_

**Parts:** phone cradle, shim L, shim R  
**Fasteners:** 1x M3x8 into inserts (phone mount base)  

Cradle over the fins, left pin in its slot, M3x8 through the right knuckle into the fin insert. Set the tilt (0-20°) and tighten. Shims into the jaws.

- *parts/phone_mount.py, step 4:* Lower the cradle over the fins: left pin into the left fin's open slot, right knuckle outside the right fin.
- *parts/phone_mount.py, step 5:* M3x8 through the right knuckle into the fin insert (hex key from the right, along X). Tilt the cradle to the wanted angle (0-20 deg back) and tighten: it clamps the knuckle to the fin.

##### Step 19. Phone

_Image: step step_19 in `assembly-guide.html`_

**Parts:** phone  

Phone in, screen forward, plug in the cable from below, then a rubber band through the jaw notches and around the back plate.

- *parts/phone_mount.py, step 6:* Drop the shims into the jaw channels (on the ledge): the thickest set the phone still slides between (see the shims above). Slide the phone down between them, screen forward, plug the cable in from below, then stretch one rubber band through both jaw-top notches, round the jaws and behind the back plate.

##### Step 20. Wheels

_Image: step step_20 in `assembly-guide.html`_

**Parts:** clamping hub L, clamping hub R, wheel L, wheel R  

Clamping hub onto each D-shaft (set screw on the flat), wheel on, at the 3 mm gap to the motor mount. Both wheels must spin freely.

- *parts/base.py, step 10:* Couplers + wheels last (they cover the motor screws); set the 3 mm gap (WHEEL_GAP) when clamping.

##### Step 21. Remaining parts

_Image: step step_21 in `assembly-guide.html`_

**Parts:** shim L, shim R  

Parts or screws that no row in assembly_guide.STEPS covers yet: add a row for them.

#### Wiring

Thick wires carry 12 V from the battery; jumpers carry signals. All grounds meet at the GND Wago. Set the buck to 5.0 V before the ESP32 is connected. Pin numbers follow `build-guide.md`.

| From | To | Wire | Note |
|---|---|---|---|
| Battery XT60 + | Fuse holder (15 A blade) | 14 AWG pigtail, red | unplug the XT60 = off switch |
| Fuse holder out | Wago +12 V (front) | 14 AWG, red |  |
| Battery XT60 - | Wago GND (rear) | 14 AWG pigtail, black | every ground meets here |
| Wago +12 V / GND | Driver board L: VM+ / GND | 14-18 AWG pair | 12 V motor supply |
| Wago +12 V / GND | Driver board R: VM+ / GND | 14-18 AWG pair | 12 V motor supply |
| Wago +12 V / GND | Buck IN+ / IN- | 18-22 AWG pair |  |
| Buck OUT+ / OUT- | ESP32 5V / GND terminals | 22 AWG pair | set the buck to 5.0 V BEFORE connecting |
| MPU-6050 VCC / GND | ESP32 3V3 / GND | Dupont jumpers | I2C bus power |
| MPU-6050 SDA / SCL | ESP32 GPIO 8 / GPIO 9 | Dupont jumpers | I2C |
| ESP32 GPIO 4 / 5 | Driver L STEP / DIR | Dupont jumpers |  |
| ESP32 GPIO 6 / 7 | Driver R STEP / DIR | Dupont jumpers |  |
| ESP32 GPIO 15 | EN on both drivers | Dupont jumpers | LOW = motors on |
| NEMA 17 L / R (4-pin) | Driver L / R motor connector | motor cable, up inside the mast |  |
| Phone USB-C | down the back of the mast | USB-C cable | power only; video goes to the laptop over Wi-Fi |

---

## C. Team workflow

### 📄 `team.md`

> **Last edited:** Nov 09. **Status:** Team file (Nov 9). Roles are now as in Part 1, section 1.2.

### Team — HackPrinceton Fall 2026

_Stub, created Nov 9, 2026. Fill in once John shares teammate details._

#### Members

| Name | School / year | Role | Owns directory | Skills | GitHub | Contact | Has Claude Code? |
|---|---|---|---|---|---|---|---|
| John Huang | UC Berkeley | _TBD_ | _TBD_ | robotics (hexapod project) | JohnHuang16 | _(his own)_ | Yes |
| Grant Ji Kim | _?_ | | | | | | |
| Jialang Zhao | _?_ | | | | | | |
| _Teammate 4_ | | | | | | | |

#### Role slots (see `team-setup/template-repo/CLAUDE.md`)

| Role | Owns | Responsibilities |
|---|---|---|
| Integrator / lead | `main`, CI, `/shared`, demo path | Creates the repo, merges, keeps `main` demoable, owns the demo |
| Frontend | `/frontend` | UI, demo flow, visuals |
| Backend / API | `/backend` | Server, data, deployment |
| AI / data | `/ai` | Models, prompts, data pipeline |

**Robot plan roles** (`robot-plan.md`): Mech/CAD (`/hardware`), Controls/firmware (`/firmware`, suggested John), Robot software + Integrator (`/robot`), Vision/AI + pitch (`/vision`). Team skills so far: CAD, Python, some Claude/OpenCV. Budget $200–500. Owned: servos, Bambu P2S, soldering kits, screws, 6804-2RS bearings.

Roles get swapped based on skills. Hardware hack? Repurpose one slot as Hardware (`/hardware`).

#### Decisions

- Rules (per John, Nov 9): hardware pre-build is OK, and testing the software stack at home is allowed. Source not yet saved here. Keep a screenshot of the organizer reply and disclose pre-event work on Devpost.
- Parts ordered Nov 9 (Amazon, pickup at ASUC Tue Nov 10). See shopping-list.md.
- Team repo: _not created yet_ (John creates it; agent doesn't push without OK).
- Idea: John proposed a modular self-balancing robot (hoverboard base, extrusion mast, IMU, camera), Nov 9. Not locked; see `ideas.md` (top pitch: #2 follow-me & fetch care robot).
- Coordination: `TASKS.md` + `MESSAGES.md` in the repo; optional team bus only if time.

#### Open questions

- 4th teammate's name. Schools, skills, preferred roles and GitHub handles for all three.
- Does the team already have an idea, or a track/sponsor prize they want?
- Is everyone flying in? Who arrives when?

### 📄 `team-setup/README.md`

> **Last edited:** Nov 09. **Status:** Team kit overview.

### HackPrinceton Team-Setup Kit

A generic, project-agnostic starter kit for a 4-person team where each person runs their own Claude Code. It has process docs and templates only (placeholders like `<PROJECT>` and `<NAME>`). There is no product code, so it is safe to prepare before the hacking period starts. Check the hacker packet's rules on pre-written code and AI tools anyway.

#### What's here

```
team-setup/
├── README.md               this file
├── first-hour-plan.md      hour 0-1 minute by minute + 36-hour timeline by role
├── kickoff-prompts.md      copy-paste prompts for each teammate's Claude
├── optional-team-bus.md    OPTIONAL upgrade: hook that auto-shows new messages
└── template-repo/          copy into the team repo at kickoff
    ├── CLAUDE.md           the rules every Claude reads (roles, ownership, ritual)
    ├── TASKS.md            task board
    ├── MESSAGES.md         append-only team log
    ├── DEMO.md             demo script + Devpost skeleton
    ├── .gitignore  .gitattributes  .env.example
    └── shared/contracts/   contract rules, example contract, example fixture
```

#### How to use it at kickoff

1. **0:00-0:45:** follow `first-hour-plan.md`: lock the idea, assign roles, draft contracts v0.
2. **Integrator** creates the team repo (John approves creating it and inviting teammates), then:
   ```bash
   cp -R team-setup/template-repo/. <team-repo>/    # the trailing /. copies dotfiles too
   cd <team-repo>
   mkdir -p frontend backend ai && touch frontend/.gitkeep backend/.gitkeep ai/.gitkeep
   # fill in the <PLACEHOLDERS> in CLAUDE.md (one-liner, team table)
   # move the v0 contract into shared/contracts/, rename the example files
   git add -A && git commit -m "chore: team scaffold + contracts v0" && git push
   ```
3. **Everyone** clones, runs `cp .env.example .env`, pastes their own keys into `.env` (never Claude), and gives their Claude the matching prompt from `kickoff-prompts.md`.
4. If there's spare time after the MVP, look at `optional-team-bus.md`. Otherwise skip it.

#### Coordination model

The repo is the team's shared brain. Each person's Claude starts every session by running `git pull` and reading `CLAUDE.md` (the rules), `TASKS.md` (who is doing what) and `MESSAGES.md` (what changed and who is blocked). Each person owns one directory and edits only that one, so four people can work in parallel with few merge conflicts. The only shared surface is `/shared/contracts`: the API and data shapes agreed in hour 1, so everyone can build against mock fixtures before the real services exist. One integrator owns `main`, CI and the demo path, and merges small PRs. Contract changes go through a proposal in `MESSAGES.md`. Claudes don't talk to each other directly; they talk through committed files. This is simple, easy to inspect, and works offline.

#### Rules check (from research, Nov 9)
Past HackPrinceton rules required the public repo to be **created during the event** and ≥85% of code written during it. So:
- Don't create the team repo before hacking starts (Fri Nov 13). Keep this kit local until then.
- At kickoff, generate app boilerplate fresh with the official CLIs (`npm create vite`, etc.), then add this kit's coordination files in **one clearly labelled commit** (`chore: add team coordination templates (prepared pre-event, no project code)`).
- Disclose AI-tool use in the Devpost write-up (wording in `template-repo/DEMO.md`).

### 📄 `team-setup/first-hour-plan.md`

> **Last edited:** Nov 09. **Status:** First hour of hacking: repo, contracts, mock.

### First-Hour Plan + 36-Hour Timeline

`T+0` = hacking starts. Fill in real clock times from the hacker packet: start `<FRI HH:MM>`, deadline `<SUN HH:MM>`.
Roles: **INT** = Integrator/lead, **FE** = Frontend, **BE** = Backend/API, **AI** = AI/data.

#### Hour 0-1, minute by minute

| Time | Goal | INT | FE | BE | AI |
|---|---|---|---|---|---|
| **0:00-0:10** Idea lock | Pick 1 idea from the shortlist and write the one-liner + the 3-step demo path | Runs a timer, forces a decision by 0:10 | Sketches the 2-3 screens the demo needs | Lists the entities + endpoints the demo needs | Confirms the model/API/data is available and fast enough (5-min check) |
| **0:10-0:25** Roles + ownership | Fill the team table in `CLAUDE.md`, choose the stack, assign directories | Writes the team table + stack; picks target tracks/prizes | Confirms FE stack + `/frontend` | Confirms BE stack + `/backend` | Confirms AI approach + `/ai`; flags any sponsor API to sign up for (John approves sign-ups) |
| **0:25-0:45** Contracts v0 + mocks | Write `shared/contracts/api.md` + at least 1 fixture per endpoint | Leads it on a shared screen and writes the file | Defines the response shapes the UI needs | Defines endpoints, request bodies, errors | Defines the `analyze()`-style function signature + a mock output |
| **0:45-0:60** Repo live | Repo created, everyone cloned, Claudes briefed, first tasks claimed | Creates the repo (John OKs), copies `template-repo/`, commits contracts v0, pushes, invites the team | Clones, `.env`, kickoff prompt, claims "App shell renders fixtures" | Clones, `.env`, kickoff prompt, claims "Stub routes serve fixtures" | Clones, `.env`, kickoff prompt, claims "AI stub returns mock output" |

**Exit criteria at T+1:** one-liner written · team table filled · contracts v0 + fixtures on `main` · 4 tasks *In progress* in `TASKS.md` · everyone can run their own area locally.

#### 36-hour timeline

| When | Checkpoint | INT | FE | BE | AI |
|---|---|---|---|---|---|
| T+1-T+3 | Each area runs against mocks | CI (build + smoke), run script, review first PRs | Shell + main screen from fixtures | Stub routes return fixtures, `/health` | Mock function + first real-model prototype in a notebook/script |
| **T+6** | **End-to-end skeleton:** UI → API → AI → UI on one thin path. Tag `contracts-v1` | Wires it together and fixes integration bugs | Calls the real API behind `USE_MOCKS` | First real endpoint replacing a stub | Real call behind the interface, with a timeout |
| T+6-T+12 | Core feature works on the happy path | Merges, keeps `main` green, starts the demo script | Core screen interactive | Persistence + seed data | Quality pass on the core output; caches responses |
| **Night 1** | Sleep shifts, about 4 h each | Pair B (INT + BE) sleeps ~T+10-T+14 | Pair A (FE + AI) sleeps ~T+6-T+10 | | |
| **T+18** | **MVP:** full demo path works end to end on `main`. Demo script drafted | Runs demo path dry-run #0, cuts scope | Fills empty/loading/error states | Error handling, deploy | Demo-path inputs that look great |
| T+18-T+28 | Polish + 1 stretch feature + sponsor-prize integrations | Decides what's stretch (P1/P2) vs cut | UI polish, responsive | Stability, deploy URL | Stretch AI feature *or* robustness |
| **Night 2** | Short sleep shifts, ~2.5 h each, all done by T−4 | Pair A ~T+26-T+28.5 · Pair B ~T+28.5-T+31 | | | |
| **T−6** | Stop starting new features | Freezes the backlog | Finishes in-flight work | Finishes in-flight work | Finishes in-flight work |
| **T−4** | Demo dry-run #1 (timed, full pitch) | Runs it, logs bugs as P0 tasks | Fixes P0 UI bugs | Fixes P0 API bugs | Fixes P0 AI bugs |
| **T−3** | **Feature freeze.** Only demo-path bug fixes, each merge OK'd by INT. Tag `demo-v1` | Guards `main` | Screenshots for Devpost | Seed/reset script, offline mode verified | Cached responses for offline mode |
| **T−2** | Devpost draft complete + backup video recorded | Records the video | Writes "What it does" | Writes "How we built it" (backend) | Writes "How we built it" (AI) + "Challenges" |
| T−1.5 | Demo dry-run #2 | Runs it | Drives | Watches logs | Speaker rehearsal |
| **T−1** | **Submit on Devpost** (it can be edited until the deadline) | Submits (John OKs before anything is posted), checks links | Checks the video link plays | Checks the repo is public if required | Checks the tracks/prizes are selected |
| T−0 → judging | Expo / judging | Speaker or driver | Driver | Backup laptop + hotspot | Q&A on tech |

**Rules of thumb:** If something isn't on the demo path by T+18, it's P2. Never more than one person debugging the same bug; post a `BLOCKED` instead. Keep at least one person awake who can fix `main`.

### 📄 `team-setup/kickoff-prompts.md`

> **Last edited:** Nov 09. **Status:** Per-role kickoff prompts (generic role names; map them to 1.2).

### Kickoff Prompts

Paste one into your own Claude Code, started in the team repo root. First fill in `<NAME>` and the other placeholders. Use the generic prompt plus your role prompt at kickoff. Use the resume prompt after every break or new session.

#### Generic (everyone, first session)

```
You're on a 4-person hackathon team. I'm <NAME>. Each teammate runs their own Claude, and we coordinate only through this repo.
1. Run `git pull --rebase`. Then read CLAUDE.md, TASKS.md, MESSAGES.md and shared/contracts/ fully.
2. Summarize in 5 lines or fewer: the project one-liner, my role and directory, the contract shapes I depend on, and any ASK addressed to me.
3. Follow CLAUDE.md's session-start ritual and rules exactly: only edit my directory, build against fixtures until real services exist, small branches, area-prefixed commits.
4. Never type, print or commit API keys. If one is needed, add its name to .env.example and tell me to paste the value into .env.
5. Propose the next task to claim from TASKS.md. Wait for my OK before claiming it.
```

#### Integrator / lead

```
I'm the Integrator. I own main, CI, /shared, /scripts, the root files and the demo path.
Your jobs: (1) keep main green: review and merge small PRs, and after each merge run the demo path or smoke test; (2) own /shared/contracts: apply CONTRACT-CHANGE proposals only after the affected owners ack, and update the fixtures in the same commit; (3) set up minimal CI (install, build, smoke test) and a one-command run script; (4) keep TASKS.md accurate and flag scope cuts. Before you merge anything, tell me what it changes. Ask me before pushing to the shared repo, inviting anyone, or posting outside the repo.
```

#### Frontend

```
I'm the Frontend owner. Only edit /frontend.
Build the UI against shared/contracts/fixtures/ behind a USE_MOCKS flag. Switch to the real API endpoint by endpoint as BE posts FYIs. Match the contract types exactly. If the UI needs a new field, draft a CONTRACT-CHANGE line in MESSAGES.md instead of inventing it. Prioritize the demo-path screens, and empty, loading and error states. Skip anything off the demo path until the MVP works.
```

#### Backend / API

```
I'm the Backend/API owner. Only edit /backend.
First, stub every endpoint in shared/contracts/ so it returns the matching fixture. Then replace stubs with real logic one route at a time, keeping responses identical in shape (diff them against the fixtures). Errors use the contract's ApiError shape. Call the AI module only through its documented interface, with a timeout and a mock fallback. Add a seed/reset script for demo data. Post an FYI in MESSAGES.md each time a real endpoint goes live.
```

#### AI / data

```
I'm the AI/data owner. Only edit /ai.
Expose exactly the function interface in shared/contracts/. First, make a mock version that returns fixture-shaped output instantly. Then the real model or API call, with a timeout, retries kept to a minimum, and a cache so demo inputs return instantly and work offline. Read API keys from env vars only. Prefer a simple, reliable approach that looks great on the demo inputs over a clever one. Post an FYI when the real version is live and say its typical latency.
```

#### Resume (after any break or new session)

```
Re-run the session-start ritual from CLAUDE.md: git pull, read TASKS.md and only the NEW lines of MESSAGES.md since my last message. Tell me in 3 bullets or fewer: what changed, anything addressed to me, and whether my in-progress task is still valid. Then continue.
```

#### Wrap-up (before you stop or sleep)

```
Before I step away: commit and push my work (on my branch, or open a PR if it's done), update my row in TASKS.md, and append one MESSAGES.md FYI with what's done, what's half-done, and where. Nothing left uncommitted.
```

### 📄 `team-setup/template-repo/CLAUDE.md`

> **Last edited:** Nov 09. **Status:** Template for the repo's CLAUDE.md.

### <PROJECT> — Team CLAUDE.md

> Every teammate's Claude reads this file first. It is the team's rulebook. Only the Integrator edits it (others propose changes in MESSAGES.md).

**One-liner:** <PROJECT> helps <WHO> do <WHAT> by <HOW>.
**Demo path (the one flow we demo):** <STEP 1> → <STEP 2> → <STEP 3>
**Hacking window:** <START DAY/TIME> to <SUBMIT DEADLINE>. Feature freeze: <DEADLINE − 3h>.

#### Team

| Name | Role | Owns directory | GitHub | Contact |
|---|---|---|---|---|
| `<NAME>` | Integrator / lead | `main`, CI, `/shared`, `/scripts`, root files, demo path | `@<handle>` | `<phone/Discord>` |
| `<NAME>` | Frontend | `/frontend` | `@<handle>` | `<...>` |
| `<NAME>` | Backend / API | `/backend` | `@<handle>` | `<...>` |
| `<NAME>` | AI / data | `/ai` | `@<handle>` | `<...>` |

Roles can be swapped based on skills. Change the table, not the rules. If the project has no AI part, the 4th slot becomes a second frontend or backend owner with its own subdirectory.

**Stack:** frontend `<e.g. React/Vite>` · backend `<e.g. FastAPI/Express>` · AI `<model/API>` · hosting `<...>`

#### Directory ownership

- **Only edit files in the directory you own.** To change someone else's area, post an `ASK` in `MESSAGES.md` or ask them directly.
- **`/shared/contracts`** is owned by the Integrator. To change it: post a `CONTRACT-CHANGE` in `MESSAGES.md` → the affected owners ack → the Integrator commits it (see `shared/contracts/README.md`).
- **Root files** (`CLAUDE.md`, CI, `.gitignore`, `DEMO.md`) belong to the Integrator. Anyone may append to `TASKS.md` and `MESSAGES.md`.
- If you must touch another area to unblock yourself, keep it tiny, say so in `MESSAGES.md`, and tag the owner.

#### Session-start ritual (every Claude, every session, no exceptions)

1. `git pull --rebase` on `main`.
2. Read `TASKS.md` and the **new** lines in `MESSAGES.md`. Answer any `ASK` addressed to you first.
3. **Claim a task:** move it to *In progress* with your name, then commit and push right away (`chore: claim <task>`) so nobody else takes it.
4. Work on a **short-lived branch**: `<area>/<short-task>` (for example `fe/item-list`). Aim for under 2 hours per branch.
5. **Small PRs** to `main`. The Integrator merges. The Integrator may allow self-merge for PRs that only touch your own directory once CI is green.
6. When done: move the task to *Done* in `TASKS.md`. Post in `MESSAGES.md` if you **changed an interface**, are **blocked**, or finished something others are waiting on.

`TASKS.md` and `MESSAGES.md` edits can be committed straight to `main` (pull first, keep commits tiny). All code goes through a branch.

#### Conventions

- **Commit prefix by area:** `fe:` `be:` `ai:` `shared:` `infra:` `docs:` `chore:`. For example `be: add GET /items stub`.
- Commit small and often. Push at least every hour. Unpushed work doesn't exist.
- Don't reformat or rename files you don't own.
- `MESSAGES.md` auto-merges (keeps both sides' lines, see `.gitattributes`). If `git pull` conflicts on `TASKS.md`: resolve by hand, so each task appears exactly once in its newest section, and never delete other people's rows.

#### Secrets

- Keys live **only** in the local `.env`. `.env` is in `.gitignore`. `.env.example` is committed with **names only, blank values**.
- **Claude never types, prints, or commits keys.** If a key is needed, add its name to `.env.example` and ask the human to paste the value into `.env`.
- Before every commit, check `git diff --staged` for anything that looks like a key. If a key gets pushed, tell the Integrator, rotate the key, and don't just delete the line.

#### Build against mocks

- Until a real service lands, build against the fixtures in `shared/contracts/fixtures/`. The frontend loads the fixture JSON, and the backend can return fixtures from stub routes.
- Use a single flag such as `USE_MOCKS=true` in `.env` to switch between mock and real. Keep the mock path working all hackathon, because it is the offline backup for the demo.

#### Demo path is sacred

- **Never break `main`.** If `main` breaks, fixing it beats everything else. Whoever broke it reverts first and debugs second.
- The Integrator runs the demo path after every merge (or CI does).
- **Feature freeze at deadline − 3h:** after that, only bug fixes on the demo path, and each merge needs the Integrator's OK. Then rehearse, record the backup video, and finish the Devpost write-up (`DEMO.md`).
- Follow the event rules, including the rules on AI-tool use. We disclose AI-tool use in the Devpost write-up.

### 📄 `team-setup/template-repo/TASKS.md`

> **Last edited:** Nov 09. **Status:** Template.

### TASKS

Rules: one owner per task. Claim before starting (move it to *In progress* with `@name`, then commit and push). Keep tasks small, 2 hours or less; split anything bigger. Tag: `[fe] [be] [ai] [shared] [infra] [demo]`. P0 = needed for the demo path, P1 = nice to have, P2 = stretch.

#### Backlog
| # | Task | Area | Pri | Notes |
|---|---|---|---|---|
| 3 | Mock server / stub routes that serve contract fixtures | be | P0 | lets fe build against the API shape right away |
| 4 | App shell + page that renders fixture data | fe | P0 | |
| 5 | AI/data stub: function returning fixture-shaped output | ai | P0 | swap for the real model later |
| 6 | CI: install + build + smoke test on PR | infra | P1 | |
| 7 | Demo script draft (`DEMO.md`) | demo | P0 | by T+18 |
| 8 | Devpost draft (`DEMO.md` skeleton) | demo | P0 | by T−2h |
| 9 | Seed / demo data | be | P0 | |

#### In progress
| # | Task | Owner | Branch | Started |
|---|---|---|---|---|
| 1 | Write contracts v0 (`shared/contracts/`) | @<integrator> | main | <HH:MM> |

#### Blocked
| # | Task | Owner | Blocked on | Since |
|---|---|---|---|---|
| | | | | |

#### Done
| # | Task | Owner | Done at |
|---|---|---|---|
| 2 | Repo scaffold from team-setup kit | @<integrator> | <HH:MM> |

### 📄 `team-setup/template-repo/MESSAGES.md`

> **Last edited:** Nov 09. **Status:** Template.

### MESSAGES

Append-only team log. Every Claude reads the new lines at session start.

**Format:** `[HH:MM] @from → @to | TYPE | message`

| Type | Use when | Reply expected? |
|---|---|---|
| `FYI` | something landed or changed, no action needed | no |
| `ASK` | you need an answer or action from `@to` | yes, `@to` replies with `re [HH:MM]` |
| `BLOCKED` | you can't continue; say on what | yes, the owner or Integrator replies ASAP |
| `CONTRACT-CHANGE` | proposing a change to `/shared/contracts` | the affected owners ack, then the Integrator commits |

**Rules**
- Newest at the **bottom**. Never edit or delete earlier lines. Correct something with a new line.
- Keep each message to one line. Put details in a PR, issue, or file and link it.
- Resolve an `ASK` by replying with `re [HH:MM]` and the original time. `@all` means everyone.
- Pull before appending. On a merge conflict, keep both sides' lines.
- For anything urgent (main broken, demo in 10 min), say it out loud too. This log isn't a pager.

---

[00:00] @<integrator> → @all | FYI | Repo is up. Read CLAUDE.md, claim a task in TASKS.md.
[00:05] @<frontend> → @<backend> | ASK | Does GET /items paginate in v0?
[00:07] @<backend> → @<frontend> | FYI | re [00:05] No pagination in v0. Returns the full list.
[00:40] @<ai> → @all | CONTRACT-CHANGE | Proposal: add optional `score: number` to Item (v0 → v0.1, additive). Ack?
[00:42] @<frontend> → @<ai> | FYI | re [00:40] ack
[03:10] @<frontend> → @<backend> | BLOCKED | POST /items returns 500 on the empty body in fixture create.v0.json

### 📄 `team-setup/template-repo/DEMO.md`

> **Last edited:** Nov 09. **Status:** Template for the demo path.

### DEMO — <PROJECT>

Owner: @<integrator> (everyone contributes). Draft by T+18, final by T−2h.

#### Pitch structure

**90 seconds (expo table / quick judge pass)**
| Time | Beat | Content |
|---|---|---|
| 0:00-0:15 | Hook + problem | `<one painful, concrete situation>` |
| 0:15-0:25 | One-liner | "<PROJECT> helps <WHO> do <WHAT> by <HOW>." |
| 0:25-1:10 | Live demo | Demo path steps 1-3, nothing else |
| 1:10-1:25 | How it works | 1 sentence on the stack + the most interesting technical part |
| 1:25-1:30 | Close | Track or sponsor fit + what's next |

**3 minutes (stage / finalist)**
| Time | Beat |
|---|---|
| 0:00-0:30 | Problem: who hurts, how much, why now |
| 0:30-0:45 | One-liner + what we built |
| 0:45-2:00 | Live demo (demo path, narrated by one person, one person drives) |
| 2:00-2:30 | How we built it: architecture, sponsor tech used, hardest problem solved |
| 2:30-2:50 | Impact + what's next |
| 2:50-3:00 | Team + thank you. Leave time for Q&A |

Speaker: `<NAME>` · Driver (hands on keyboard): `<NAME>` · Q&A on tech: `<NAME>`

#### Demo path

| # | Action (driver) | What the judge sees | Says (speaker) | If it fails |
|---|---|---|---|---|
| 1 | `<open app at URL>` | `<landing screen>` | `<line>` | switch to mock mode |
| 2 | `<do the core action>` | `<result>` | `<line>` | show seeded result |
| 3 | `<the wow moment>` | `<result>` | `<line>` | play backup video at mm:ss |

**Pre-demo checklist:** laptop charged · notifications off · browser zoom set, extra tabs closed · logged in · seed data loaded · `.env` correct · phone hotspot ready · backup video on the desktop.

#### Backup plan
1. **Recorded video** (made at T−2h): a 60-90 s screen recording of the full demo path, saved locally **and** uploaded unlisted.
2. **Seeded data:** `<command/script>` resets the demo to a known-good state in under 30 s.
3. **Offline mode:** `USE_MOCKS=true` serves fixtures and cached AI responses, so the demo works with no Wi-Fi or API.
4. **Screenshots** of each demo step in `/docs/screens/` as a last resort.

---

#### Devpost write-up skeleton

**Project name:** <PROJECT> · **Tagline (≤60 chars):** <...>
**Tracks / prizes submitted to:** <track>, <sponsor prize>

##### Inspiration
<The problem and why we cared. 2-3 sentences.>

##### What it does
<What the user does and what they get. Mirror the demo path.>

##### How we built it
<Stack per layer: frontend, backend, AI/data, hosting. Sponsor APIs used and how. Architecture diagram link.>

##### Challenges we ran into
<1-3 real technical problems and how we solved them.>

##### Accomplishments that we're proud of
<...>

##### What we learned
<...>

##### What's next for <PROJECT>
<2-3 concrete next steps.>

##### Built with
`<language>` `<framework>` `<db>` `<model/API>` `<sponsor tech>` `<hosting>`

**AI-tool disclosure:** We used <Claude Code / other tools> for <code generation, debugging, writing help>, in line with HackPrinceton's rules. All code was written during the hacking period. <Adjust to match the event's required wording.>

**Links:** Repo <URL> · Demo video <URL> · Live app <URL> · Slides <URL>

### 📄 `team-setup/cv-practice-prompt.md`

> **Last edited:** Nov 11. **Status:** CV practice prompt (phone → OpenCV → follow-me).

### CV practice prompt

_Nov 11, 2026. For teammates to paste into their own Claude (Claude Code or claude.ai) to work on the iPhone → OpenCV/MediaPipe stack as personal project work. It follows `robot-plan.md`: the phone streams to the laptop, and the laptop sends `{v, w}` JSON to the ESP32._

```
I'm working with friends on a small self-balancing robot with an iPhone on its mast as the camera. I want to get the computer-vision side working on my laptop with my iPhone. Take me through the phases below in order, one at a time. Finish a phase, show me the result, and wait for my OK before starting the next. If you can run commands on my computer, do the steps yourself; if not, give me exact commands to paste. Briefly explain the less obvious ideas (latency, smoothing, frame size) as we go: I want to understand this, not just collect code.

How the full system works (build against this so it plugs in later):
- The iPhone on the mast streams video to a laptop. The laptop runs OpenCV + MediaPipe and sends drive commands to the robot's ESP32 over Wi-Fi at 20–50 Hz, as newline-delimited JSON over UDP: {"t":"cmd","v":0.3,"w":0.0,"mode":"drive"} (v = forward speed in m/s, w = turn rate in rad/s; modes idle|balance|drive|kickstand).
- The ESP32 sends telemetry back: {"t":"tel","pitch":1.2,"rate":-0.4,"vl":0.28,"vr":0.31,"batt":11.6,"state":"balance","fault":null}
- The robot balances on its own and stops driving if no command arrives for 300 ms, so vision only decides where to go.
- The laptop and robot will share a laptop or phone hotspot rather than a crowded public Wi-Fi.
- On the mount, the phone's screen and front (selfie) camera face forward. It can be flipped to use the rear camera if that streams better.

Phases:
1. Setup. Check my OS and Python, make a venv, install opencv-python, mediapipe and numpy, and confirm they import. MediaPipe can lag behind the newest Python: if it won't install, use a slightly older Python for the venv.
2. iPhone → OpenCV. Get live iPhone video into cv2 with the lowest delay you can. Try at least two ways and compare FPS and delay (film a stopwatch on the laptop screen and compare the two clocks): (a) a webcam app on the iPhone (for example DroidCam or an IP-camera app) read as a network stream, and (b) if I'm on a Mac, Continuity Camera as a regular webcam. For each, note which camera it uses (front or rear), whether it keeps working when the phone's screen shows something else or turns off, and how it reconnects after a drop. Stretch: a small HTTPS page the iPhone opens in Safari that streams the front camera to Python over a WebSocket. That route would also let the phone's screen show a robot face.
3. Person tracking. Run MediaPipe person or pose detection on the stream, draw the box, and show FPS. Work at a small frame size (about 320–640 px wide) and report the speed at each size.
4. Follow-me. Turn the person's box into commands: box center x → turn rate w, box height → forward speed v (hold a set distance), with limits, a dead zone and smoothing. If the person is lost for about 1 s, set v = 0 and turn slowly to search. Send the JSON above over UDP at 20 Hz to a tiny mock-robot script on the same laptop that prints each command and sends fake telemetry back. Show the commands live on the video.
5. Gestures. MediaPipe Hands: open palm = stop, beckon = come here, thumbs up = deliver. Debounce them so each gesture fires once.
6. Notes. Write cv-practice-notes.md: the setup steps that worked, which streaming method you'd pick and why, the measured FPS and delay, the follow-me numbers that felt right, and the gotchas. Keep it to one page so I can share it with the team.
```

### 📄 `team-setup/team-context-prompt.md`

> **Last edited:** Nov 13. **Status:** Short context prompt for teammates' Claude.

### Team context prompt

_Nov 13, 2026. For Grant, Jialang and the others to paste into their own Claude at the start of hacking. John does the whole hardware stack, and everyone else does the software. Each person fills in `<NAME>` and `<ROLE>` first._

```
I'm <NAME>, on a hackathon team building a robot over the next ~36 hours. My teammate John is building the hardware. The rest of us write all the software. My role is <ROLE> (one of the three below). Help me plan, write and debug my part, and keep it plugging into everyone else's through the contract below.

THE ROBOT
- A half-size two-wheel self-balancing robot, about 40 cm tall and 2.2 kg, with a phone on top of its mast as the camera. A small HTD-45H servo arm is on the side of the mast.
- Pitch: a low-cost helper robot that follows you, carries things, and responds to gestures (open palm = stop, beckon = come here, thumbs up = deliver). Fallback if balancing isn't reliable by about hour 18: "kickstand mode", where the robot rests on a printed kickstand and drives with the same commands.

HARDWARE (John's; it's fixed, so build to it)
- ESP32-S3 DevKitC-1 (N16R8) on a screw-terminal board.
- 2× NEMA 17 steppers (200 steps/rev) on 2× TMC2209 drivers at 1/16 microstepping, step/dir only. 85 mm wheels.
- MPU-6050 IMU (GY-521) over I2C.
- 3S LiPo (11.1 V nominal) through a 15 A fuse. A buck converter gives the ESP32 5 V. Unplugging the XT60 is the off switch.
- ESP32 pins: IMU SDA = GPIO 8, SCL = GPIO 9. Left driver STEP/DIR = GPIO 4/5. Right driver STEP/DIR = GPIO 6/7. GPIO 15 = EN on both drivers (LOW = motors on).
- From the CAD: the center of mass is about 93 mm above the axle, and it balances at about a 1.3° lean.
- The arm servos run on a BusLinker serial board. Agree with John whether the ESP32 or the laptop drives it.
- If something about the hardware is unclear or seems wrong, ask John. Don't guess, and don't ask for physical changes without a reason.

SYSTEM CONTRACT (everyone builds against this; change it only if all of us agree)
- The phone streams video to a laptop. The laptop runs OpenCV + MediaPipe, the dashboard, and the logic that decides where to go.
- Laptop → ESP32, newline-delimited JSON over UDP at 20–50 Hz:
  {"t":"cmd","v":0.3,"w":0.0,"mode":"drive"}
  v = forward speed in m/s, w = turn rate in rad/s, mode = idle | balance | drive | kickstand.
- ESP32 → laptop telemetry at about 50 Hz:
  {"t":"tel","pitch":1.2,"rate":-0.4,"vl":0.28,"vr":0.31,"batt":11.6,"state":"balance","fault":null}
- Safety lives on the ESP32: if no command arrives for 300 ms, it holds position; if it tips past a set angle, it cuts the motors. Balancing never depends on Wi-Fi.
- Everything runs on a laptop or phone hotspot, not the venue Wi-Fi.
- Put the contract and sample messages in /shared/contracts in the first hour, plus a mock robot (a script that accepts commands and sends fake telemetry). Then everyone can work in parallel before the hardware is ready.

ROLES (pick yours, and only edit your own directory)
1. Firmware / controls (/firmware, ESP32, Arduino or PlatformIO):
   - Read the IMU with a complementary filter.
   - Drive the steppers with hardware-timer step pulses (for example FastAccelStepper).
   - Run a cascaded PID balance loop (pitch inner loop, wheel speed outer loop) at about 200–500 Hz.
   - Handle the UDP command/telemetry link, the 300 ms timeout, tilt cutoff and kickstand mode.
   - Expose the PID gains so they can be tuned live from the dashboard. Order: motors spin → IMU reads → balances 10 s while tethered → drives on commands.
2. Robot software + integrator (/robot, laptop Python):
   - A robot service that talks UDP to the ESP32 (or to the mock) and has one arbitrated drive() call: e-stop > manual joystick > autonomous behaviors.
   - A web dashboard: e-stop, joystick, a live pitch/battery plot, and live gain tuning.
   - Owns main, merges, the one-command run script and the demo path.
3. Vision / AI + pitch (/vision, laptop Python):
   - Phone → laptop video with low delay.
   - MediaPipe person tracking → follow-me commands (box center → w, box size → v, with a dead zone and smoothing; search slowly when the person is lost).
   - Gestures, plus a stretch goal: natural-language or voice commands.
   - Also owns the Devpost write-up, the 2-minute demo script and a backup demo video.
   - If anyone on the team already practiced this stack, start from their cv-practice-notes.md.

HOW WE WORK
- One shared GitHub repo. Before working, pull and read CLAUDE.md, TASKS.md, MESSAGES.md and /shared/contracts. Post questions and contract-change proposals in MESSAGES.md.
- Small branches, small commits. Keep main working.
- Never commit API keys: put the name in .env.example and the value in your own .env.
- Credit any open-source libraries in the README.
- Timeline (T = hacking start):
  - T+1: the contract and mock are in.
  - T+10: it balances for 10 s while tethered.
  - T+18: go/no-go on balancing, otherwise kickstand mode.
  - T+33: feature freeze, bug fixes only.
  - T+35: submit.

Start by summarizing my role in 5 lines. Then propose my first 3 tasks for the next 2 hours, each one testable against the mock robot. Wait for my OK before writing code.
```

---

# Part 3. What's in the zip (`team-context.zip`)

Only what you need to understand the project and build the robot:

| Path | What it's for |
|---|---|
| `team-context.md` | This file: the project, hardware, contract, plan and rules |
| `assembly-guide.html` | The build: 21 illustrated steps, the fastener kit and the wiring table, in one offline file |
| `cad/viewer.html` | An interactive 3D model of the whole robot. Open it in a browser to see how everything fits |
| `cad/assembly.step` | The full CAD assembly, for Fusion, Onshape or FreeCAD (measure things, check fits) |
| `cad/stl/` | All 22 printed parts as STLs, already in print orientation, to reprint any part that breaks (settings are in the assembly guide's print list) |
| `cad/renders/hero.png`, `exploded.png` | What the robot looks like, and how it comes apart |
| `cad/spec-sheet.png`, `cad/drawing.png` | Spec sheet and dimensioned drawing (also good for Devpost) |

# Left out on purpose

- **John's working files:**
  - the CAD source code (build123d)
  - raw CAD check logs
  - Bambu 3MF plates and per-plate print settings
  - extra close-up renders

  John owns the hardware and has all of these if someone needs them.
- **Repo templates as separate files:** their content (CLAUDE.md, TASKS.md, MESSAGES.md, DEMO.md) is in Part 2.
- **Superseded drafts and personal files:** the old full-size design, the never-bought shopping options, the pre-trip timeline, and John's own checklists. What still applies is in Part 1.


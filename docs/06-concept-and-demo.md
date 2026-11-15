# Concept and demo

**Proposed** Sat Nov 14, 12:30 pm (Nick), from the team's direction: a healthcare robot for older adults, a family app for their adult children, and a fall responder.

> **Superseded in part.** The team settled the use case in decision 0052: Miguel cares for a senior **in her own home**, directed by her family, not in assisted living. Where this doc says assisted living, a front desk or staff, read it as her home and her family; `00-overview.md` wins. It's kept for the feature ideas and the demo script.

## In one line

**Miguel walks with your parent, brings them what they need, and gets help if they fall, and you can look after them from your phone.**

## The 30-second pitch

Families of older adults ask themselves two questions every day: is Mom okay, and does she have what she needs? Today the answer is a phone call she may not pick up, or an alarm pendant she won't press. Miguel is a small balancing robot that lives with her. It walks beside her, carries water, medication and small things on its tray, and if she falls it is already there: it asks if she's okay, alerts her family with a photo, and lets them talk to her through it. Her kids see how her day went, send her things, and get an alert the moment something's wrong, all from one app.

## Who it's for

| Person | Their question | What Miguel gives them |
| --- | --- | --- |
| **Margaret**, 82, assisted living | "I don't want to bother anyone" | Company on her walks, water and medication brought to her chair, a night-light on the way to the bathroom, help that comes to her when she falls |
| **Sarah**, 45, her daughter, three hours away | "Is Mom okay? Does she have what she needs?" | A live picture of Mom's day, a button to send her water or a card, an instant alert with a photo if she falls, and her own voice coming out of Miguel |
| **Front desk staff** | "I can't be in every room" | Requests arrive with the item and the room; Miguel does the walking; fall alerts come with a photo and what she said |

## Why it matters (numbers for the pitch)

- **Falls:** about 1 in 4 adults 65 and older fall each year, and falls are the leading cause of injury death in that age group ([CDC](https://www.cdc.gov/falls/data-research/index.html)).
- **Lying on the floor, alarm unused:** in a study of people over 90, 80% of those who fell couldn't get up after at least one fall, 30% lay on the floor for an hour or more, and most had a call alarm they didn't use. Long lies were strongly linked to serious injury, hospital admission and moving into long-term care ([BMJ 2008](https://www.bmj.com/content/337/bmj.a2227.abstract)).
- **Walking speed is a vital sign:** across 34,485 adults 65 and older, age, sex and walking speed alone predicted survival as well as age, sex, chronic conditions, blood pressure, smoking history and more ([JAMA 2011](https://www.sciencedaily.com/releases/2011/01/110104161621.htm)). Miguel measures it every day just by walking alongside.
- **Families carry the load:** 63 million Americans are family caregivers, up 45% since 2015 ([AARP 2025](https://www.aarp.org/caregiving/basics/caregiving-in-us-survey-2025/)).

## Why this robot (judges will ask)

- **It goes to her.** A pendant has to be pressed and a wall camera can only watch. Miguel walks with her, so after a fall it's there in seconds.
- **It fits where she lives.** 19 × 13 cm and balancing on two wheels, it turns in place between a bed, a chair and a walker.
- **It's at the right height.** Its camera sits about 40 cm up, which is exactly the view for spotting someone on the floor. Its tray is at reach from a chair. Its face and mic are close to someone lying down.
- **It's cheap.** An old iPhone is the head: camera, screen, mic and speaker. Add [parts cost, from John].
- **It never takes weight,** by design. It doesn't lift anyone or act as a cane; it gets help.

## What Miguel can do

### Five building blocks (what we build)

Every feature is a combination of these, so building them well gives us many features.

| Block | What it does | Built from |
| --- | --- | --- |
| **Know her** | Finds and keeps track of Margaret, even with other people around | MediaPipe pose plus her clothing color, the same trick as John's yellow follow |
| **Move with purpose** | Follow beside her, go to the front desk, find her again, approach and stop at a set distance | John's follow gains; a colored marker at the front desk; turn-in-place to search |
| **Notice** | Standing, walking, sitting, on the floor; for how long; how fast she walks | Pose over time; wheel speed while following = her walking speed. A fall = her head and shoulders drop fast and stay low. The phone is now tilted up to see faces (PR #20), so the floor right in front is out of view: Miguel backs up half a meter to see her, then asks |
| **Talk** | Asks, listens, understands, answers, with a face that shows how it feels | The phone page (mic, speaker, face); speech to text; Claude picks skills; text to speech |
| **Connect** | Everything it notices goes to the family app; requests from the app become tasks; alerts go out with a photo | Server events over WebSocket to the app and the dashboard |

### Features (what people see)

| Feature | What happens | In the live demo? |
| --- | --- | --- |
| **Walk with me** | "Miguel, walk with me": it follows beside her and stops when she stops | Yes |
| **Her day, for the family** | The app shows walking, sitting, resting; minutes active; today's walking speed and its trend | Yes, on the judge's phone |
| **Bring it to her** | The family taps "Bring water" (or medication, bandages, a card); Miguel fetches it from the front desk and brings it with a message | Yes |
| **Fall response** | It notices she's on the floor, goes to her, asks if she's okay, alerts family and staff with a photo, lets family talk through it, stays with her | Yes |
| **Night-light** | At night, when she gets up, its screen turns into a warm light and it walks beside her | Yes, a few seconds |
| **Medication reminder** | "It's 2 pm, time for your blue pill." It asks whether she took it and logs her answer | App screen only |
| **Cards and voice notes** | Family sends a card (staff put it on the tray) or a voice note; Miguel delivers it and plays it | Message only (read aloud with the water) |
| **Check in** | Family asks to see her; Miguel asks Margaret first, then opens a live view with talk | App screen only |
| **Trust** | Open palm stops it at once; a camera-on light on its face; family can only look in when she says yes; video isn't stored | Mentioned; open palm if time allows |

### How it delivers without a gripper

The front desk has a small station with a green marker card. When the family taps "Bring water", the request appears on the front desk screen ("Water for Margaret, room 12"). Miguel drives to the marker, a staff member puts the item on the tray and gives a thumbs-up, and Miguel finds Margaret and brings it. Light things can also ride on the tray all day: a lidded water bottle and bandages, like a nightstand that follows her.

Tray rules: light items only (John measures the limit), centered, bottles with lids. Re-check the trim after mounting the tray and after loading the heaviest item (`firmware/README.md`, safety rules).

## The family app and the screens

All of these are pages in `web/` (Nick's lane), on the same server connection.

**Family app (Sarah's phone):**
1. **Home:** "Mom is walking with Miguel" (or sitting, resting, sleeping). Today: minutes active, walking speed with a 7-day sparkline, water brought, medication taken. Big buttons: Bring water, Bring medication, Send something, Check in.
2. **Send:** water, medication, bandages, or "something else" (free text for staff), plus an optional message ("Love you, Mom" or your own), read aloud by Miguel.
3. **Timeline:** her day as events ("12:41 Water delivered", "2:03 am Got up; night-light on").
4. **Alert:** full screen and loud. "Mom fell, 2:04 am." The photo, what she said ("My hip hurts"), and buttons: Hold to talk, Call front desk, Call 911.
5. **Check in:** asks Margaret first, then live view plus Hold to talk.

**Robot's phone (the phone page):** the face, with states for calm, listening, talking, worried, delivering and night-light; a camera-on dot; it also sends camera, mic and motion to the server and plays Miguel's voice.

**Front desk and team dashboard (laptop):** the request queue ("Load water for Margaret"), alerts, what Miguel sees with labels (standing, lying), what Claude decided, live tilt, STOP. For the demo it also has a **Reset demo** button and a **day/night** switch.

## The demo (2 minutes)

### Stage

About 2.5 × 2 m. Judges stand along the bottom edge, so they see Miguel's face whenever it faces Margaret or turns back toward them.

```
   +-----------------------------------------------+
   | [FRONT DESK]                        [CHAIR]   |
   |  green marker,                       Margaret |
   |  water bottle,                       sits     |
   |  John stands here                    here     |
   |                                               |
   |          ========== mat ==========            |
   |       (Margaret's path at "night")            |
   +-----------------------------------------------+
     Judges here                [LAPTOP: dashboard, facing judges]
     (one judge holds the family phone)
```

### Cast and props

- **Narrator (Nick):** tells the story, hands a judge the family phone.
- **Margaret (suggested: Grant):** wears a bright yellow cardigan or scarf (how Miguel knows her).
- **Front desk and spotter (John):** loads the tray, gives the thumbs-up, stays within reach of the robot the whole time (safety rule).
- **Operator (Alex):** at the laptop; watches the dashboard, presses STOP if needed, triggers fallbacks.
- **Props:** chair, yoga mat, small table or box for the front desk with a green card, a 250 ml lidded water bottle, the family phone (a team phone on our hotspot, app open as "Sarah"), the laptop with the dashboard facing the judges.

### Script

| Time | What happens | Narrator says | Miguel says or does | Judge's phone |
| --- | --- | --- | --- | --- |
| **Before** | Miguel balancing beside Margaret at the front desk. Dashboard reset, day mode | | Calm face | Home: "Mom is with Miguel" |
| **0:00–0:15** Hook | Narrator hands a judge the phone | "This is Margaret. She's 82 and lives in assisted living. You're her daughter, three hours away, and this is your app." | | |
| **0:15–0:35** Walk with me | Margaret: "Miguel, walk with me." She walks slowly to the chair and sits | "Miguel balances on two wheels, so it goes anywhere she walks. And just by walking with her, it measures her walking speed, one of the best predictors of how an older adult is doing." | "Coming, Margaret!" Follows beside her and stops when she sits | Status: "Walking with Miguel", then "Sitting". Walking speed fills in: "0.6 m/s today" |
| **0:35–1:05** Bring it to her | Narrator: "She hasn't had water since lunch. Tap Bring water." Judge taps it, with "Love you, Mom". Miguel drives to the front desk; John puts the bottle on the tray and gives a thumbs-up; Miguel finds Margaret and comes back | "No gripper needed: staff load the tray, Miguel does the walking. Medication, bandages, a birthday card: same thing." | "Sarah asked me to bring you some water. Back in a moment!" … "Thanks!" … "Here's your water, Margaret. Sarah says: love you, Mom!" | "Water on its way", then "Water delivered 12:41 ✓" |
| **1:05–1:40** Night and the fall | Alex switches to night. Margaret stands: "Miguel, I need the bathroom." She walks across the mat and goes down onto it, slowly | "It's 2 am. She gets up for the bathroom, in the dark." | Face becomes a warm night-light; walks beside her. When she's down: worried face, rolls to her head: "Margaret, are you okay?" She: "I fell. My hip hurts." Miguel: "Don't try to get up. I'm telling Sarah and the front desk. I'm staying right here." | Loud full-screen alert: photo, "Mom fell, 2:04 am", "She says her hip hurts", Hold to talk |
| **1:40–1:50** Talk | Narrator: "Hold to talk." Judge: "Mom, help is coming." John walks over as the "nurse" | | Plays the judge's voice | |
| **1:50–2:00** Close | Narrator points at the dashboard | "It saw her upright, then on the floor. Claude decided to check on her, alert family and stay; it picks actions, it never drives the wheels. One old iPhone and [cost] of parts. Miguel: take care of your parents, even from far away." | | |

**The three moments judges remember:** they tapped a button and a robot brought water across the floor; it noticed the fall without being told; their own voice came out of the robot.

### Cues and fallbacks

Every beat has a real trigger first and backups after it. A backup is only for when the real one fails; if a judge asks, say which one ran.

| Beat | Real trigger | Backup 1 | Backup 2 |
| --- | --- | --- | --- |
| Start following | Margaret: "Miguel, walk with me" | Beckon gesture | Alex clicks Follow on the dashboard |
| Knows Margaret | Pose plus yellow clothing lock | Margaret stays the only person inside the square | |
| Delivery request | Judge taps Bring water | Narrator taps it | |
| Loaded, go | John's thumbs-up | John taps Loaded on the dashboard | Leaves 3 s after arriving |
| Find Margaret again | Turns in place to find yellow, drives over | Margaret waves: "Over here, Miguel" | Alex drives with the dashboard joystick |
| Fall detected | Her head drops fast and stays low for 2 s | Margaret: "Miguel, help!" | Alex presses Fall on the dashboard |
| Talk | Hold to talk, played on Miguel | Preset quick reply ("Help is coming"), spoken in Miguel's voice | |
| Balancing trouble | | Kickstand mode near the chair: it turns to face her; voice, face, app and alert all still work | Backup video |
| Wi-Fi drops | Own hotspot | Long USB cable, laptop on a stool at the square's edge | Backup video |

### Reset between judges (about 45 s)

1. Margaret back to the front desk; bottle back on the desk; mat flat.
2. Alex: **Reset demo** on the dashboard (clears the timeline and alert, day mode).
3. If the run limit is close, park (P) and start again (g, held upright). The limit is 5 minutes today and 30 once PR #20 merges.
4. Glance at the battery: stop and swap or charge below about 10 V.
5. The robot's phone is still awake and the family phone is on Home.

### The 30-second version (walk-up judges, special tracks)

Margaret already in the chair with Miguel beside her. Narrator: "Miguel lives with older adults. Watch what happens if she falls." Margaret goes down; Miguel goes to her, asks, alerts the judge's phone, the judge talks to her. Close with the one-liner.

### Questions judges will ask

- **Why not an alarm pendant?** Most people who lie on the floor for a long time had one and didn't use it (BMJ 2008). Miguel doesn't need to be pressed.
- **Why not a camera on the wall?** It can't come to her, can't bring her anything, and needs one per room. Miguel goes where she goes.
- **Privacy?** Perception runs on our own laptop, video isn't stored, a camera-on light shows when it's looking, and family can only look in when she says yes.
- **What if she falls when Miguel isn't with her?** By default it stays with her; when it's elsewhere it checks back on a schedule. Honest limit: it's not a wall-to-wall sensor.
- **Can it help her up?** No, by design: a 2.2 kg robot must never take weight. It gets a person.
- **How does it know it's her?** Today: her pose plus the color of her clothing. Next: recognizing her face after a one-time setup.
- **What did you build here?** All software at the event; the hardware was pre-built with the organizers' OK (disclosed on Devpost).
- **Battery life?** [Measure before judging.]

## Build plan (Sat 12:30 pm to the Sun 5 am freeze)

**Tier 1: no demo without these.** Target: first full run-through at 9 pm, backups allowed.

| What | Who | Notes |
| --- | --- | --- |
| Robot over the hotspot | John, Alex | The biggest unknown. Test before anything else |
| Server skeleton, link, arbiter, events to the web | Alex | Already in the build plan |
| Know Margaret and follow her; approach and stop | Grant, Alex | Start from John's follow gains |
| Go to the front desk marker and back to Margaret | Grant | Same color tracking as the yellow follow |
| Fall detection | Grant | Head and shoulders drop fast and stay low; back up to see her |
| Phone page: face, camera, voice out | Nick | Face states; send frames; play speech |
| Family app: Home, Bring water, Alert, Timeline | Nick | |
| Miguel speaks (text to speech) | Grant | Its lines are in the script above |

**Tier 2: makes it polished.** Target: second run-through at 1 am, then record the backup video.

| What | Who |
| --- | --- |
| Listening (phone mic), Claude picking skills | Grant |
| Hold to talk from the family app | Nick |
| Walking speed and activity on the app | Nick, Grant |
| Night-light and worried faces | Nick |
| Front desk request queue, thumbs-up to go | Nick, Grant |
| Dashboard: Reset demo, day/night, fallback buttons | Nick |

**Tier 3: shown as app screens unless there's time.** Medication reminders, check-in video, cards, voice notes, more than one resident.

**Checkpoints:** 6 pm Miguel follows Margaret's yellow over Wi-Fi and the app shows her status. 9 pm first full run-through. 1 am second run-through and the backup video. 5 am freeze. 5–7 am rehearse at least five times, then Devpost.

## Questions for the team

| # | Question | Options | Recommendation |
| --- | --- | --- | --- |
| 1 | Use this concept, Healthcare as the main track, plus Best Physical AI, Best Hardware and Amazon Practical AI? (P-1, P-2) | This; the pediatric distraction buddy; a general helper | This. Hard to reverse after tonight, since skills and screens get built for it |
| 2 | Which way the phone faces. The rear camera points forward, so the screen faces backward: Margaret wouldn't see the face | Flip the phone and use the front camera (face and camera both forward); keep the rear camera and lose the face; add a second screen | Flip it and use the front camera. The face is half the character, and tilted up it looks up at people. Flipping moves the balance point, so re-trim (John). Check the front camera still sees head and shoulders (Grant) |
| 3 | How it spots a fall now that the camera is tilted up (T-10 in PR #20) and can't see the floor right in front | Watch for the head dropping fast, then back up to look; tilt the camera back down (loses faces and gestures); a second, low camera | Head drop, then back up and ask. It keeps the tilt that makes following work |
| 4 | How Miguel knows Margaret | Clothing color plus pose; face recognition; whoever is closest | Clothing plus pose for the weekend (it reuses what already works), and say so honestly |
| 5 | How it finds the front desk | A colored marker; counting wheel turns; ARKit position | The marker: same tracking that already works; wheel counting drifts |
| 6 | Where Margaret's voice is heard (T-13) | The phone page's mic; a clip-on mic to the laptop | Phone mic, since Miguel brings it to her face; a clip-on mic as backup in a loud hall |
| 7 | Tray load limit and trim | | John measures and re-trims with the tray and the bottle on |
| 8 | Who plays which role | | As suggested in the cast |

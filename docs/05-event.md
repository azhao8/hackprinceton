# Event

HackPrinceton Fall 2026, Julis Romo Rabinowitz Building, Princeton. Hacking runs from 8 pm ET Fri Nov 13 to a hard 8 am ET Sun Nov 15 submission deadline (36 h); judging is 9:30 am-2:30 pm Sunday.

Sources: [on-site handbook](https://docs.google.com/document/d/1sifGjJ_WePpTG7EaCPkWB89p3g1qEEyEvNmJ8Ef191A/edit), [main tracks](https://docs.google.com/document/d/1vlIlKADkpq5dy7ECl28IW5aqpP4Wmv5skNWSJ9sxIMU/edit), [special tracks](https://docs.google.com/document/d/1mWhKpigToIglYtf34ldFHn4B95kGF4N34A5C7KUxUsc/edit), [official site](https://www.hackprinceton.com/).

**Theme:** "Passport to Innovation". It's just the theme; projects don't need to fit it.

## Rules that shape the build

- Submit a public GitHub repo created Nov 13-15.
- Enter exactly one main track; special tracks are unlimited, but each one is another demo during round 1.
- Pitch and in-person demo, max 2 min, at an assigned spot; an optional 2-min video is "highly recommended" (a good backup if the robot misbehaves).
- Main rubric: creativity, utility, charity (societal need), avidity (team excitement, polish, future plans).
- Wi-Fi is the puvisitor guest network, which needs a sign-in page an ESP32 can't complete: use our own hotspot.
- No ESP32/IMU rental here; the MLH kit has Raspberry Pis, Arduinos, webcams and Echo/Google Home devices.
- AI coding tools are allowed if disclosed on Devpost; past events required about 85% of code to be written during the event.
- Organizers OK'd pre-building the hardware (per John, Nov 9): keep the screenshot and disclose the pre-event hardware work on Devpost.

## Prize strategy

Aim to win 1-2 tracks for sure. Enter a track only if its criteria already describe the robot; the last hackathon chased every track and won nothing. Tracks aren't chosen yet; the table is a recommendation.

| Track | Type | Prize | Fit | Recommendation |
| --- | --- | --- | --- | --- |
| Best Physical AI Hack (Justin Bojarski) | Special | $500 | "Must incorporate AI into a physical hardware build": exactly this project | Enter |
| Best Hardware Hack | Optional main | Bambu P1S | Robotics is named; past winners were small, reliable builds | Enter |
| Best Healthcare Hack | Main (pick one) | Apple Watch SE 3 each | Helper robot for limited mobility; John's docs also recommend it | Likely main track |
| Best Practical AI Innovation (Amazon) | Special | $125/person for 1st | Agentic AI for real users; its own example is "an accessibility tool that uses voice, vision, or gesture". The same prize went to a gesture project (MindPad) at F25 | Enter |
| MLH Best Use of Gemini API | MLH | Swag kits | Only if Gemini ends up being the AI we use | Maybe |
| Best use of deepagents (LangChain) | Special | Switch 2 | Only if the planner is built on deepagents anyway | Maybe |
| Photon (iMessage agents) | Not listed for F26 | None announced | Ran prizes at F25 and S26; not on this year's special-track list | Skip unless announced |
| Inside and Out (CoStar) | Special | $1,500 | Needs 2 of 3 CoStar data layers; forced for an indoor robot | Skip |
| Forward Deployed (Peri) | Special | Interviews | Needs a real business consulted during the event | Skip |
| Arlequin AI | Special | Unstated | Forensics or social-network analysis | Skip |

Best Overall is automatic; track winners can't also win it.

## Demo notes

- **Past-winner patterns (F25, S26):** overall winners pair a concrete societal problem with a strong live visual demo; camera and gesture projects win repeatedly; agents that take real actions beat chatbots; winners often stack 2-3 prizes that fit naturally.
- **Draft 2-minute demo (John's, Nov 9):** robot rolls up following the judge with a tray (0:00-0:15); problem and why balancing (small footprint, fits between beds) (0:15-0:40); live module swap (0:40-1:20); how it works plus live pitch graph and cost (1:20-1:45); what's next (1:45-2:00). Modules are conceptual for now, so the swap would show concept modules.
- **Demo space:** plan a short scripted demo in a cleared ~2 m square.

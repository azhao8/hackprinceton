# Product

What Miguel.exe is and does, as a person experiences it.

**Use case (decision 0052):** a caretaker robot in a senior's home. The senior's children use an iOS app to ask it to help their parent, for example "bring Mom her pills" or "get Dad a glass of water". The senior can also talk to it directly. Open details: how it carries things without a gripper (P-5), how it finds places and the senior (P-6), what else the family app does (P-7), and how the app reaches the robot from outside the home (T-17).

## Concept

Working pitch (tentative): a two-wheeled self-balancing robot with an iPhone "head" that sees, shows a face, and helps people who can't easily reach things, driven by gesture and voice instead of a controller.

- **Body:** a frame on two wheels that balances itself, about 50 cm tall.
- **Head:** an iPhone at the top, used for sensing (camera, possibly LiDAR) and as a display (eyes, status, info).
- **Hands:** nothing built yet; any arm or end attachment can be added later. The robot is pitched as modular, with concept modules in the demo. Core functionality comes first.
- **Control:** no handheld controller; gestures and voice.
- **Purpose:** caring for seniors at home, with their family directing it from an app (decision 0052).

## Principles (decided)

- **Must-work floor:** follows you, carries things, responds to gestures (open palm = stop, beckon = come here, thumbs up = go ahead).
- **Own words:** people talk to it in their own words; an LLM understands them. Gestures stay as instant controls.
- **Anyone can direct it,** one person at a time.
- **Autonomy:** the human says what; the robot works out how.
- **Character:** named Miguel.exe, with a light personality (name, eyes, voice).
- **Memory:** it remembers things while it's running and forgets on restart.
- **Companion panel:** shows what it sees and thinks, with buttons to give tasks, if it doesn't take too much effort.
- **Trust:** the stop gesture always works; it says what it's about to do; a visible camera-on indicator.
- **Low tasks:** the use case favors things that happen low: the floor, seated people, kids.

## Use case brainstorm

Every idea runs on the same core: balance, drive, see people and objects, talk, show a face, carry small things. Grouped by the HackPrinceton main track it would enter.

| Idea | Who it helps | Main track | Demo moment |
| --- | --- | --- | --- |
| Dropped-item retriever | Wheelchair users, people who can't bend down | Healthcare | Judge drops a pen; robot sees it, picks it up, brings it back |
| Fetch-and-carry helper | Elderly, people recovering from injury | Healthcare | "Bring me my glasses case" |
| Medication reminder and delivery | Older adults living alone | Healthcare | At a set time it rolls over with the pill box and asks if they took it |
| Fall check-in companion | Older adults, their families | Healthcare | Sees someone on the floor, asks if they're OK, texts a caregiver |
| Physical therapy coach | Rehab patients doing home exercises | Healthcare | Watches squats, counts reps, cheers, flags bad form |
| Find-my-things helper | Blind/low-vision users, people with dementia | Healthcare | "Where are my keys?" It remembers where it saw them and leads you there |
| Reader on wheels | Low-vision users | Healthcare | Holds a letter or pill bottle up to the camera and reads it aloud |
| Telepresence visitor | Hospital patients, isolated seniors | Healthcare | Family video-calls in through the phone face and drives around the room |
| Hospital supply runner | Nurses | Healthcare | Carries supplies between two beds on command |
| Litter picker | Campuses, parks, event halls | Sustainability | Spots a wrapper on the floor, picks it up, drops it in a bin |
| Recycling sorter | Anyone at a trash station | Sustainability | Picks up an item, says "that's recyclable", puts it in the right bin |
| Energy and waste patrol | Offices, dorms | Sustainability | Patrols and reports lights left on, open windows, overflowing bins |
| Robotics and AI teaching platform | Students, STEM outreach | Education | Kids give it plain-language instructions and watch its "thoughts" on screen |
| Language-learning buddy | Kids, language learners | Education | You point at an object; it names it in Spanish and quizzes you |
| Homework or reading buddy | Young kids | Education | Listens to a child read, helps with hard words |
| Control-systems explainer | Engineering students | Education | Shows live tilt and correction graphs while balancing |
| Robot pet with personality | Anyone; lonely people | Entertainment | Follows you, wiggles when happy, "sulks" when ignored |
| Robot camera operator | Creators, streamers | Entertainment | Follows and films you, keeps you framed, cuts a short video |
| Game partner | Kids, families | Entertainment | Plays Simon Says or rock-paper-scissors with gestures and the arm |
| Party or photo-booth host | Events | Entertainment | Approaches people, takes photos, prints or shares them |
| Storyteller | Kids | Entertainment | Tells a story with eyes, voice and acting it out with its body |
| Retail shelf auditor | Store staff | Business | Rolls down an aisle, flags empty or misplaced items |
| Office or hotel runner | Front desk, office staff | Business | Carries mail or snacks to a named person |
| Greeter and wayfinder | Visitors in lobbies or events | Business | Greets visitors and leads them to a room |
| Security patrol | Small businesses after hours | Business | Patrols a route, notices people or changes, sends alerts |
| Lab assistant | Researchers, students | Science | Fetches small tools, runs timers, logs what happened |
| Environmental mapper | Facilities, researchers | Science | Walks a building and maps light, noise or Wi-Fi strength |
| Experiment documenter | Labs | Science | Photographs a sample at set times and builds a timelapse report |
| Food bank or shelter helper | Volunteers, nonprofits | Healthcare / Business | Carries and sorts donated items |
| Hackathon helper | Hackers (very on-theme for judges) | Entertainment / Business | Delivers snacks, finds a mentor, cheers you on at 4 am |

Recommendation, still open: ideas that need grabbing (dropped-item retriever, litter picker, recycling sorter) depend on an end attachment that isn't built. Without one, the strongest fits for this body are the fetch-and-carry helper with a tray (the team's Nov 9 top pick), the find-my-things helper, the robot pet and telepresence. All of them share one core: follow a person, see and name things, talk, carry.

## Capability menu

Everything the robot could do, described as what a person experiences. Nothing is picked or ruled out; the core gets chosen from here once the use case is set. Effort is a rough guide for a 36 h build: Low = a few hours, Med = half a day, High = most of the weekend.

### Noticing (what it perceives)

| ID | Capability | What a person sees | Effort |
| --- | --- | --- | --- |
| P1 | Sees people | Its eyes turn to follow you as you move | Low |
| P2 | Reads hand gestures | It reacts to a wave, open palm or thumbs up | Low |
| P3 | Knows objects by name | "The blue mug" means the blue mug, not any mug | Med |
| P4 | Senses obstacles | It stops or steers around a chair leg | Med |
| P5 | Recognizes specific people | "Hi Sam" | Med |
| P6 | Describes what's around it | "There's a backpack and two cups on the floor" | Low |
| P7 | Reads text | Reads a label, letter or pill bottle aloud | Low |
| P8 | Notices a fall | Sees someone on the floor and checks on them | Med |
| P9 | Reads emotions | Notices you look upset and softens its tone | Med |
| P10 | Remembers where things are | "Your keys were by the couch 10 minutes ago" | Med |
| P11 | Spots changes | Notices a spill, a dropped item, an open door | Med |
| P12 | Turns toward voices | You speak from the side; it turns to face you | Med |
| P13 | Reads markers | Recognizes QR or tag stickers on places and objects | Low |
| P14 | Counts things | "Shelf 3 has 2 cereal boxes left" | Med |

### Communicating (how people direct it and how it responds)

| ID | Capability | What a person sees | Effort |
| --- | --- | --- | --- |
| I1 | Gesture commands | Palm = stop, beckon = come, thumbs up = go ahead | Low |
| I2 | Fixed voice commands | "Robot, stop" / "Robot, follow me" | Low |
| I3 | Requests in your own words | "Can you grab the thing I dropped under the chair?" | Med |
| I4 | Point and say "get that" | You point at an object; it goes to the right one | High |
| I5 | Expressive face | Eyes that blink, look around, show mood and status | Low |
| I6 | Conversation with personality | Small talk, jokes, a consistent character | Low |
| I7 | Body language | Nods by rocking forward, wiggles when happy, slumps when tired | Med |
| I8 | Arm gestures | Waves hello, points at what it found | Low |
| I9 | Wake and focus | Wakes when you wave or say its name; attends to one person at a time | Low |
| I10 | Many languages | Understands and answers in the speaker's language | Low |
| I11 | Companion screen | A laptop or phone view: live camera, what it's thinking, buttons to give tasks | Med |
| I12 | Telepresence | A remote person video-calls in and drives it around | Med |
| I13 | Basic sign language | A handful of ASL signs work as commands | High |
| I14 | Caregiver alerts | Texts or notifies someone when something needs attention | Low |
| I15 | Explains itself | "I'm going to the kitchen to get your water" before it moves | Low |

### Deciding and moving (what it does on its own)

| ID | Capability | What a person sees | Effort |
| --- | --- | --- | --- |
| A1 | Follow me | Walks beside or behind you at a set distance | Low |
| A2 | Go to a visible thing | Drives to the object or person you named | Med |
| A3 | Avoid obstacles | Weaves around feet and furniture | Med |
| A4 | Saved places | "Go to the kitchen" | Med |
| A5 | Maps a space | Explores a room and plans its own route | High |
| A6 | Suggests help | "You dropped something, want me to get it?" (asks, doesn't act) | Med |
| A7 | Searches | Wanders until it finds the thing or person you asked for | Med |
| A8 | Patrols | Walks a route and reports what it saw | Med |
| A9 | Scheduled tasks | "At 3 pm, bring me the pill box" | Low |
| A10 | Parks itself | Puts its kickstand down when idle or low on battery | Med |
| A11 | Multi-step errands | "Find my keys, bring them, then go back to the door" | Med |
| A12 | Polite distance | Slows down near people and never crowds them | Low |

### Handling objects

| ID | Capability | What a person sees | Effort |
| --- | --- | --- | --- |
| M1 | Grabs from a known spot | Picks up an item placed in a set position | Low |
| M2 | Grabs what it sees | Lines up with any small object and picks it up | High |
| M3 | Hand-over | Holds the item out and lets go when you take it | Med |
| M4 | Picks up from the floor | Retrieves a dropped pen, wrapper or toy | Med-High |
| M5 | Carries in a holder | Brings items in a basket, no grip needed | Low |
| M6 | Pushes things | Nudges a ball, a door stop, an item toward you | Low |
| M7 | Sorts into bins | Drops each item in the right bin | High |

### Memory and growth

| ID | Capability | What a person sees | Effort |
| --- | --- | --- | --- |
| X1 | Remembers you | Your name, preferences, what you asked for yesterday | Med |
| X2 | Daily summary | A short report for a caregiver or owner of what happened | Low |
| X3 | Learns by watching | "Watch me put this here, now you do it" | High |
| X4 | New skills plug in | Abilities can be added like apps without rebuilding the rest | Med |

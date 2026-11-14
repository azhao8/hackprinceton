# Miguel.exe (HackPrinceton Fall 2026)

Two-wheeled self-balancing robot with an iPhone head that sees, shows a face,
and takes instructions by gesture and voice. Read docs/00-overview.md first;
it wins over every other doc.

## Repo map

| Path      | What                                                           | Stack             |
|-----------|----------------------------------------------------------------|-------------------|
| contract/ | Messages between laptop and robot, with samples                | JSON              |
| firmware/ | Balancing, motors, IMU, robot link, arm                        | ESP32, PlatformIO |
| server/   | Robot link, mock robot, vision, speech, LLM brain, skills, API | Python            |
| web/      | Dashboard, phone face and camera page                          | Next.js           |
| sim/      | Balance simulation                                             | Python            |
| docs/     | Plans, decisions, open questions, milestones, reference        | Markdown          |

## Commands (fill in as code lands)

- Server: cd server && uv sync && uv run python -m app --robot mock
- Mock robot: cd server && uv run python -m mock
- Web: cd web && npm install && npm run dev
- Firmware: cd firmware && pio run -t upload && pio device monitor

## Workflow

- One task = one GitHub issue = one branch = one PR that says "Closes #N".
- Only the master agent merges and pushes to main; everyone else opens PRs.
- main always runs against the mock robot.

## Rules

- Everything except firmware runs against the mock robot.
- Only the server's link code talks to the robot, using contract/.
- Drive commands go through one arbiter: e-stop > manual joystick > skills.
- The LLM picks skills; it never sends speeds.
- A contract change updates the mock and the firmware in the same PR.
- Don't send commands to the real robot unless the user says someone is with it.
- Secrets live in .env (git-ignored); names go in .env.example.
- Credit open-source libraries in README.md.

## Docs

- Settled: docs/decisions/. Open: docs/open-questions.md. Milestones: docs/milestones.md.
- docs/reference/ is background; docs/reference/john-pack/ is a raw archive, open only when needed.
- When something is decided: add a decision file and update 00-overview,
  open-questions and the doc it affects.

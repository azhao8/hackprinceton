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

- Lanes and owners are in docs/01-build-plan.md. Stay in your lane's folders;
  a PR that touches another lane's folder says so and gets that owner's OK.
- One task = one GitHub issue = one branch = one PR that says "Closes #N".
  Issues carry a lane label (lane:motion, lane:vision, lane:misc). Assign
  yourself before starting. Branch name: <lane>/<N>-short-name.
- Pull main before starting a task. Keep PRs small; tests pass before opening.
- Only the master agent (Alex, GitHub azhao8) merges and pushes to main;
  everyone else opens PRs. main always runs against the mock robot.
- Talk in issue and PR comments (blockers, questions, interface changes);
  the group chat is for quick pings. Read the issue's comments before working.

## How to choose

- Be as standard as possible: use the common convention, library or
  protocol before inventing one (for example SI units and ROS REP 103 axes).
- Prefer the simpler way when it does the job; pick a better way over the
  first one that works.
- For any real choice, list as many alternatives as you can, critique each
  in a line, then pick one and say why. For a choice that affects the
  product, bring that list to your human (see below).

## Ask, don't guess

- If a choice could affect the product (decisions, architecture, interfaces
  between lanes, product details, UI/UX, demo behavior), stop and ask your
  human instead of assuming. Say what the question is, the options, and your
  recommendation.
- Your human raises it with the team (issue comment, then a group-chat ping);
  the team decides together. Settled answers go in docs/decisions/; ones still
  open go in docs/open-questions.md.
- Keep working on parts the question doesn't touch while you wait.
- Trivial choices (variable names, file layout inside your lane, small
  refactors) don't need asking; just make them.

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

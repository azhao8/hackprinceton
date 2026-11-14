# Miguel.exe (HackPrinceton Fall 2026)

Two-wheeled self-balancing robot with an iPhone head that sees, shows a face,
and takes instructions by gesture and voice. Read docs/00-overview.md first;
it wins over every other doc.

**Latest (Sat Nov 14, noon, from John):** the real robot works. It balances hands-off with the
phone mounted, drives over USB and follows a yellow object. Before any firmware or real-robot
work, read firmware/README.md: its state, frame, the link it speaks, safety rules, next steps.

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
- Firmware (arduino-cli for now; see firmware/README.md):
  cd firmware/balance && arduino-cli compile --upload --fqbn esp32:esp32:esp32s3 -p <port> .
- Drive the real robot from the keyboard over USB (someone at the robot): cd firmware/balance && python3 drive.py

## Workflow

- Lanes and owners are in docs/01-build-plan.md. Stay in your lane's folders;
  a PR that touches another lane's folder says so and gets that owner's OK.
- One task = one GitHub issue = one branch = one PR that says "Closes #N".
  Issues carry a lane label (lane:motion, lane:vision, lane:misc). Assign
  yourself before starting. Branch name: <lane>/<N>-short-name.
- Pull main before starting a task. Keep PRs small; tests pass before opening.
- Anyone may push or merge to main, but only when their human asks for
  that specific action. Branches, PRs, issues and comments need no
  permission. main always runs against the mock robot.
- Alex's agent (GitHub azhao8) is the master agent: it organizes the work
  (issues, milestones, decisions, keeping the docs in sync).
- Talk in issue and PR comments (blockers, questions, interface changes);
  the group chat is for quick pings. Read the issue's comments before working.

## Decisions

A decision is anything that changes what the product does or looks like,
how parts fit together, or would be hard to change later. Naming and small
refactors inside your lane aren't decisions; just do them.

1. Don't decide alone: ask your human, and the team decides. Keep working
   on what the question doesn't touch.
2. When asking, list every alternative you can find with a one-line
   critique, mark which is standard, and give your pick and why.
3. Prefer standard over custom and simple over complex, unless the other
   option buys something real. Setup effort barely counts (agents do it);
   runtime, platform, debugging and demo risks do.
4. Say how hard it is to reverse, and settle hard-to-reverse ones before
   other code depends on them.
5. Cite sources (file:line or link) and label guesses as guesses.
6. Stay impartial: change an answer for a reason, not because someone asked.
7. Add every open question to docs/open-questions.md as soon as it comes
   up (chat, issue or PR), with your recommendation and where it came from.
   Once the team settles it, move it to docs/decisions/ (from TEMPLATE.md)
   and update the docs it affects (00-overview first).

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

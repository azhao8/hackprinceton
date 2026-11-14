# Decisions

One file per settled decision. Don't edit an old decision: to change it, add a new file and mark the old one "superseded by NNNN".

New file: next number, `NNNN-short-name.md`, copied from [TEMPLATE.md](TEMPLATE.md). Older decisions predate the template and keep the short form.

| # | Decision | Source |
| --- | --- | --- |
| [0001](0001-two-wheeled-self-balancing.md) | Two-wheeled self-balancing frame | Kickoff |
| [0002](0002-iphone-head.md) | iPhone on top as sensor head and display | Kickoff |
| [0003](0003-no-handheld-controller.md) | No handheld controller | Kickoff |
| [0004](0004-hardware-bought-software-focus.md) | Hardware is bought; docs cover software | Round 1 |
| [0005](0005-prize-strategy.md) | Prize strategy: win 1-2 tracks for sure | Rounds 2-3 |
| [0006](0006-software-unconstrained.md) | Software is unconstrained | Round 3 |
| [0007](0007-keep-options-open.md) | Brainstorm wide before narrowing | Round 3 |
| [0008](0008-autonomy-level.md) | Autonomy: the human says what, the robot works out how | Round 3 |
| [0009](0009-one-agent-for-now.md) | One agent does all software work for now (superseded by 0033) | Exit round |
| [0010](0010-plan-shape.md) | General core first, then specialize | Q1, Q11 |
| [0011](0011-llm-understanding.md) | An LLM handles understanding | Q2 |
| [0012](0012-anyone-can-direct.md) | Anyone nearby can direct it | Q3 |
| [0013](0013-miguel-exe.md) | Name and character: Miguel.exe | Q4b |
| [0014](0014-memory-during-run.md) | Memory lasts while it runs | Q5 |
| [0015](0015-companion-panel.md) | Companion panel | Q6 |
| [0016](0016-low-tasks.md) | Favor low tasks | Q7b |
| [0017](0017-trust-features.md) | Trust features | Q8 |
| [0018](0018-light-planning.md) | Planning stays light | Q9, Q12 |
| [0019](0019-team.md) | Team: one on hardware, three on software | Q10 |
| [0020](0020-end-attachment.md) | No end attachment yet; core first | Q13 |
| [0021](0021-modules-conceptual.md) | Modules are conceptual | Q14 |
| [0022](0022-theme.md) | The theme is just a theme | Q15 |
| [0023](0023-planning-doc-source.md) | The planning doc was the source for docs/ | Docs round |
| [0024](0024-docs-layout.md) | docs/ layout | Docs round |
| [0025](0025-john-pack-archive.md) | John's pack is archived as reference | Docs round |
| [0026](0026-master-agent-merges.md) | One master agent merges; others open PRs (superseded by 0048) | Repo setup (C2) |
| [0027](0027-tasks-in-issues.md) | Tasks in GitHub Issues plus a milestones doc | Repo setup (T1, T4) |
| [0028](0028-stack.md) | Stack: Python server, Next.js web app | Repo setup (S2, N1) |
| [0029](0029-folder-layout.md) | Folder layout | Repo setup (S1, N2) |
| [0030](0030-claude-md.md) | Rules live in CLAUDE.md | Repo setup (C3) |
| [0031](0031-docs-is-source.md) | docs/ is the source of truth | After the first commit |
| [0032](0032-bench-first.md) | Build on the desk and against the mock robot | Build-plan round (B1) |
| [0033](0033-vision-motion-equal.md) | Vision and motion are equal priority, one person each | Build-plan round (B2) |
| [0034](0034-first-slice.md) | First milestone: the end-to-end slice | Build-plan round (B3) |
| [0035](0035-arm-control.md) | Arm: laptop on the desk, ESP32 on the robot | Build-plan round (B5) |
| [0036](0036-motion-owns-firmware.md) | One person owns firmware and balancing | Build-plan round (B6) |
| [0037](0037-llm-claude.md) | LLM: Claude, with Gemini swappable | Build-plan round (B7) |
| [0038](0038-arm-gestures.md) | Arm in the demo: gestures only for now | Build-plan round (P-3) |
| [0039](0039-memory-in-build.md) | Memory is in the build | Build-plan round (P-4) |
| [0040](0040-platformio.md) | Firmware uses PlatformIO | Build-plan round (T-1) |
| [0041](0041-iphone-model.md) | The head is an iPhone 18 Pro or similar | Build-plan round (T-2) |
| [0042](0042-agents-md.md) | AGENTS.md points to CLAUDE.md | Build-plan round (W-2) |
| [0043](0043-estop-keeps-balancing.md) | E-stop stops the robot but keeps it balancing | Contract round |
| [0044](0044-collaboration-workflow.md) | How we collaborate day to day | Collaboration round |
| [0045](0045-ask-dont-guess.md) | Agents ask instead of guessing | Collaboration round |
| [0046](0046-standard-simple-alternatives.md) | Standard and simple, chosen from alternatives | Contract round |
| [0047](0047-decision-rules.md) | Decision rules in CLAUDE.md; only main is protected | Issue #4 |
| [0048](0048-anyone-merges.md) | Anyone can merge to main; Alex's agent organizes | Issue #6 |

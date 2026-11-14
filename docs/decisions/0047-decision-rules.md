# 0047: Decision rules in CLAUDE.md; only main is protected

- Date: 2026-11-14
- Status: accepted
- Source: issue #4
- Agreed by: Alex

CLAUDE.md's "Decisions" section replaces the separate "How to choose" and "Ask, don't guess" rules (0045, 0046 still hold; this is their short form). A decision is anything that changes what the product does or looks like, how parts fit together, or would be hard to change later. For each: the team decides; bring critiqued alternatives; prefer standard and simple unless the other option buys something real; say how reversible it is; cite sources; stay impartial; record only what the team settles. New decisions use TEMPLATE.md, and the PR template asks whether a PR makes an unrecorded decision.

Only main is protected: nothing is pushed or merged to main without Alex's OK for that action. Branches, PRs, issues and comments need no permission.

## Alternatives

| Option | Critique |
| --- | --- |
| **Short numbered rules in CLAUDE.md + decision template + PR checkbox** | Rules every agent reads, a template that makes missing fields visible, and a check at merge time that catches decisions made quietly in code |
| Rules in CLAUDE.md only | Agents skim; nothing catches a decision made inside a PR |
| A long decision guide in docs/ | Agents don't read it unless pointed to it; longer than it needs to be |

## Reversibility

Easy: it's text. Changing it only changes how future decisions are made.

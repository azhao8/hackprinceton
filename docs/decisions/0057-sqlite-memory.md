# 0057: Miguel's memory lives in SQLite and survives restarts

- Date: 2026-11-14
- Status: accepted (supersedes 0014; keeps 0039)
- Source: Alex's redesign, Sat night; issue #68
- Agreed by: Alex

Facts (remember / recall / forget), places (sign cards with markers) and the day's events go in one SQLite file, `server/miguel.db` (git-ignored). All of it is small, so it goes into every request to Claude; no search. The control page's Memory card shows and edits it. Places are data, not the `PLACES` env var (which now only seeds the table). Saved looks stay in `server/people.json` for now.

## Alternatives

| Option | Critique |
| --- | --- |
| **SQLite** (standard: yes) | One file, Python's standard library, safe writes, easy "everything today" queries |
| JSON files | Simple, but three writers at once (agent, API, control page) and a crash mid-write can corrupt it |
| Postgres / Supabase | Only needed when the family app runs off the home network on many devices; one more service |
| Vector database | Not needed: everything fits in the prompt |
| Claude's memory tool (`memory_20250818`) | Standard for free-form notes; harder to show as tidy, editable items. A later upgrade |

## Why this one

Restarts are routine at the demo; RAM-only memory lost Mom's day each time. Easy to reverse (one module, `server/app/memory/`).

# 0050: The server skeleton is #22; Grant builds on it

- Date: 2026-11-14
- Status: accepted
- Source: issue #21, PR #22, Grant's question on #3
- Agreed by: Alex

`server/` starts from Alex's skeleton (#22): one uv project, one folder per lane, the arbiter (e-stop > joystick > skill) and a draft skill API. Grant moves his follow-me pipeline (#3) into `app/vision` and `app/skills`, and follow-me drives through `ctx.drive(v, w)`, which goes to the arbiter. To unblock follow-me on the robot, Grant may add a minimal USB serial link in `app/link` behind one interface; Alex reviews it and owns it afterwards, and adds UDP and the mock with the contract.

## Alternatives

| Option | Critique |
| --- | --- |
| **Grant builds on #22** | Small and ready; the arbiter and lane layout were designed for all three lanes. Cost: Grant moves files |
| Use Grant's `server/` and drop #22 | Fastest to follow-me on the robot, but its layout and arbiter weren't designed for the other lanes |
| Both keep going | Two `server/` projects; whichever merges second hits a large conflict |

## Reversibility

Moderate: once all three lanes build on the layout, moving folders costs everyone. The skill API inside it is a draft Grant owns (T-8).

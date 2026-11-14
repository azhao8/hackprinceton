# 0051: Contract v1 is what the firmware speaks today

- Date: 2026-11-14
- Status: accepted
- Source: issue #23
- Agreed by: Alex

`contract/` (README, JSON Schemas, samples) writes down the robot messages exactly as `balance.ino` speaks them, plus `seq`/`ack` from #14: JSON `cmd` with modes drive/balance/idle, one-letter commands (`g`, `x`, `P`, `5`, `L`/`R`, `F`/`B`), `tel` at 20 Hz with angles in degrees, UDP 4210, `balancebot.local`. The mock robot (`server/mock/`) behaves the same. Changes come one at a time through C-1, each updating the firmware, schema, mock and samples together.

## Alternatives

| Option | Critique |
| --- | --- |
| **Write down what the working firmware speaks** | Matches the robot that balances; no firmware risk; every lane can build today |
| Alex's earlier proposal (renamed keys and modes, radians, live parameters) | More standard in places, but every change means re-testing firmware that already balances; several items would have broken it (C-1 review) |
| The v0 draft in 03-software.md | Never matched the firmware (kickstand mode, 50 Hz, no x/yaw) |

## Reversibility

Moderate: each change is small, but it touches the firmware, the mock, the server link and the dashboard together, so it goes through C-1 one item at a time.

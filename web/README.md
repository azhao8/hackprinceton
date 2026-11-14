# Web: the control page

The laptop's control page (decision 0053): drive with WASD, start, park, STOP, follow and its settings, say lines, live telemetry. It talks only to the server's WebSocket.

```bash
cd server && uv run python -m app --robot real --someone-at-robot --no-vision --no-window   # or --robot mock
cd web && npm install && npm run dev    # then open http://localhost:3000
```

- Keys (anywhere on the page): **W A S D** / arrows held to drive, **Space** stop and hold, **Q/E** 90° turns, **P** park, **X** motors off, **G** start balancing (asks first), **F** follow on/off.
- `NEXT_PUBLIC_SERVER_WS_URL` changes the server (default `ws://localhost:8080/ws`); `sample` runs an in-browser fake robot.
- The server's own simple page at `http://localhost:8080/control` still works as a backup.


The Next.js app for Miguel.exe: the dashboard now, the phone page (camera and face) later. Lane: misc (Nick).

## Run

```bash
npm install
npm run dev
```

Open http://localhost:3000. With no server configured, the dashboard runs on sample telemetry from a fake robot in the browser (`lib/fake-robot.ts`). To use the server instead, copy `.env.example` to `.env.local` and set `NEXT_PUBLIC_SERVER_WS_URL`.

## Check

```bash
npm test
npm run lint
npm run typecheck
npm run build
```

## Layout

- `app/page.tsx`: the dashboard route.
- `components/`: dashboard, e-stop panel, chart.
- `lib/messages.ts`: server and web message types and parsing. Mirrors `contract/web/README.md`; change both together.
- `lib/use-robot.ts`: connects to the server (or the fake robot) and keeps the last 10 s of telemetry.

## Open-source libraries

Next.js, React, Tailwind CSS, Geist (font), Vitest, ESLint and eslint-config-next. These also need to go in the root `README.md` before submission.

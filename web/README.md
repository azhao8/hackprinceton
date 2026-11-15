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

## Family app (`/family`)

The app for Mom's family: Miguel in 3D on Home, Send something, Check in, Mom's day, Manage (routines, family circle, preferences) and the possible-fall alert. It runs on seeded demo data in the browser (`lib/family/source.ts`, `DemoSource`); a server-backed source can implement the same `FamilySource` interface later.

```bash
npm run dev   # then http://localhost:3000/family
```

- **On an iPhone:** same Wi-Fi as the laptop, open `http://<laptop-ip>:3000/family` in Safari, then Share → Add to Home Screen. It opens full screen as "Miguel". `next.config.ts` lets the dev server run its JavaScript for the laptop's own network addresses; if you switch networks, restart the dev server. Recording a voice note needs HTTPS (`npx next dev --experimental-https`); everything else works over plain http.
- **For filming or the demo,** run the production build instead (faster, no dev badge): `npm run build && npx next start -p 3000`.
- **Demo controls (hidden):** long-press Miguel's status in the top left, press `d` on a keyboard, or add `?demo` to the URL. Set his state (with Mom, delivering, charging, listening, night-light, idle, offline), choose whether Mom says yes to a check-in, trigger a possible fall, or reset the day.
- **Miguel:** `components/family/miguel/`. `MiguelModel.tsx` rebuilds the robot from John's CAD (the GLB) as a character; `face.ts` draws his face on the phone screen; `voice.ts` plays his lines and moves his mouth from each line's loudness envelope. Drag to turn him, tap to hear him.
- **His voice:** `node --env-file=<file with CARTESIA_API_KEY> scripts/voice.mjs` regenerates the lines in `scripts/voice.mjs` with Cartesia's "Corey" voice (the intro video's) into `public/family/voice/`; `--say` makes a macOS stand-in instead.

## Open-source libraries

Next.js, React, Tailwind CSS, Geist (font), Vitest, ESLint and eslint-config-next. The family app adds three.js, React Three Fiber, drei, and the Fraunces, Figtree and DM Mono fonts (SIL Open Font License, via Google Fonts). Miguel's voice is generated with Cartesia (a service, not a library). These also need to go in the root `README.md` before submission.

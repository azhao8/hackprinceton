# web/

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

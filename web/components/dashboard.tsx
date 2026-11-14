"use client";

import { HISTORY_S, SERVER_WS_URL, radToDeg, useRobot, type Connection } from "@/lib/use-robot";
import { EStopPanel } from "./estop-panel";
import { LineChart } from "./line-chart";

const STALE_MS = 1000;

export function Dashboard() {
  const robot = useRobot();
  const tel = robot.telemetry;
  const ageMs = robot.lastAt === null ? null : robot.now - robot.lastAt;
  const stale = robot.connection !== "sample" && (ageMs === null || ageMs > STALE_MS);

  return (
    <main className="mx-auto flex w-full max-w-6xl flex-col gap-4 p-4 sm:p-6">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">Miguel.exe</h1>
          <p className="text-sm text-muted">Dashboard</p>
        </div>
        <ConnectionBadge connection={robot.connection} stale={stale} />
      </header>

      <div className="grid gap-4 lg:grid-cols-[1fr_320px]">
        <section aria-label="Telemetry" className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <Stat label="State" value={tel?.state ?? "—"} />
          <Stat label="Battery" value={fmt(tel?.batt, 2)} unit="V" />
          <Stat label="Fault" value={tel ? (tel.fault ?? "none") : "—"} danger={!!tel?.fault} />
          <Stat label="Last update" value={ageMs === null ? "—" : `${Math.round(ageMs)}`} unit="ms ago" />
          <Stat label="Pitch" value={fmt(tel && radToDeg(tel.pitch), 1)} unit="°" />
          <Stat label="Tilt rate" value={fmt(tel && radToDeg(tel.rate), 1)} unit="°/s" />
          <Stat label="Left wheel" value={fmt(tel?.vl, 2)} unit="m/s" />
          <Stat label="Right wheel" value={fmt(tel?.vr, 2)} unit="m/s" />
        </section>
        <EStopPanel active={robot.estop} sendFailed={robot.sendFailed} onChange={robot.setEStop} />
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <LineChart
          title="Pitch"
          unit="°"
          samples={robot.history}
          series={[{ key: "pitchDeg", label: "pitch", color: "var(--accent)" }]}
          now={robot.now}
          windowS={HISTORY_S}
          minRange={5}
        />
        <LineChart
          title="Wheel speed"
          unit="m/s"
          samples={robot.history}
          series={[
            { key: "vl", label: "left", color: "var(--series-2)" },
            { key: "vr", label: "right", color: "var(--series-3)" },
          ]}
          now={robot.now}
          windowS={HISTORY_S}
          minRange={0.5}
        />
      </div>

      <section
        aria-label="Joystick"
        className="flex min-h-28 items-center justify-center rounded-lg border border-dashed border-line p-4 text-sm text-muted"
      >
        Joystick goes here (next task).
      </section>
    </main>
  );
}

function ConnectionBadge({ connection, stale }: { connection: Connection; stale: boolean }) {
  const { label, tone } = describe(connection, stale);
  const dot = { ok: "bg-ok", warn: "bg-warn", danger: "bg-danger", neutral: "bg-muted" }[tone];
  return (
    <div className="flex items-center gap-2 rounded-full border border-line bg-panel px-3 py-1.5 text-sm" role="status">
      <span className={`h-2 w-2 rounded-full ${dot}`} aria-hidden />
      <span>{label}</span>
      {SERVER_WS_URL && <span className="hidden font-mono text-xs text-muted sm:inline">{SERVER_WS_URL}</span>}
    </div>
  );
}

function describe(connection: Connection, stale: boolean): { label: string; tone: "ok" | "warn" | "danger" | "neutral" } {
  switch (connection) {
    case "sample":
      return { label: "Sample telemetry (no server)", tone: "neutral" };
    case "connecting":
      return { label: "Connecting…", tone: "warn" };
    case "open":
      return stale ? { label: "Connected, no telemetry", tone: "warn" } : { label: "Live", tone: "ok" };
    case "closed":
      return { label: "Disconnected, retrying", tone: "danger" };
  }
}

function Stat({ label, value, unit, danger }: { label: string; value: string; unit?: string; danger?: boolean }) {
  return (
    <div className="rounded-lg border border-line bg-panel p-3">
      <div className="text-xs text-muted">{label}</div>
      <div className={`mt-1 font-mono text-lg tabular-nums ${danger ? "text-danger" : ""}`}>
        {value}
        {unit && value !== "—" && <span className="ml-1 text-xs text-muted">{unit}</span>}
      </div>
    </div>
  );
}

function fmt(value: number | null | undefined, digits: number): string {
  return value === undefined || value === null ? "—" : value.toFixed(digits);
}

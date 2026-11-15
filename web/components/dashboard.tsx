"use client";

import { useEffect, useRef, useState } from "react";
import { HISTORY_S, SERVER_WS_URL, useRobot, type Connection } from "@/lib/use-robot";
import type { ClientMessage, FollowSettings, KeyLetter } from "@/lib/messages";
import { EStopPanel } from "./estop-panel";
import { LineChart } from "./line-chart";

const STALE_MS = 1000;
const DRIVE_HZ = 20;
const RANGES: Record<FollowSettings["mode"], [number, number]> = { person: [0.25, 0.65], yellow: [0.2, 0.6] };
const SAY_PRESETS = ["Hi, I'm Miguel!", "Time for your medicine.", "Here is your water.", "Follow me!", "Hello, judges!"];
const ARM_CONFIRM =
  "Start balancing (g)?\n\nSomeone must be holding the robot upright, within about 6°, ready to let go once it holds itself.";

type Dir = "U" | "D" | "L" | "R";
const KEY_DIR: Record<string, Dir> = { w: "U", arrowup: "U", s: "D", arrowdown: "D", a: "L", arrowleft: "L", d: "R", arrowright: "R" };

/** The laptop's control page (decision 0053): every control for the robot, plus live telemetry. */
export function Dashboard() {
  const robot = useRobot();
  const { send } = robot;
  const tel = robot.telemetry;
  const status = robot.status;
  const ageMs = robot.lastAt === null ? null : robot.now - robot.lastAt;
  const stale = robot.connection !== "sample" && (ageMs === null || ageMs > STALE_MS);

  const [vmax, setVmax] = useState(0.3);
  const [wmax, setWmax] = useState(1.0);
  const [held, setHeld] = useState<Set<Dir>>(new Set());
  const heldRef = useRef(held);
  const speedRef = useRef({ vmax, wmax });

  const key = (letter: KeyLetter) => send({ t: "key", letter });
  const arm = () => {
    if (window.confirm(ARM_CONFIRM)) send({ t: "arm" });
  };
  const stopHold = () => {
    heldRef.current = new Set();
    setHeld(new Set());
    send({ t: "joystick", v: 0, w: 0 });
    key("5");
  };
  const toggleFollow = () => send({ t: "follow", on: !(status?.follow ?? false) });

  // Keyboard: John's drive.py keys. Held WASD/arrows drive; the rest are one-shot.
  const actions = useRef<Record<string, () => void>>({});
  useEffect(() => {
    // The key handlers below read these through refs, so they always see the latest values.
    speedRef.current = { vmax, wmax };
    actions.current = { q: () => key("L"), e: () => key("R"), p: () => key("P"), x: () => key("x"), g: arm, f: toggleFollow, " ": stopHold };
  });
  useEffect(() => {
    const typing = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement | null;
      return !!el && (el.tagName === "INPUT" || el.tagName === "TEXTAREA" || el.tagName === "SELECT");
    };
    const down = (e: KeyboardEvent) => {
      if (typing(e) || e.metaKey || e.ctrlKey) return;
      const k = e.key.toLowerCase();
      const dir = KEY_DIR[k];
      if (dir) {
        e.preventDefault();
        if (!heldRef.current.has(dir)) {
          heldRef.current = new Set(heldRef.current).add(dir);
          setHeld(heldRef.current);
        }
      } else if (!e.repeat && actions.current[k]) {
        e.preventDefault();
        actions.current[k]();
      }
    };
    const up = (e: KeyboardEvent) => {
      const dir = KEY_DIR[e.key.toLowerCase()];
      if (!dir) return;
      const next = new Set(heldRef.current);
      next.delete(dir);
      heldRef.current = next;
      setHeld(next);
      if (next.size === 0) send({ t: "joystick", v: 0, w: 0 });
    };
    const blur = () => {
      if (heldRef.current.size) send({ t: "joystick", v: 0, w: 0 });
      heldRef.current = new Set();
      setHeld(new Set());
    };
    window.addEventListener("keydown", down);
    window.addEventListener("keyup", up);
    window.addEventListener("blur", blur);
    const tick = setInterval(() => {
      const h = heldRef.current;
      if (h.size === 0) return; // nothing held: the server's joystick request goes stale and the robot holds
      const { vmax: v, wmax: w } = speedRef.current;
      send({ t: "joystick", v: v * ((h.has("U") ? 1 : 0) - (h.has("D") ? 1 : 0)), w: w * ((h.has("L") ? 1 : 0) - (h.has("R") ? 1 : 0)) });
    }, 1000 / DRIVE_HZ);
    return () => {
      window.removeEventListener("keydown", down);
      window.removeEventListener("keyup", up);
      window.removeEventListener("blur", blur);
      clearInterval(tick);
    };
  }, [send]);

  const pressDir = (dir: Dir, on: boolean) => {
    const next = new Set(heldRef.current);
    if (on) next.add(dir);
    else next.delete(dir);
    heldRef.current = next;
    setHeld(next);
    if (!on && next.size === 0) send({ t: "joystick", v: 0, w: 0 });
  };

  return (
    <main className="mx-auto flex w-full max-w-7xl flex-col gap-4 p-4 sm:p-6">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Miguel.exe</h1>
          <p className="text-sm text-muted">Control page · keys work anywhere on this page</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <ConnectionBadge connection={robot.connection} stale={stale} />
          <Badge tone={status?.link ? "ok" : "danger"}>
            Robot link {status ? (status.link ? "ok" : "down") : "?"}
            {status?.lag_ms != null && ` · ${Math.round(status.lag_ms)} ms`}
          </Badge>
          <Badge tone={tel?.state === "idle" ? "muted" : "ok"}>{tel?.state ?? "no telemetry"}</Badge>
        </div>
      </header>

      {robot.sendFailed && (
        <p role="alert" className="rounded-md border border-danger bg-danger/10 px-3 py-2 text-sm font-medium text-danger">
          Not sent: no connection to the server ({SERVER_WS_URL}). Is <code>python -m app</code> running?
        </p>
      )}

      <div className="grid gap-4 lg:grid-cols-[1fr_1fr_340px]">
        <Card title="Drive" hint="Hold W A S D or the arrows · Space stops and holds">
          <div className="flex flex-wrap items-center gap-6">
            <div className="grid grid-cols-3 gap-2">
              <span />
              <PadKey label="W" on={held.has("U")} onPress={(on) => pressDir("U", on)} />
              <span />
              <PadKey label="A" on={held.has("L")} onPress={(on) => pressDir("L", on)} />
              <PadKey label="S" on={held.has("D")} onPress={(on) => pressDir("D", on)} />
              <PadKey label="D" on={held.has("R")} onPress={(on) => pressDir("R", on)} />
            </div>
            <div className="flex flex-1 flex-col gap-3">
              <Slider label="Top speed" unit="m/s" min={0.1} max={0.6} step={0.05} value={vmax} onChange={setVmax} />
              <Slider label="Turn rate" unit="rad/s" min={0.5} max={1.5} step={0.25} value={wmax} onChange={setWmax} />
            </div>
          </div>
          <div className="mt-4 flex flex-wrap gap-2">
            <Action k="Space" onClick={stopHold}>Stop &amp; hold</Action>
            <Action k="Q" onClick={() => key("L")}>Turn 90° left</Action>
            <Action k="E" onClick={() => key("R")}>Turn 90° right</Action>
            <Action onClick={() => key("F")}>50 cm forward</Action>
            <Action onClick={() => key("B")}>50 cm back</Action>
          </div>
        </Card>

        <div className="flex flex-col gap-4">
          <Card title="Robot">
            <div className="grid grid-cols-3 gap-2">
              <Action k="G" tone="ok" onClick={arm}>Start balancing</Action>
              <Action k="P" onClick={() => key("P")}>Park</Action>
              <Action k="X" tone="danger" onClick={() => key("x")}>Motors off</Action>
            </div>
            <p className="mt-3 text-xs text-muted">
              Start only while someone holds it upright. Park leans it onto the kickstand. Motors off drops it: catch it.
            </p>
          </Card>
          <FollowCard
            follow={status?.follow ?? false}
            skill={status?.skill ?? null}
            settings={status?.settings ?? null}
            serverVision={status?.vision?.mode === "server"}
            send={send}
            onToggle={toggleFollow}
          />
        </div>

        <EStopPanel active={status?.estop ?? false} sendFailed={false} onChange={(on) => send({ t: "estop", on })} />
      </div>

      <CameraCard status={status} />

      <div className="grid gap-4 lg:grid-cols-[1fr_340px]">
        <section aria-label="Telemetry" className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <Stat label="Pitch" value={fmt(tel?.pitch, 1)} unit="°" />
          <Stat label="Tilt rate" value={fmt(tel?.rate, 0)} unit="°/s" />
          <Stat label="Distance" value={fmt(tel?.x, 2)} unit="m" />
          <Stat label="Heading" value={fmt(tel?.yaw, 0)} unit="°" />
          <Stat label="Left wheel" value={fmt(tel?.vl, 2)} unit="m/s" />
          <Stat label="Right wheel" value={fmt(tel?.vr, 2)} unit="m/s" />
          <Stat label="Battery" value={fmt(tel?.batt, 1)} unit="V" />
          <Stat label="Fault" value={tel ? (tel.fault ?? "none") : "—"} danger={!!tel?.fault} />
        </section>
        <SayCard send={send} />
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <LineChart title="Pitch" unit="°" samples={robot.history} now={robot.now} windowS={HISTORY_S} minRange={5}
          series={[{ key: "pitch", label: "pitch", color: "var(--accent)" }]} />
        <LineChart title="Wheel speed" unit="m/s" samples={robot.history} now={robot.now} windowS={HISTORY_S} minRange={0.5}
          series={[
            { key: "vl", label: "left", color: "var(--series-2)" },
            { key: "vr", label: "right", color: "var(--series-3)" },
          ]} />
      </div>
    </main>
  );
}

function FollowCard({ follow, skill, settings, serverVision, send, onToggle }: {
  follow: boolean; skill: string | null; settings: FollowSettings | null; serverVision: boolean;
  send: (m: ClientMessage) => boolean; onToggle: () => void;
}) {
  const [draft, setDraft] = useState<FollowSettings | null>(null);
  const shown = draft ?? settings;
  const set = (s: Partial<FollowSettings>) => {
    if (!shown) return;
    setDraft({ ...shown, ...s });
    send({ t: "settings", ...s });
    setTimeout(() => setDraft(null), 800);
  };
  const range = shown ? RANGES[shown.mode] : [0.25, 0.65];
  return (
    <Card title="Follow" hint={serverVision ? "The server sees and follows · settings apply when Follow starts" : "The phone tracks"}>
      <div className="flex items-center justify-between gap-3">
        <span className={`text-sm font-semibold ${follow ? "text-ok" : "text-muted"}`}>
          {follow ? "Following" : skill ? `Server skill: ${skill}` : "Off"}
        </span>
        <Action k="F" tone={follow ? "danger" : "ok"} onClick={onToggle}>{follow ? "Follow off" : "Follow on"}</Action>
      </div>
      {shown ? (
        <div className="mt-3 flex flex-col gap-3">
          <div className="flex gap-2">
            <select value={shown.mode} onChange={(e) => set({ mode: e.target.value as FollowSettings["mode"] })}
              className="flex-1 rounded-md border border-line bg-background px-2 py-1.5 text-sm">
              <option value="person">Follow a person</option>
              {!serverVision && <option value="yellow">Follow something yellow</option>}
            </select>
            <button type="button" onClick={() => set({ voice: !shown.voice })}
              className="rounded-md border border-line bg-background px-3 py-1.5 text-sm">
              Voice {shown.voice ? "on" : "off"}
            </button>
          </div>
          <Slider label="Follow speed cap" unit="m/s" min={0.1} max={0.45} step={0.05} value={shown.speed}
            onChange={(v) => set({ speed: v })} />
          <Slider label="Stop distance (bigger = closer)" unit="" min={range[0]} max={range[1]} step={0.05}
            value={shown.distance} onChange={(v) => set({ distance: v })} />
        </div>
      ) : (
        <p className="mt-3 text-sm text-muted">Waiting for the server…</p>
      )}
    </Card>
  );
}

/** The server's view: the phone's camera with the server's boxes, target and command drawn on it. */
function CameraCard({ status }: { status: import("@/lib/messages").Status | null }) {
  const vision = status?.vision ?? null;
  const httpBase = SERVER_WS_URL.replace(/^ws(s?):/, "http$1:").replace(/\/ws$/, "");
  const age = vision?.camera?.age_s ?? null;
  const live = age !== null && age < 2;
  return (
    <Card title="What Miguel sees" hint="The phone's camera, with the server's tracking drawn on it">
      {vision?.mode === "server" ? (
        <div className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_280px]">
          {/* eslint-disable-next-line @next/next/no-img-element -- MJPEG stream, not an optimizable image */}
          <img src={`${httpBase}/video.mjpg`} alt="Live view from the robot's phone"
            className="max-h-[60vh] w-full rounded-lg bg-black object-contain" />
          <div className="flex flex-col gap-2 text-sm">
            <Badge tone={live ? "ok" : "danger"}>
              Camera {live ? `live · ${vision.camera?.frames ?? 0} frames` : age === null ? "no frames yet" : `stalled ${age.toFixed(0)} s`}
            </Badge>
            <p className="text-muted">Vision: {vision.status ?? "—"}</p>
            {!live && (
              <p className="text-muted">
                Open the phone page on the robot&apos;s iPhone and tap Start. It streams the camera here.
              </p>
            )}
          </div>
        </div>
      ) : (
        <p className="text-sm text-muted">
          {vision ? "The phone is tracking on its own (no video sent to the server)." : "Waiting for the server…"}
        </p>
      )}
    </Card>
  );
}

function SayCard({ send }: { send: (m: ClientMessage) => boolean }) {
  const [text, setText] = useState("");
  const say = (t: string) => t.trim() && send({ t: "say", text: t.trim() });
  return (
    <Card title="Say" hint="Spoken by the phone on the robot">
      <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); say(text); setText(""); }}>
        <input value={text} onChange={(e) => setText(e.target.value)} placeholder="Type a line, press Enter"
          className="min-w-0 flex-1 rounded-md border border-line bg-background px-3 py-2 text-sm" />
        <button type="submit" className="rounded-md bg-accent px-3 py-2 text-sm font-medium text-white">Say</button>
      </form>
      <div className="mt-3 flex flex-wrap gap-1.5">
        {SAY_PRESETS.map((p) => (
          <button key={p} type="button" onClick={() => say(p)}
            className="rounded-full border border-line bg-background px-3 py-1 text-xs hover:border-accent">{p}</button>
        ))}
      </div>
    </Card>
  );
}

function Card({ title, hint, children }: { title: string; hint?: string; children: React.ReactNode }) {
  return (
    <section aria-label={title} className="rounded-xl border border-line bg-panel p-4 shadow-sm">
      <div className="mb-3 flex items-baseline justify-between gap-2">
        <h2 className="font-semibold">{title}</h2>
        {hint && <span className="text-xs text-muted">{hint}</span>}
      </div>
      {children}
    </section>
  );
}

function PadKey({ label, on, onPress }: { label: string; on: boolean; onPress: (on: boolean) => void }) {
  return (
    <button type="button" aria-pressed={on}
      onPointerDown={(e) => { e.currentTarget.setPointerCapture(e.pointerId); onPress(true); }}
      onPointerUp={() => onPress(false)} onPointerCancel={() => onPress(false)}
      className={`h-14 w-14 select-none rounded-lg border text-lg font-semibold transition ${
        on ? "border-accent bg-accent text-white" : "border-line bg-background"}`}>
      {label}
    </button>
  );
}

function Action({ children, onClick, k, tone }: {
  children: React.ReactNode; onClick: () => void; k?: string; tone?: "ok" | "danger";
}) {
  const color = tone === "ok" ? "border-ok text-ok" : tone === "danger" ? "border-danger text-danger" : "border-line";
  return (
    <button type="button" onClick={onClick}
      className={`flex items-center justify-center gap-2 rounded-lg border bg-background px-3 py-2 text-sm font-medium hover:bg-panel ${color}`}>
      {children}
      {k && <kbd className="rounded border border-line px-1.5 text-[10px] text-muted">{k}</kbd>}
    </button>
  );
}

function Slider({ label, unit, min, max, step, value, onChange }: {
  label: string; unit: string; min: number; max: number; step: number; value: number; onChange: (v: number) => void;
}) {
  return (
    <label className="flex flex-col gap-1 text-sm">
      <span className="flex justify-between text-muted">
        <span>{label}</span>
        <span className="font-mono text-foreground">{value.toFixed(2)} {unit}</span>
      </span>
      <input type="range" min={min} max={max} step={step} value={value} onChange={(e) => onChange(+e.target.value)}
        className="accent-[var(--accent)]" />
    </label>
  );
}

function Badge({ tone, children }: { tone: "ok" | "danger" | "muted"; children: React.ReactNode }) {
  const cls = tone === "ok" ? "border-ok text-ok" : tone === "danger" ? "border-danger text-danger" : "border-line text-muted";
  return <span className={`rounded-full border px-3 py-1 text-xs font-medium ${cls}`}>{children}</span>;
}

function ConnectionBadge({ connection, stale }: { connection: Connection; stale: boolean }) {
  if (connection === "sample") return <Badge tone="muted">Sample robot</Badge>;
  if (connection === "open") return <Badge tone={stale ? "danger" : "ok"}>Server {stale ? "· no telemetry" : "connected"}</Badge>;
  return <Badge tone="danger">Server {connection === "connecting" ? "connecting…" : "disconnected"}</Badge>;
}

function Stat({ label, value, unit, danger }: { label: string; value: string; unit?: string; danger?: boolean }) {
  return (
    <div className="rounded-xl border border-line bg-panel p-3 shadow-sm">
      <div className="text-xs text-muted">{label}</div>
      <div className={`mt-1 truncate font-mono text-lg ${danger ? "text-danger" : ""}`}>
        {value}
        {unit && value !== "—" && <span className="ml-1 text-xs text-muted">{unit}</span>}
      </div>
    </div>
  );
}

function fmt(v: number | null | undefined, digits: number): string {
  return v === null || v === undefined ? "—" : v.toFixed(digits);
}

"use client";

import { useEffect, useRef, useState } from "react";
import { HISTORY_S, SERVER_WS_URL, useRobot, type Connection } from "@/lib/use-robot";
import type { AgentEvent, ClientMessage, FollowSettings, KeyLetter, MemoryView } from "@/lib/messages";
import { LineChart } from "./line-chart";

const STALE_MS = 1000;
const DRIVE_HZ = 20;
const RANGES: Record<FollowSettings["mode"], [number, number]> = { person: [0.1, 1.0], yellow: [0.1, 1.0] };
const SAY_PRESETS = ["Hi, I'm Miguel!", "Time for your medicine.", "Here is your water.", "Follow me!", "Hello, judges!"];
const CUT_CONFIRM = "Cut motor power?\n\nThe robot stops balancing and drops. Use STOP unless that isn't enough.";
/** The firmware's default balance angle (balance.ino `trim`), before any shift from this page. */
const FIRMWARE_TRIM = -3.65;
const TRIM_STEP = 0.25;
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
  // STOP: all movement stops (driving, turns, follow) and stays stopped until Resume; it keeps balancing.
  const stop = () => {
    heldRef.current = new Set();
    setHeld(new Set());
    send({ t: "estop", on: true });
  };
  const resume = () => send({ t: "estop", on: false });
  const stopped = status?.estop ?? false;
  const toggleFollow = () => send({ t: "follow", on: !(status?.follow ?? false) });

  // Keyboard: John's drive.py keys. Held WASD/arrows drive; the rest are one-shot.
  const actions = useRef<Record<string, () => void>>({});
  useEffect(() => {
    // The key handlers below read these through refs, so they always see the latest values.
    speedRef.current = { vmax, wmax };
    actions.current = { q: () => key("L"), e: () => key("R"), p: () => key("P"), x: () => key("x"), g: arm, f: toggleFollow, " ": stop };
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
          <div className="mt-1 flex flex-wrap items-center gap-2">
            <ConnectionBadge connection={robot.connection} stale={stale} />
            <Badge tone={status?.link ? "ok" : "danger"}>
              Robot {status ? (status.link ? "connected" : "not connected") : "?"}
              {status?.lag_ms != null && ` · ${Math.round(status.lag_ms)} ms`}
            </Badge>
            <Badge tone={tel?.state === "idle" ? "muted" : "ok"}>{stateLabel(tel?.state)}</Badge>
            {tel?.fault && <Badge tone="danger">Last stop: {tel.fault}</Badge>}
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Action k="G" tone="ok" onClick={arm}>Start</Action>
          <Action k="P" onClick={() => key("P")}>Park</Action>
          {stopped ? (
            <button type="button" onClick={resume}
              className="h-14 rounded-xl bg-ok px-8 text-lg font-bold text-white shadow-sm hover:opacity-90">
              Resume
            </button>
          ) : (
            <button type="button" onClick={stop}
              className="h-14 rounded-xl bg-danger px-10 text-lg font-bold tracking-wide text-white shadow-sm hover:bg-danger-strong">
              STOP <kbd className="ml-2 rounded border border-white/40 px-1.5 text-xs font-normal">Space</kbd>
            </button>
          )}
        </div>
      </header>

      {stopped && (
        <p role="status" className="rounded-md border border-danger bg-danger/10 px-3 py-2 text-sm font-medium text-danger">
          Stopped. Driving and follow are blocked; the robot keeps balancing. Press Resume to drive again.
        </p>
      )}
      {robot.sendFailed && (
        <p role="alert" className="rounded-md border border-danger bg-danger/10 px-3 py-2 text-sm font-medium text-danger">
          Not sent: no connection to the server ({SERVER_WS_URL}). Is <code>python -m app</code> running?
        </p>
      )}

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
        <CameraCard status={status} send={send} />
        <div className="flex flex-col gap-4">
          <Card title="Drive" hint="Hold W A S D or the arrows">
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
                <Slider label="Top speed" unit="m/s" min={0.1} max={3.2} step={0.05} value={vmax} onChange={setVmax} />
                <Slider label="Turn rate" unit="rad/s" min={0.5} max={1.5} step={0.25} value={wmax} onChange={setWmax} />
              </div>
            </div>
            <div className="mt-4 flex flex-wrap gap-2">
              <Action k="Q" onClick={() => key("L")}>Turn 90° left</Action>
              <Action k="E" onClick={() => key("R")}>Turn 90° right</Action>
            </div>
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
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <MiguelCard events={robot.agent} listening={status?.listening ?? false} send={send} />
        <MemoryCard memory={robot.memory} send={send} />
      </div>

      <SayCard send={send} />

      <TrimCard shift={status?.trim_shift ?? 0} pitch={tel?.pitch ?? null} rate={tel?.rate ?? null}
        balancing={tel?.state === "balance" || tel?.state === "drive"} send={send} />

      <details className="rounded-xl border border-line bg-panel p-4 shadow-sm">
        <summary className="cursor-pointer font-semibold">Details: telemetry and charts</summary>
        <div className="mt-4 flex flex-col gap-4">
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
          <div className="grid gap-4 lg:grid-cols-2">
            <LineChart title="Pitch" unit="°" samples={robot.history} now={robot.now} windowS={HISTORY_S} minRange={5}
              series={[{ key: "pitch", label: "pitch", color: "var(--accent)" }]} />
            <LineChart title="Wheel speed" unit="m/s" samples={robot.history} now={robot.now} windowS={HISTORY_S} minRange={0.5}
              series={[
                { key: "vl", label: "left", color: "var(--series-2)" },
                { key: "vr", label: "right", color: "var(--series-3)" },
              ]} />
          </div>
          <div className="flex flex-wrap items-center gap-3 border-t border-line pt-4">
            <span className="text-sm font-semibold text-danger">Emergency</span>
            <Action k="X" tone="danger" onClick={() => { if (window.confirm(CUT_CONFIRM)) key("x"); }}>Cut motor power</Action>
            <span className="text-xs text-muted">The robot drops. Only if STOP isn&apos;t enough; catch it.</span>
          </div>
        </div>
      </details>
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
          <Slider label="Follow speed cap" unit="m/s" min={0.05} max={3.2} step={0.05} value={shown.speed}
            onChange={(v) => set({ speed: v })} />
          <Slider label="Closeness (bigger = stops closer)" unit="" min={range[0]} max={range[1]} step={0.05}
            value={shown.distance} onChange={(v) => set({ distance: v })} />
        </div>
      ) : (
        <p className="mt-3 text-sm text-muted">Waiting for the server…</p>
      )}
    </Card>
  );
}

/** The server's view: the phone's camera with the server's boxes, target and command drawn on it. */
function CameraCard({ status, send }: { status: import("@/lib/messages").Status | null; send: (m: ClientMessage) => boolean }) {
  const camera = status?.settings.camera ?? "back";
  const mirror = status?.settings.mirror ?? false;
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
            <div className="flex gap-2">
              {(["back", "front"] as const).map((side) => (
                <button key={side} type="button" onClick={() => send({ t: "settings", camera: side })}
                  className={`flex-1 rounded-md border px-3 py-1.5 ${camera === side ? "border-accent bg-accent text-white" : "border-line bg-background"}`}>
                  {side === "back" ? "Back camera" : "Front camera"}
                </button>
              ))}
            </div>
            <label className="flex items-center gap-2">
              <input type="checkbox" checked={mirror} onChange={(e) => send({ t: "settings", mirror: e.target.checked })} />
              Mirror (if left and right look swapped)
            </label>
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

const AGENT_LABEL: Record<string, string> = {
  heard: "Heard", say: "Miguel says", reply: "To family", plan: "Plan", step: "Step", task: "Task",
  check_in: "Check-in", place: "Learned place", error: "Error",
};

/** The voice agent: talk to Miguel as the operator, watch what he hears, says and does. */
function MiguelCard({ events, listening, send }: { events: AgentEvent[]; listening: boolean; send: (m: ClientMessage) => boolean }) {
  const [text, setText] = useState("");
  const shown = events.filter((e) => e.kind !== "step").slice(-10).reverse();
  return (
    <Card title="Miguel (voice agent)" hint="Mom talks to him by saying “Miguel”; you can type here">
      <div className="mb-2">
        <Badge tone={listening ? "ok" : "muted"}>{listening ? "● Listening" : "Not listening"}</Badge>
      </div>
      <form className="flex gap-2" onSubmit={(e) => {
        e.preventDefault();
        if (text.trim()) send({ t: "agent_message", text: text.trim() });
        setText("");
      }}>
        <input value={text} onChange={(e) => setText(e.target.value)} placeholder="“Bring Mom water”, “follow me”…"
          className="min-w-0 flex-1 rounded-md border border-line bg-background px-3 py-2 text-sm" />
        <button type="submit" className="rounded-md bg-accent px-3 py-2 text-sm font-medium text-white">Send</button>
      </form>
      <div className="mt-3 flex flex-wrap gap-2">
        <Action tone="ok" onClick={() => send({ t: "tray_loaded" })}>Tray loaded</Action>
        <Action tone="danger" onClick={() => { if (window.confirm("Raise a test fall alert? The family app turns red and Miguel checks on her.")) send({ t: "test_fall" }); }}>
          Test fall alert
        </Action>
      </div>
      <ul className="mt-3 flex max-h-64 flex-col gap-1.5 overflow-y-auto text-sm">
        {shown.length === 0 && <li className="text-muted">Nothing yet. With ANTHROPIC_API_KEY set, his events show here.</li>}
        {shown.map((e) => (
          <li key={e.id} className="rounded-md border border-line px-2 py-1">
            <span className="mr-2 text-xs font-semibold text-muted">{AGENT_LABEL[e.kind] ?? e.kind}</span>
            {e.text || (Array.isArray(e.data.steps) ? (e.data.steps as string[]).join(" → ") : "")}
          </li>
        ))}
      </ul>
    </Card>
  );
}

/** What Miguel knows (SQLite on the server): people by sight, places (sign cards), facts. */
function MemoryCard({ memory, send }: { memory: MemoryView | null; send: (m: ClientMessage) => boolean }) {
  const [person, setPerson] = useState("");
  const [fact, setFact] = useState({ key: "", value: "" });
  const [place, setPlace] = useState({ name: "", marker: "" });
  const input = "min-w-0 flex-1 rounded-md border border-line bg-background px-2 py-1.5 text-sm";
  const del = "text-xs text-danger hover:underline";
  return (
    <Card title="Memory" hint="What Miguel knows; kept across restarts">
      {!memory ? <p className="text-sm text-muted">Waiting for the server…</p> : (
        <div className="flex flex-col gap-4 text-sm">
          <section>
            <h3 className="mb-1 font-medium">People he knows by sight</h3>
            <ul className="mb-2 flex flex-wrap gap-2">
              {memory.people.length === 0 && <li className="text-muted">Nobody yet.</li>}
              {memory.people.map((n) => (
                <li key={n} className="rounded-full border border-line px-2 py-0.5">
                  {n} <button type="button" className={del} onClick={() => send({ t: "memory_set", what: "person", action: "delete", name: n })}>forget</button>
                </li>
              ))}
            </ul>
            <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); if (person.trim()) send({ t: "this_is", name: person.trim() }); setPerson(""); }}>
              <input value={person} onChange={(e) => setPerson(e.target.value)} placeholder="Name of the person in front of him" className={input} />
              <button type="submit" className="rounded-md border border-line px-3 py-1.5">Save look</button>
            </form>
          </section>
          <section>
            <h3 className="mb-1 font-medium">Places (sign cards)</h3>
            <ul className="mb-2 flex flex-col gap-1">
              {memory.places.map((p) => (
                <li key={p.name} className="flex items-baseline justify-between gap-2">
                  <span>{p.name} <span className="text-muted">{p.marker !== null ? `· marker ${p.marker}` : "· no marker"}{p.aliases.length ? ` · ${p.aliases.join(", ")}` : ""}</span></span>
                  <button type="button" className={del} onClick={() => send({ t: "memory_set", what: "place", action: "delete", name: p.name })}>delete</button>
                </li>
              ))}
            </ul>
            <form className="flex gap-2" onSubmit={(e) => {
              e.preventDefault();
              if (place.name.trim()) send({ t: "memory_set", what: "place", name: place.name.trim(), marker: place.marker.trim() ? Number(place.marker) : null });
              setPlace({ name: "", marker: "" });
            }}>
              <input value={place.name} onChange={(e) => setPlace({ ...place, name: e.target.value })} placeholder="water station" className={input} />
              <input value={place.marker} onChange={(e) => setPlace({ ...place, marker: e.target.value })} placeholder="marker #" inputMode="numeric" className="w-24 rounded-md border border-line bg-background px-2 py-1.5 text-sm" />
              <button type="submit" className="rounded-md border border-line px-3 py-1.5">Save</button>
            </form>
          </section>
          <section>
            <h3 className="mb-1 font-medium">Facts</h3>
            <ul className="mb-2 flex flex-col gap-1">
              {memory.facts.length === 0 && <li className="text-muted">Nothing yet.</li>}
              {memory.facts.map((f) => (
                <li key={f.key} className="flex items-baseline justify-between gap-2">
                  <span><span className="font-medium">{f.key}:</span> {f.value} <span className="text-xs text-muted">({f.source})</span></span>
                  <button type="button" className={del} onClick={() => send({ t: "memory_set", what: "fact", action: "delete", key: f.key })}>delete</button>
                </li>
              ))}
            </ul>
            <form className="flex gap-2" onSubmit={(e) => {
              e.preventDefault();
              if (fact.key.trim()) send({ t: "memory_set", what: "fact", key: fact.key.trim(), value: fact.value.trim() });
              setFact({ key: "", value: "" });
            }}>
              <input value={fact.key} onChange={(e) => setFact({ ...fact, key: e.target.value })} placeholder="evening pills" className={input} />
              <input value={fact.value} onChange={(e) => setFact({ ...fact, value: e.target.value })} placeholder="blue bottle, 8 pm" className={input} />
              <button type="submit" className="rounded-md border border-line px-3 py-1.5">Save</button>
            </form>
          </section>
        </div>
      )}
    </Card>
  );
}

/** The balance angle (trim): the tilt the robot treats as upright. Live changes (firmware t / y) last until it reboots. */
function TrimCard({ shift, pitch, rate, balancing, send }: {
  shift: number; pitch: number | null; rate: number | null; balancing: boolean; send: (m: ClientMessage) => boolean;
}) {
  const now = FIRMWARE_TRIM + shift;
  const [target, setTarget] = useState("");
  const goal = Number.parseFloat(target);
  const steps = Number.isFinite(goal) ? Math.round((goal - now) / TRIM_STEP) : 0;
  return (
    <Card title="Balance angle (trim)" hint={`Firmware default ${fmtSigned(FIRMWARE_TRIM)}°; changes here last until the robot reboots`}>
      <div className="flex flex-wrap items-center gap-x-6 gap-y-3">
        <div className="text-sm">
          Target <span className="font-mono text-lg">{fmtSigned(now)}°</span>
          <span className="ml-2 text-xs text-muted">(shifted {fmtSigned(shift)}° from here)</span>
          <div className="text-xs text-muted">Tilt now: {pitch === null ? "—" : `${fmtSigned(pitch)}°`}
            {rate !== null && Math.abs(rate) > 3 && !balancing && (
              <span className="ml-2 font-medium text-danger">Tilt sensor drifting ({Math.round(rate)}°/s while still?): recalibrate</span>
            )}
          </div>
        </div>
        <div className="flex gap-2">
          <Action onClick={() => send({ t: "trim", steps: -1 })}>−0.25°</Action>
          <Action onClick={() => send({ t: "trim", steps: 1 })}>+0.25°</Action>
          <Action onClick={() => {
            if (!balancing && window.confirm("Recalibrate the tilt sensor?\n\nLay the robot down so it can't move and don't touch it for 3 s. Not while it balances."))
              send({ t: "recalibrate" });
          }}>Recalibrate tilt sensor</Action>
        </div>
        <form className="flex items-center gap-2" onSubmit={(e) => {
          e.preventDefault();
          if (steps !== 0 && !balancing) send({ t: "trim", steps });
          setTarget("");
        }}>
          <label className="text-sm" htmlFor="trim-target">Set to</label>
          <input id="trim-target" value={target} onChange={(e) => setTarget(e.target.value)} inputMode="decimal"
            placeholder="-3.2" className="w-20 rounded-md border border-line bg-background px-2 py-1.5 text-sm" />
          <span className="text-sm">°</span>
          <button type="submit" disabled={balancing || steps === 0}
            className="rounded-md bg-accent px-3 py-1.5 text-sm font-medium text-white disabled:opacity-40">Apply</button>
        </form>
      </div>
      <p className="mt-2 text-xs text-muted">
        {balancing
          ? "Balancing: only ±0.25° steps. Stop it to set a new angle."
          : "Lean forward (battery side) is +. Find the angle by balancing it on a fingertip, motors off, and reading Tilt now."}
      </p>
    </Card>
  );
}

function fmtSigned(x: number): string {
  return `${x > 0 ? "+" : x < 0 ? "−" : ""}${Math.abs(x).toFixed(2)}`;
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

function stateLabel(state: string | undefined): string {
  if (state === "balance") return "Balancing";
  if (state === "drive") return "Moving";
  if (state === "idle") return "Motors off / parked";
  return "No robot data";
}

function fmt(v: number | null | undefined, digits: number): string {
  return v === null || v === undefined ? "—" : v.toFixed(digits);
}

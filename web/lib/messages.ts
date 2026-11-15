// Server <-> web messages over the server's WebSocket (server/app/api, contract/web/README.md).
// Robot telemetry follows contract v1 (contract/README.md): angles in DEGREES.

/** Robot telemetry, forwarded by the server as-is from the robot (contract v1). */
export interface Telemetry {
  t: "tel";
  /** Tilt, degrees, + leaning forward (battery side). */
  pitch: number;
  /** Tilt rate, degrees per second. */
  rate: number;
  /** Left and right wheel speed, m/s. */
  vl: number;
  vr: number;
  /** Battery voltage, V; null until the robot measures it. */
  batt: number | null;
  /** idle | balance | drive */
  state: string;
  /** Why the motors last turned off (free text), or null. */
  fault: string | null;
  /** Distance driven since starting to balance, m. */
  x?: number;
  /** Heading since starting to balance, degrees, + left. */
  yaw?: number;
  /** seq of the last command the robot received. */
  ack?: number;
}

export interface FollowSettings {
  mode: "person" | "yellow";
  speed: number;
  distance: number;
  voice: boolean;
  /** Which phone camera: back (default) or front (the screen faces the person). */
  camera?: "back" | "front";
  /** Flip the phone's frames left-right before vision (front cameras can send mirrored frames). */
  mirror?: boolean;
}

/** Who does the seeing: "server" (the phone streams its camera; Alex's design) or "phone" (the phone tracks). */
export interface VisionInfo {
  mode: "server" | "phone";
  status: string | null;
  /** Frames from the phone: how many so far and seconds since the last one. */
  camera: { frames: number; age_s: number | null } | null;
}

/** The server's own state, about twice a second. */
export interface Status {
  t: "status";
  follow: boolean;
  link: boolean;
  estop: boolean;
  settings: FollowSettings;
  lag_ms: number | null;
  skill: string | null;
  vision: VisionInfo | null;
  /** Degrees the balance angle was shifted from this server (0 after a server restart; lost on a robot reboot). */
  trim_shift: number;
}

/** One of the voice agent's events (contract/web/README.md, "Agent"): heard, say, reply, plan, step, task, check_in... */
export interface AgentEvent {
  t: "agent";
  id: number;
  kind: string;
  text: string;
  to: string | null;
  data: Record<string, unknown>;
}

export interface Place {
  name: string;
  marker: number | null;
  aliases: string[];
  description: string;
}

/** What Miguel knows (SQLite), for the memory page. */
export interface MemoryView {
  t: "memory";
  on: boolean;
  people: string[];
  places: Place[];
  facts: { key: string; value: string; source: string }[];
}

export type ServerMessage = Telemetry | Status | AgentEvent | MemoryView;

/** One-letter robot commands the control page may send (contract/README.md). Never g: see "arm". */
export type KeyLetter = "x" | "P" | "5" | "L" | "R" | "F" | "B";

export type ClientMessage =
  | { t: "estop"; on: boolean }
  | { t: "joystick"; v: number; w: number }
  | { t: "follow"; on: boolean }
  | { t: "say"; text: string }
  | { t: "settings"; mode?: FollowSettings["mode"]; speed?: number; distance?: number; voice?: boolean; camera?: "back" | "front"; mirror?: boolean }
  | { t: "key"; letter: KeyLetter }
  | { t: "arm" }
  | { t: "trim"; steps: number }
  | { t: "recalibrate" }
  | { t: "agent_message"; text: string }
  | { t: "tray_loaded" }
  | { t: "test_fall" }
  | { t: "this_is"; name: string }
  | { t: "memory_get" }
  | { t: "memory_set"; what: "fact" | "place" | "person"; action?: "delete"; key?: string; value?: string;
      name?: string; marker?: number | null; aliases?: string; description?: string };

const num = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);
const optNum = (v: unknown) => v === undefined || num(v);

function parseTelemetry(m: Record<string, unknown>): Telemetry | null {
  if (!(["pitch", "rate", "vl", "vr"] as const).every((k) => num(m[k]))) return null;
  if (!(m.batt === null || num(m.batt))) return null;
  if (typeof m.state !== "string" || !(m.fault === null || typeof m.fault === "string")) return null;
  if (!optNum(m.x) || !optNum(m.yaw) || !optNum(m.ack)) return null;
  const tel: Telemetry = {
    t: "tel",
    pitch: m.pitch as number,
    rate: m.rate as number,
    vl: m.vl as number,
    vr: m.vr as number,
    batt: m.batt as number | null,
    state: m.state,
    fault: m.fault as string | null,
  };
  if (num(m.x)) tel.x = m.x;
  if (num(m.yaw)) tel.yaw = m.yaw;
  if (num(m.ack)) tel.ack = m.ack;
  return tel;
}

function parseSettings(v: unknown): FollowSettings | null {
  if (typeof v !== "object" || v === null) return null;
  const s = v as Record<string, unknown>;
  if ((s.mode !== "person" && s.mode !== "yellow") || !num(s.speed) || !num(s.distance) || typeof s.voice !== "boolean")
    return null;
  const out: FollowSettings = { mode: s.mode, speed: s.speed, distance: s.distance, voice: s.voice };
  if (s.camera === "back" || s.camera === "front") out.camera = s.camera;
  if (typeof s.mirror === "boolean") out.mirror = s.mirror;
  return out;
}

function parseVision(v: unknown): VisionInfo | null {
  if (typeof v !== "object" || v === null) return null;
  const x = v as Record<string, unknown>;
  if (x.mode !== "server" && x.mode !== "phone") return null;
  let camera: VisionInfo["camera"] = null;
  if (typeof x.camera === "object" && x.camera !== null) {
    const c = x.camera as Record<string, unknown>;
    if (num(c.frames)) camera = { frames: c.frames, age_s: num(c.age_s) ? c.age_s : null };
  }
  return { mode: x.mode, status: typeof x.status === "string" ? x.status : null, camera };
}

function parseStatus(m: Record<string, unknown>): Status | null {
  const settings = parseSettings(m.settings);
  if (!settings || typeof m.follow !== "boolean" || typeof m.link !== "boolean" || typeof m.estop !== "boolean")
    return null;
  return {
    t: "status",
    follow: m.follow,
    link: m.link,
    estop: m.estop,
    settings,
    lag_ms: num(m.lag_ms) ? m.lag_ms : null,
    skill: typeof m.skill === "string" ? m.skill : null,
    vision: parseVision(m.vision),
    trim_shift: num(m.trim_shift) ? m.trim_shift : 0,
  };
}

/**
 * Parse one message from the server. Returns null for anything malformed or of a type the page
 * doesn't know, so new message types never crash it.
 */
export function parseServerMessage(raw: string): ServerMessage | null {
  let value: unknown;
  try {
    value = JSON.parse(raw);
  } catch {
    return null;
  }
  if (typeof value !== "object" || value === null || Array.isArray(value)) return null;
  const m = value as Record<string, unknown>;
  if (m.t === "tel") return parseTelemetry(m);
  if (m.t === "status") return parseStatus(m);
  if (m.t === "agent") return parseAgent(m);
  if (m.t === "memory") return parseMemory(m);
  return null;
}

function parseAgent(m: Record<string, unknown>): AgentEvent | null {
  if (!num(m.id) || typeof m.kind !== "string") return null;
  const data = typeof m.data === "object" && m.data !== null && !Array.isArray(m.data) ? (m.data as Record<string, unknown>) : {};
  return { t: "agent", id: m.id, kind: m.kind, text: typeof m.text === "string" ? m.text : "",
    to: typeof m.to === "string" ? m.to : null, data };
}

function parseMemory(m: Record<string, unknown>): MemoryView | null {
  const arr = (v: unknown): unknown[] => (Array.isArray(v) ? v : []);
  const str = (v: unknown): string => (typeof v === "string" ? v : "");
  const places: Place[] = arr(m.places).flatMap((p) => {
    if (typeof p !== "object" || p === null) return [];
    const r = p as Record<string, unknown>;
    if (typeof r.name !== "string") return [];
    return [{ name: r.name, marker: num(r.marker) ? r.marker : null, aliases: arr(r.aliases).filter((a): a is string => typeof a === "string"),
      description: str(r.description) }];
  });
  const facts = arr(m.facts).flatMap((f) => {
    if (typeof f !== "object" || f === null) return [];
    const r = f as Record<string, unknown>;
    return typeof r.key === "string" ? [{ key: r.key, value: str(r.value), source: str(r.source) }] : [];
  });
  return { t: "memory", on: m.on === true, people: arr(m.people).filter((p): p is string => typeof p === "string"), places, facts };
}

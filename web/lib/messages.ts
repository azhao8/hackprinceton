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
}

export type ServerMessage = Telemetry | Status;

/** One-letter robot commands the control page may send (contract/README.md). Never g: see "arm". */
export type KeyLetter = "x" | "P" | "5" | "L" | "R" | "F" | "B";

export type ClientMessage =
  | { t: "estop"; on: boolean }
  | { t: "joystick"; v: number; w: number }
  | { t: "follow"; on: boolean }
  | { t: "say"; text: string }
  | { t: "settings"; mode?: FollowSettings["mode"]; speed?: number; distance?: number; voice?: boolean }
  | { t: "key"; letter: KeyLetter }
  | { t: "arm" };

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
  return { mode: s.mode, speed: s.speed, distance: s.distance, voice: s.voice };
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
  return null;
}

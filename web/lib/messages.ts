// Server <-> web messages. Mirrors the draft in contract/web/README.md;
// change both together.

/**
 * Robot telemetry, forwarded by the server as-is from the robot contract.
 * SI units (decision 0046); the dashboard converts to degrees for display.
 */
export interface Telemetry {
  t: "tel";
  /** Tilt, radians. Sign and axes are set by the robot contract (REP 103). */
  pitch: number;
  /** Tilt rate, rad/s. */
  rate: number;
  /** Left and right wheel speed, m/s. */
  vl: number;
  vr: number;
  /** Battery voltage, V. */
  batt: number;
  /** Robot state, e.g. idle | balance | drive | kickstand. */
  state: string;
  /** Fault name, or null when healthy. */
  fault: string | null;
}

export type ServerMessage = Telemetry;

/** E-stop: on=true zeroes speed and turn but keeps balancing (decision 0043). */
export interface EStopMessage {
  t: "estop";
  on: boolean;
}

export type ClientMessage = EStopMessage;

const NUMERIC_TEL_FIELDS = ["pitch", "rate", "vl", "vr", "batt"] as const;

function isTelemetry(value: Record<string, unknown>): value is Record<string, unknown> & Telemetry {
  return (
    value.t === "tel" &&
    NUMERIC_TEL_FIELDS.every((k) => typeof value[k] === "number" && Number.isFinite(value[k])) &&
    typeof value.state === "string" &&
    (value.fault === null || typeof value.fault === "string")
  );
}

/**
 * Parse one message from the server. Returns null for anything malformed or
 * of a type the dashboard doesn't know yet, so new message types never crash it.
 */
export function parseServerMessage(raw: string): ServerMessage | null {
  let value: unknown;
  try {
    value = JSON.parse(raw);
  } catch {
    return null;
  }
  if (typeof value !== "object" || value === null || Array.isArray(value)) return null;
  const msg = value as Record<string, unknown>;
  if (isTelemetry(msg)) {
    return {
      t: "tel",
      pitch: msg.pitch,
      rate: msg.rate,
      vl: msg.vl,
      vr: msg.vr,
      batt: msg.batt,
      state: msg.state,
      fault: msg.fault,
    };
  }
  return null;
}

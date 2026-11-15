// Where the family app gets its data (see web/.env.example).
//
// Default: the Python server's family WebSocket (contract/web/family.md). `?demo` in the URL,
// or NEXT_PUBLIC_FAMILY_SOURCE=demo, runs the seeded demo day in the browser instead.

/** Set at build time, so the server's prerender and the browser agree on it. */
export const DEMO_BY_ENV = process.env.NEXT_PUBLIC_FAMILY_SOURCE === "demo";

/** The weekend's one shared family token (FAMILY_TOKEN in the server's .env; T-22 makes them per person). */
export const FAMILY_TOKEN = process.env.NEXT_PUBLIC_FAMILY_TOKEN ?? "";

/** Demo source? `search` is the page's query string ("?demo"), or null on the server. */
export function wantsDemo(search: string | null, byEnv = DEMO_BY_ENV): boolean {
  return byEnv || (search !== null && new URLSearchParams(search).has("demo"));
}

/**
 * The family WebSocket. NEXT_PUBLIC_FAMILY_WS_URL wins; otherwise the server on the host that
 * served this page: ws://<host>:8080/family/ws, or wss://<host>:8443/family/ws when the page is
 * https (browsers block ws:// from an https page).
 */
export function familyWsUrl(
  page: { protocol: string; hostname: string },
  envUrl: string | undefined = process.env.NEXT_PUBLIC_FAMILY_WS_URL,
): string {
  if (envUrl) return envUrl;
  const secure = page.protocol === "https:";
  return `${secure ? "wss" : "ws"}://${page.hostname}:${secure ? 8443 : 8080}/family/ws`;
}

/** The server's HTTP origin for media (`/family/media/<id>`): same host and port as the WebSocket. */
export function mediaOrigin(wsUrl: string): string {
  const u = new URL(wsUrl);
  return `${u.protocol === "wss:" ? "https:" : "http:"}//${u.host}`;
}

/** A media path from the server, made absolute against its origin. Absolute and data: URLs pass through. */
export function resolveMedia(path: string, origin: string): string {
  if (/^(https?:|data:|blob:)/.test(path)) return path;
  return new URL(path, `${origin}/`).toString();
}

/**
 * Demo step lengths for filming, from NEXT_PUBLIC_DEMO_TIMING (JSON of milliseconds, e.g.
 * {"loading":1400,"onTheWay":2900}). Anything missing or not a number keeps its default.
 */
export function demoTiming(raw: string | undefined = process.env.NEXT_PUBLIC_DEMO_TIMING): Record<string, number> {
  if (!raw) return {};
  try {
    const parsed: unknown = JSON.parse(raw);
    if (!parsed || typeof parsed !== "object") return {};
    return Object.fromEntries(Object.entries(parsed).filter(([, v]) => typeof v === "number" && Number.isFinite(v) && v >= 0));
  } catch {
    return {};
  }
}

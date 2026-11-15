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

/** The port `npm run dev:https` serves the family app on (package.json). */
export const HTTPS_APP_PORT = 3443;

/**
 * Where this page can use the camera and mic, for the check-in call (#118): browsers only give them to
 * https pages and localhost. Null when this page already can; otherwise the same path on the https
 * dev server (`npm run dev:https`) on the same host.
 */
export function cameraPageUrl(page: { protocol: string; hostname: string; pathname: string; search?: string }): string | null {
  if (page.protocol === "https:") return null;
  if (page.hostname === "localhost" || page.hostname === "127.0.0.1" || page.hostname === "[::1]") return null;
  return `https://${page.hostname}:${HTTPS_APP_PORT}${page.pathname}${page.search ?? ""}`;
}

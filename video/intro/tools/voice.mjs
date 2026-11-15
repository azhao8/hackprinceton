// Generates Miguel's three lines with Cartesia (voice "Corey — Supportive Buddy").
//   CARTESIA_API_KEY=sk_car_... node tools/voice.mjs        (or put CARTESIA_API_KEY in video/intro/.env)
// Writes public/audio/voice/line1.wav, line2.wav, line3.wav. The key is read from the environment only and never printed.
//
//   node tools/voice.mjs --placeholder
// Writes a clearly labelled stand-in (macOS `say`, NOT Corey) to public/audio/voice-placeholder/, for timing reviews only.
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const timeline = JSON.parse(fs.readFileSync(path.join(root, "src/timeline.json"), "utf8"));
const lines = Object.entries(timeline.voice); // [["line1", {text}], ...]

const VOICE_ID = "630ed21c-2c5c-41cf-9d82-10a7fd668370"; // Corey — Supportive Buddy
const MODEL = process.env.CARTESIA_MODEL || "sonic-3.6";
const VERSION = process.env.CARTESIA_VERSION || "2026-08-14";

const readKey = () => {
  if (process.env.CARTESIA_API_KEY) return process.env.CARTESIA_API_KEY.trim();
  const envFile = path.join(root, ".env");
  if (fs.existsSync(envFile)) {
    const m = fs.readFileSync(envFile, "utf8").match(/^\s*CARTESIA_API_KEY\s*=\s*"?([^"\n]+)"?/m);
    if (m) return m[1].trim();
  }
  return null;
};

if (process.argv.includes("--placeholder")) {
  const out = path.join(root, "public/audio/voice-placeholder");
  fs.mkdirSync(out, { recursive: true });
  for (const [key, { text }] of lines) {
    const aiff = path.join(out, `${key}.aiff`);
    execFileSync("say", ["-v", "Daniel", "-r", "240", "-o", aiff, text]);
    execFileSync("ffmpeg", ["-y", "-loglevel", "error", "-i", aiff, "-ar", "48000", "-ac", "1", path.join(out, `${key}.wav`)]);
    fs.rmSync(aiff);
    console.log(`placeholder ${key}: "${text}"`);
  }
  process.exit(0);
}

const key = readKey();
if (!key) {
  console.error(
    "CARTESIA_API_KEY is not set. Add it to video/intro/.env (git-ignored) as CARTESIA_API_KEY=..., or export it, then run again.",
  );
  process.exit(1);
}

const out = path.join(root, "public/audio/voice");
fs.mkdirSync(out, { recursive: true });
for (const [name, { text }] of lines) {
  const res = await fetch("https://api.cartesia.ai/tts/bytes", {
    method: "POST",
    headers: { Authorization: `Bearer ${key}`, "Cartesia-Version": VERSION, "Content-Type": "application/json" },
    body: JSON.stringify({
      model_id: MODEL,
      transcript: text,
      voice: { id: VOICE_ID },
      output_format: { container: "wav", encoding: "pcm_s16le", sample_rate: 48000 },
      language: "en",
    }),
  });
  if (!res.ok) {
    console.error(`Cartesia returned ${res.status} for ${name}: ${(await res.text()).slice(0, 300)}`);
    process.exit(1);
  }
  const raw = path.join(out, `${name}.raw.wav`);
  fs.writeFileSync(raw, Buffer.from(await res.arrayBuffer()));
  // Cartesia streams the WAV, so its header has no length; rewrite it with a proper one
  execFileSync("ffmpeg", ["-y", "-loglevel", "error", "-i", raw, "-c:a", "pcm_s16le", "-ar", "48000", path.join(out, `${name}.wav`)]);
  fs.rmSync(raw);
  console.log(`Corey ${name}: "${text}"`);
}

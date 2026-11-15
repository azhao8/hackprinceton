// Miguel's narration with Cartesia, voice "Corey — Supportive Buddy" (the intro's voice), with
// word and phoneme timings for the narrator bubble's lip sync.
//
//   node --env-file=.env tools/voice.mjs [id ...]     (.env holds CARTESIA_API_KEY; git-ignored)
//
// Writes public/audio/voice/<id>.wav (48 kHz mono) and <id>.json ({ words, phonemes } with
// start/end seconds). The key is read from the environment and never printed. Needs ffmpeg.
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const { lines } = JSON.parse(fs.readFileSync(path.join(root, "src/narration.json"), "utf8"));
const VOICE_ID = "630ed21c-2c5c-41cf-9d82-10a7fd668370"; // Corey — Supportive Buddy
const MODEL = process.env.CARTESIA_MODEL || "sonic-3.6";
const VERSION = process.env.CARTESIA_VERSION || "2026-08-14";
const key = process.env.CARTESIA_API_KEY?.trim();
if (!key) {
  console.error("No CARTESIA_API_KEY. Put it in video/showcase/.env (git-ignored) and run: node --env-file=.env tools/voice.mjs");
  process.exit(1);
}
const only = process.argv.slice(2);
const out = path.join(root, "public/audio/voice");
fs.mkdirSync(out, { recursive: true });

for (const line of lines) {
  if (only.length && !only.includes(line.id)) continue;
  const res = await fetch("https://api.cartesia.ai/tts/sse", {
    method: "POST",
    headers: { Authorization: `Bearer ${key}`, "Cartesia-Version": VERSION, "Content-Type": "application/json" },
    body: JSON.stringify({
      model_id: MODEL,
      transcript: line.text,
      voice: { mode: "id", id: VOICE_ID },
      output_format: { container: "raw", encoding: "pcm_s16le", sample_rate: 48000 },
      language: "en",
      add_timestamps: true,
      add_phoneme_timestamps: true,
    }),
  });
  if (!res.ok) {
    console.error(`Cartesia returned ${res.status} for ${line.id}: ${(await res.text()).slice(0, 300)}`);
    process.exit(1);
  }
  const events = (await res.text())
    .split("\n")
    .filter((l) => l.startsWith("data:"))
    .map((l) => JSON.parse(l.slice(5)));
  const pcm = [];
  const words = [];
  const phonemes = [];
  for (const e of events) {
    if (e.type === "chunk" && e.data) pcm.push(Buffer.from(e.data, "base64"));
    if (e.type === "timestamps" && e.word_timestamps) {
      const w = e.word_timestamps;
      w.words.forEach((t, i) => words.push({ text: t, start: w.start[i], end: w.end[i] }));
    }
    if (e.type === "phoneme_timestamps" && e.phoneme_timestamps) {
      const p = e.phoneme_timestamps;
      p.phonemes.forEach((t, i) => phonemes.push({ p: t, start: p.start[i], end: p.end[i] }));
    }
  }
  const raw = path.join(out, `${line.id}.raw`);
  fs.writeFileSync(raw, Buffer.concat(pcm));
  execFileSync("ffmpeg", ["-y", "-loglevel", "error", "-f", "s16le", "-ar", "48000", "-ac", "1", "-i", raw, path.join(out, `${line.id}.wav`)]);
  fs.rmSync(raw);
  const seconds = Buffer.concat(pcm).length / 2 / 48000;
  fs.writeFileSync(path.join(out, `${line.id}.json`), JSON.stringify({ text: line.text, seconds, words, phonemes }, null, 1));
  console.log(`Corey ${line.id} ${seconds.toFixed(2)} s, ${words.length} words, ${phonemes.length} phonemes: "${line.text}"`);
}

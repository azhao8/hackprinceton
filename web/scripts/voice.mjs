// Generates Miguel's spoken lines for the family app, plus a loudness envelope per line
// so his mouth moves with the actual audio.
//
//   node --env-file=<file with CARTESIA_API_KEY> scripts/voice.mjs      Cartesia, voice "Corey — Supportive Buddy" (same as the intro video)
//   node scripts/voice.mjs --say                                        macOS `say` stand-in (not Corey), for timing only
//
// Writes public/family/voice/<id>.m4a and components/family/miguel/voice-envelopes.json.
// The API key is read from the environment and never printed. Needs ffmpeg.

import { execFileSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const LINES = {
  hello: "Hi Sarah! Margaret and I are having tea with Ruth.",
  hello2: "She's had a lovely day. We walked the whole garden!",
  onIt: "Got it! I'll bring it right over.",
  asking: "Margaret, Sarah would like to say hi. Is now a good time?",
  night: "Shh. We're just walking to the bathroom. All good.",
  charging: "Just topping up while she naps.",
};

const VOICE_ID = "630ed21c-2c5c-41cf-9d82-10a7fd668370"; // Corey — Supportive Buddy
const MODEL = process.env.CARTESIA_MODEL || "sonic-3.6";
const VERSION = process.env.CARTESIA_VERSION || "2026-08-14";
const FPS = 60;

const web = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const outDir = path.join(web, "public/family/voice");
const envFile = path.join(web, "components/family/miguel/voice-envelopes.json");
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "miguel-voice-"));
fs.mkdirSync(outDir, { recursive: true });

const useSay = process.argv.includes("--say");
const envelopesOnly = process.argv.includes("--envelopes-only"); // recompute from the saved .m4a files
const key = process.env.CARTESIA_API_KEY?.trim();
if (!useSay && !envelopesOnly && !key) {
  console.error("No CARTESIA_API_KEY in the environment. Pass --env-file=<file>, or use --say for a stand-in voice.");
  process.exit(1);
}

const ff = (...args) => execFileSync("ffmpeg", ["-y", "-loglevel", "error", ...args]);

async function synth(id, text) {
  const wav = path.join(tmp, `${id}.wav`);
  if (useSay) {
    const aiff = path.join(tmp, `${id}.aiff`);
    execFileSync("say", ["-v", "Samantha", "-r", "200", "-o", aiff, text]);
    ff("-i", aiff, "-ar", "48000", "-ac", "1", wav);
    return wav;
  }
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
  if (!res.ok) throw new Error(`Cartesia returned ${res.status} for ${id}: ${(await res.text()).slice(0, 200)}`);
  const raw = path.join(tmp, `${id}.raw.wav`);
  fs.writeFileSync(raw, Buffer.from(await res.arrayBuffer()));
  ff("-i", raw, "-c:a", "pcm_s16le", "-ar", "48000", "-ac", "1", wav); // fix the streamed header
  return wav;
}

/** Loudness per animation frame, 0..1. */
function envelope(wav) {
  const pcm = path.join(tmp, "env.pcm");
  ff("-i", wav, "-f", "s16le", "-ac", "1", "-ar", "16000", pcm);
  const buf = fs.readFileSync(pcm);
  const samples = new Int16Array(buf.buffer, buf.byteOffset, buf.length / 2);
  const per = 16000 / FPS;
  const rms = [];
  for (let f = 0; Math.floor(f * per) < samples.length; f++) {
    const start = Math.floor(f * per);
    const end = Math.min(samples.length, Math.floor((f + 1) * per));
    let sum = 0;
    for (let j = start; j < end; j++) sum += (samples[j] / 32768) ** 2;
    rms.push(Math.sqrt(sum / Math.max(1, end - start)));
  }
  // Normalize to this line's loud syllables, then curve it so the mouth opens and closes on syllables
  // instead of hanging open.
  const peak = [...rms].sort((a, b) => a - b)[Math.floor(rms.length * 0.92)] || 1;
  const levels = [];
  let smooth = 0;
  for (const r of rms) {
    const v = Math.min(1, r / peak) ** 1.6;
    smooth += (v - smooth) * (v > smooth ? 0.65 : 0.4);
    levels.push(Math.round(smooth * 100) / 100);
  }
  return levels;
}

const out = {};
for (const [id, text] of Object.entries(LINES)) {
  if (envelopesOnly) {
    out[id] = { text, fps: FPS, levels: envelope(path.join(outDir, `${id}.m4a`)) };
    console.log(`envelope ${id} (${(out[id].levels.length / FPS).toFixed(1)} s)`);
    continue;
  }
  const wav = await synth(id, text);
  // Trim leading silence so the mouth and the sound start together.
  const trimmed = path.join(tmp, `${id}.trim.wav`);
  ff("-i", wav, "-af", "silenceremove=start_periods=1:start_threshold=-50dB,apad=pad_dur=0.15", trimmed);
  ff("-i", trimmed, "-c:a", "aac", "-b:a", "96k", "-ac", "1", path.join(outDir, `${id}.m4a`));
  out[id] = { text, fps: FPS, levels: envelope(trimmed) };
  console.log(`${useSay ? "say (stand-in)" : "Corey"} ${id}: "${text}" (${(out[id].levels.length / FPS).toFixed(1)} s)`);
}
fs.writeFileSync(envFile, JSON.stringify(out) + "\n");
fs.rmSync(tmp, { recursive: true, force: true });

"""Original score + sound design for the Miguel intro, synthesized from scratch and synced to the timeline.

Inputs:  src/timeline.json, public/audio/motion.json (tools/export_motion.ts),
         optional voice lines in public/audio/voice/line{1,2,3}.wav (tools/voice.mjs)
Outputs: public/audio/mix.wav (+ stems: music.wav, sfx.wav, voice.wav)

Usage: uv run --with numpy --with scipy python tools/synth_audio.py [--voice-dir DIR] [--out NAME]
"""
import argparse, json, os
import numpy as np
import scipy.signal as sg
from scipy.io import wavfile

SR = 48000
ap = argparse.ArgumentParser()
ap.add_argument("--voice-dir", default="public/audio/voice")
ap.add_argument("--out", default="mix")
args = ap.parse_args()

T = json.load(open("src/timeline.json"))
M = json.load(open("public/audio/motion.json"))
DUR = T["duration"]
N = int((DUR + 0.6) * SR)
rng = np.random.default_rng(20261114)

def zeros(): return np.zeros((N, 2))
def tt(n): return np.arange(n) / SR
def at(t): return int(round(t * SR))
def db(x): return 10 ** (x / 20)

def sos_lp(fc, order=2): return sg.butter(order, fc, "low", fs=SR, output="sos")
def sos_hp(fc, order=2): return sg.butter(order, fc, "high", fs=SR, output="sos")
def sos_bp(lo, hi, order=2): return sg.butter(order, [lo, hi], "band", fs=SR, output="sos")
def filt(sos, x): return sg.sosfilt(sos, x, axis=0)

def place(buf, x, t0, gain=1.0, pan=0.0):
    """Add a mono (n,) or stereo (n,2) signal at time t0 with equal-power pan in [-1, 1]."""
    i = at(t0)
    if i >= N: return
    if x.ndim == 1:
        a = (pan + 1) * np.pi / 4
        x = np.stack([x * np.cos(a), x * np.sin(a)], axis=1)
    j = min(N, i + len(x))
    if i < 0:
        x = x[-i:]; j = min(N, len(x)); i = 0
    buf[i:j] += x[: j - i] * gain

def adsr(n, a, d, s, r):
    t = tt(n); tot = n / SR
    e = np.ones(n) * s
    e = np.where(t < a, t / max(a, 1e-4), e)
    e = np.where((t >= a) & (t < a + d), 1 - (1 - s) * (t - a) / max(d, 1e-4), e)
    rel = tot - r
    e = np.where(t >= rel, e * np.clip((tot - t) / max(r, 1e-4), 0, 1), e)
    return e

def reverb_ir(seconds, decay, lp=6000, seed=0):
    r = np.random.default_rng(seed)
    n = int(seconds * SR)
    t = tt(n)
    ir = r.standard_normal((n, 2)) * np.exp(-t / decay)[:, None]
    ir = filt(sos_lp(lp), ir)
    # darker tail
    ir[:, 0] *= np.exp(-t * 0.6); ir[:, 1] *= np.exp(-t * 0.6)
    ir[: int(0.012 * SR)] *= np.linspace(0, 1, int(0.012 * SR))[:, None]
    return ir / np.sqrt((ir ** 2).sum(axis=0).mean())

def convolve(x, ir):
    out = np.stack([sg.fftconvolve(x[:, c], ir[:, c])[:N] for c in range(2)], axis=1)
    return out

def note(f): return 440 * 2 ** ((f - 69) / 12)
NAMES = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
def n2f(name):
    pitch, octv = name[:-1], int(name[-1])
    semis = NAMES[pitch[0]] + (1 if "#" in pitch else -1 if "b" in pitch[1:] else 0)
    return note(12 * (octv + 1) + semis)

# ---------------------------------------------------------------- instruments
def pad_voice(f, dur, attack=1.0, release=1.2, bright=1100, detune=0.007):
    n = int((dur + release) * SR); t = tt(n)
    x = np.zeros(n)
    for k, d in enumerate((-detune, 0, detune)):
        ph = rng.uniform(0, 2 * np.pi)
        x += sg.sawtooth(2 * np.pi * f * (1 + d) * t + ph) * (0.8 if k != 1 else 1.0)
    x += 0.6 * np.sin(2 * np.pi * f * 0.5 * t)  # body
    lfo = 1 + 0.25 * np.sin(2 * np.pi * 0.11 * t + rng.uniform(0, 6))
    x = sg.sosfilt(sos_lp(min(bright, 9000)), x) * 0.6
    x = sg.sosfilt(sos_lp(min(bright * 1.4, 12000), 1), x) * lfo
    env = adsr(n, attack, 0.5, 0.85, release)
    return x * env

def chord(buf, names, t0, dur, gain, pan_spread=0.5, **kw):
    for i, nm in enumerate(names):
        f = n2f(nm)
        p = (i / max(1, len(names) - 1) - 0.5) * 2 * pan_spread
        g = gain * (0.8 if f > 400 else 1.0) * (0.6 if f > 700 else 1.0)
        place(buf, pad_voice(f, dur, **kw), t0, g, p)

def bell(f, dur=2.4, index=2.2, ratio=3.5, decay=1.1):
    n = int(dur * SR); t = tt(n)
    mod_env = np.exp(-t / (decay * 0.35))
    x = np.sin(2 * np.pi * f * t + index * mod_env * np.sin(2 * np.pi * f * ratio * t))
    x += 0.35 * np.sin(2 * np.pi * f * 2.01 * t) * np.exp(-t / (decay * 0.5))
    env = np.exp(-t / decay) * np.clip(t / 0.004, 0, 1)
    return x * env * 0.5

def marimba(f, dur=1.2):
    n = int(dur * SR); t = tt(n)
    x = np.sin(2 * np.pi * f * t) * np.exp(-t / 0.42)
    x += 0.35 * np.sin(2 * np.pi * f * 3.93 * t) * np.exp(-t / 0.07)
    x += 0.12 * np.sin(2 * np.pi * f * 9.2 * t) * np.exp(-t / 0.02)
    return x * np.clip(t / 0.0015, 0, 1) * 0.6

def noise(n, seed=None):
    r = rng if seed is None else np.random.default_rng(seed)
    return r.standard_normal(n)

def tick(freq=2600, dur=0.05, gain=1.0):
    n = int(dur * SR); t = tt(n)
    x = np.sin(2 * np.pi * freq * t) * np.exp(-t / 0.008)
    x += 0.5 * sg.sosfilt(sos_bp(2500, 7000), noise(n)) * np.exp(-t / 0.003)
    return x * gain

def whoosh(dur=0.35, lo=400, hi=3200, gain=1.0):
    n = int(dur * SR); t = tt(n)
    x = sg.sosfilt(sos_bp(lo, hi), noise(n))
    env = np.sin(np.pi * np.clip(t / dur, 0, 1)) ** 2
    return x * env * gain

# ---------------------------------------------------------------- MUSIC
music = zeros()
stat_in = [s["in"] for s in T["stats"]]
progression = [
    (["A2", "E3", "C4", "B4"], 0.0, stat_in[1] - 0.0 + 0.25),
    (["F2", "C3", "A3", "E4"], stat_in[1] - 0.1, stat_in[2] - stat_in[1] + 0.35),
    (["D2", "A2", "F3", "C4", "E4"], stat_in[2] - 0.1, T["darkStart"] - stat_in[2] + 0.1),
]
for names, t0, dur in progression:
    chord(music, names, t0, dur, gain=0.034, attack=0.9, release=0.9, bright=850)
# sub drone + high shimmer under the statistics
n = at(T["darkStart"] + 0.6); t = tt(n)
drone = np.sin(2 * np.pi * 55 * t) * np.clip(t / 1.5, 0, 1) * np.clip((T["darkStart"] + 0.6 - t) / 0.8, 0, 1)
place(music, drone, 0, 0.07)
shim = (np.sin(2 * np.pi * n2f("E6") * t) + 0.6 * np.sin(2 * np.pi * n2f("B6") * t)) * (0.5 + 0.5 * np.sin(2 * np.pi * 0.37 * t))
shim *= np.clip(t / 2.0, 0, 1) * np.clip((T["darkStart"] - t) / 0.6, 0, 1)
place(music, shim, 0, 0.007, 0.3)

# the wordmark: the harmony turns warm (vi-IV-ii resolves to I)
w0 = T["wordIn"]
chord(music, ["C2", "G2", "E3", "D4", "G4"], w0 - 0.05, 1.5, gain=0.038, attack=0.35, release=1.6, bright=1400)
for i, nm in enumerate(["C5", "G5", "D6"]):
    place(music, bell(n2f(nm), 2.6, index=1.4, decay=1.2), w0 + 0.03 + i * 0.07, 0.05 * (0.8 ** i), -0.2 + 0.2 * i)
# a light bed while Miguel is around (ducked later under his lines)
chord(music, ["C3", "G3", "E4"], T["enterStart"] - 0.2, T["windup"] - T["enterStart"] + 0.1, gain=0.026, attack=0.8, release=0.5, bright=1300)
# small musical punctuation
place(music, marimba(n2f("G5")), T["line1"] + T["voice"]["line1"]["dur"] + 0.06, 0.08, 0.2)
place(music, marimba(n2f("E5")), T["line1"] + T["voice"]["line1"]["dur"] + 0.17, 0.07, 0.25)
# after the settle: warm and a little proud
chord(music, ["F2", "C3", "A3", "E4"], T["slotEnd"] + 0.05, 1.5, gain=0.03, attack=0.5, release=0.9, bright=1300)
for i, nm in enumerate(["C5", "E5", "G5"]):
    place(music, marimba(n2f(nm)), T["line3"] + T["voice"]["line3"]["dur"] + 0.08 + i * 0.075, 0.06, -0.1 + 0.15 * i)
# thoughts: chimes on each appearance + a soft swell
chord(music, ["A2", "E3", "C4", "G4"], T["grandma"] - 0.2, T["lookBack"] - T["grandma"] + 0.3, gain=0.03, attack=0.7, release=0.8, bright=1400)
for t0, notes in ((T["grandma"], ["E6", "C6"]), (T["heart"], ["G6", "D6"]), (T["phone"], ["A6", "E6", "C7"])):
    for k, nm in enumerate(notes):
        place(music, bell(n2f(nm), 2.8, index=1.8, decay=1.3), t0 + 0.02 + k * 0.045, 0.045 * (0.7 ** k), 0.15 * (k - 1))
# resolution: plagal (IV -> I), warm and restrained
res = T["lookBack"]
chord(music, ["F2", "C3", "A3", "E4", "G4"], res, 0.75, gain=0.032, attack=0.35, release=0.6, bright=1200)
chord(music, ["C2", "G2", "E3", "B3", "D4", "G4"], res + 0.62, DUR - res, gain=0.034, attack=0.5, release=1.0, bright=1400)
for i, nm in enumerate(["G4", "C5", "E5", "G5"]):
    place(music, bell(n2f(nm), 3.2, index=1.1, decay=1.6), res + 0.66 + i * 0.09, 0.04 * (0.85 ** i), -0.3 + 0.2 * i)
place(music, np.sin(2 * np.pi * n2f("C2") * tt(at(2.2))) * np.exp(-tt(at(2.2)) / 0.9) * np.clip(tt(at(2.2)) / 0.02, 0, 1), res + 0.64, 0.035)
# the closing hold: a faint echo of the bells with the heart's last beat, over the sustained I chord
for i, nm in enumerate(["E5", "G5", "C6"]):
    place(music, bell(n2f(nm), 2.6, index=0.9, decay=1.3), T["idleBlink"] + 0.35 + i * 0.11, 0.024 * (0.85 ** i), 0.25 - 0.25 * i)

# ---------------------------------------------------------------- SFX
sfx = zeros()
# statistics: a soft tick + air on each roll, a lighter tick when the sentence lands
for k, t0 in enumerate(stat_in):
    place(sfx, tick(2400 - 200 * k, gain=1.0), t0 + 0.04, 0.12, 0)
    place(sfx, whoosh(0.32, 500, 2600), t0 - 0.12, 0.02, 0)
    place(sfx, tick(3400, 0.03), t0 + 0.14, 0.04, 0.1)
# wordmark letters settling: small, wooden, left to right
for i in range(6):
    t0 = T["wordIn"] + i * T["wordStagger"] + T["wordDur"] * 0.42
    n = at(0.12); t = tt(n)
    x = np.sin(2 * np.pi * (190 - i * 6) * t) * np.exp(-t / 0.035) + 0.3 * sg.sosfilt(sos_bp(1200, 4000), noise(n)) * np.exp(-t / 0.004)
    place(sfx, x, t0, 0.11, -0.55 + i * 0.22)

# Miguel's motors, driven by the wheel speed from the animation
hz = M["hz"]
w = np.array(M["w"]); lean = np.array(M["pitch"]); xs = np.array(M["x"])  # wheel speed rad/s, body pitch deg
tm = np.arange(len(w)) / hz
lr = np.abs(np.gradient(lean, 1 / hz))  # deg/s
ts = tt(N)
w_s = np.interp(ts, tm, w, right=0); lr_s = np.interp(ts, tm, lr, right=0)
pan_s = np.clip((np.interp(ts, tm, xs, right=960) - 960) / 960, -1, 1) * 0.75
w_s = filt(sos_lp(25, 1), w_s); lr_s = filt(sos_lp(12, 1), lr_s)
# far-away approach before he enters (faint, filtered)
approach = np.clip((ts - T["whirStart"]) / (T["enterStart"] - T["whirStart"]), 0, 1) * (ts < T["enterStart"] + 0.3)
w_eff = np.maximum(w_s, approach * 22)
f0 = np.minimum(92 + 4.0 * w_eff, 300)
phase = 2 * np.pi * np.cumsum(f0) / SR
motor = np.sin(phase) + 0.45 * np.sin(2 * phase) + 0.2 * np.sin(3 * phase + 0.4)
whine = np.sin(phase * 6.0) * 0.07 + np.sin(phase * 9.0) * 0.025
amp = np.clip(w_eff / 6, 0, 1) ** 1.2 * (0.35 + 0.65 * np.clip(w_eff / 40, 0, 1))
idle = np.clip(lr_s / 20, 0, 1) * 0.25 * (ts > T["enterStart"])  # balancing corrections
roll_noise = filt(sos_lp(320), noise(N)) * np.clip(w_eff / 30, 0, 1) * 0.35
motor_sig = (motor * 0.6 + whine) * (amp + idle) + roll_noise
motor_sig = filt(sos_lp(2600), motor_sig)
motor_sig = filt(sos_hp(70), motor_sig)
far = np.where(ts < T["enterStart"], np.clip((ts - T["whirStart"]) / 1.2, 0, 1) * 0.5, 1.0)
far_lp = filt(sos_lp(650), motor_sig)
motor_sig = np.where(ts < T["enterStart"] + 0.15, far_lp * far + motor_sig * far * 0.15, motor_sig)
a_ = (pan_s + 1) * np.pi / 4
# a held breath between the wind-up and the charge
breath = np.interp(ts, [T["charge"] - 0.12, T["charge"] - 0.06, T["charge"] + 0.02, T["charge"] + 0.08], [1, 0.05, 0.05, 1])
motor_sig *= breath
sfx += np.stack([motor_sig * np.cos(a_), motor_sig * np.sin(a_)], axis=1) * 0.05

# the curious chirp when he notices the I
def chirp(f1, f2, dur):
    n = at(dur); t = tt(n)
    f = f1 * (f2 / f1) ** (t / dur)
    x = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.sin(np.pi * t / dur) ** 0.6
    return x
place(sfx, np.concatenate([chirp(n2f("C6"), n2f("E6"), 0.07), np.zeros(at(0.03)), chirp(n2f("E6"), n2f("A6"), 0.09)]), T["notice"] + 0.02, 0.05, 0.35)
# the realisation: a tiny bloop
place(sfx, chirp(n2f("A5"), n2f("E5"), 0.09), T["realize"] - 0.06, 0.03, 0.35)

# impact: a satisfying mechanical bonk
imp = T["impact"]
n = at(0.5); t = tt(n)
body = (np.sin(2 * np.pi * 410 * t * (1 - 0.06 * t)) * np.exp(-t / 0.085)
        + 0.6 * np.sin(2 * np.pi * 1060 * t) * np.exp(-t / 0.045)
        + 0.35 * np.sin(2 * np.pi * 1720 * t) * np.exp(-t / 0.025)
        + 0.8 * np.sin(2 * np.pi * 125 * t) * np.exp(-t / 0.06))
click = sg.sosfilt(sos_hp(2500), noise(n)) * np.exp(-t / 0.0025)
place(sfx, body * 0.9 + click * 0.5, imp, 0.2, -0.25)
# the letter teetering on its edge: a soft scrape
place(sfx, sg.sosfilt(sos_bp(900, 3000), noise(at(0.28))) * np.hanning(at(0.28)), imp + 0.12, 0.015, -0.4)
# the grounded clunk from behind the ledge (muffled), plus a small bounce
land = M["landT"]
for k, (g, delay) in enumerate(((1.0, 0.0), (0.35, 0.13))):
    n = at(0.6); t = tt(n)
    x = (np.sin(2 * np.pi * 88 * t) * np.exp(-t / 0.16) + 0.7 * np.sin(2 * np.pi * 176 * t) * np.exp(-t / 0.07)
         + 0.4 * np.sin(2 * np.pi * 310 * t) * np.exp(-t / 0.04) + 0.6 * sg.sosfilt(sos_lp(700), noise(n)) * np.exp(-t / 0.02))
    x = sg.sosfilt(sos_lp(1400), x)
    place(sfx, x, land + delay, 0.13 * g, -0.45)

# ---------------------------------------------------------------- VOICE
voice = zeros()
voice_found = []
for key in ("line1", "line2", "line3"):
    path = os.path.join(args.voice_dir, f"{key}.wav")
    if not os.path.exists(path):
        continue
    sr, v = wavfile.read(path)
    v = v.astype(np.float64)
    if v.ndim > 1: v = v.mean(axis=1)
    v /= (np.abs(v).max() + 1e-9)
    if sr != SR: v = sg.resample_poly(v, SR, sr)
    # trim leading/trailing silence
    e = np.abs(v) > 0.02
    idx = np.where(e)[0]
    v = v[max(0, idx[0] - at(0.01)): idx[-1] + at(0.05)]
    v = filt(sos_hp(90), v)
    place(voice, v, T[key], 0.21, 0.15)
    voice_found.append((key, len(v) / SR))
    nxt = {"line1": T["notice"], "line2": T["windup"], "line3": T["lookUp"]}[key]
    if T[key] + len(v) / SR > nxt + 0.05:
        print(f"WARNING: {key} lasts {len(v)/SR:.2f}s and runs past the next beat at {nxt}s; adjust src/timeline.json")

# ---------------------------------------------------------------- MIX
ir_music = reverb_ir(3.2, 0.55, 5200, seed=1)
ir_room = reverb_ir(1.2, 0.18, 6500, seed=2)
music_w = music * 0.75 + convolve(music, ir_music) * 0.4
sfx_w = sfx + convolve(sfx, ir_room) * 0.18
voice_w = voice + convolve(voice, ir_room) * 0.08

# duck music and motors under Miguel's lines; hush before the impact
duck = np.ones(N)
for key in ("line1", "line2", "line3"):
    d = dict(voice_found).get(key, T["voice"][key]["dur"])
    s0, s1 = T[key] - 0.08, T[key] + d + 0.12
    duck = np.minimum(duck, np.interp(ts, [s0 - 0.08, s0, s1, s1 + 0.3], [1, db(-4.5), db(-4.5), 1]))
hush = np.interp(ts, [T["windup"] - 0.1, T["windup"] + 0.15, imp - 0.02, imp + 0.6], [1, 0.0, 0.0, 1])
music_w *= (duck * hush)[:, None]
sfx_w[:, :] *= np.where((ts >= T["line1"]) & (ts <= T["line3"] + 1.2), 0.75 + 0.25 * duck, 1)[:, None]

fade_end = np.clip((DUR - ts) / max(0.01, DUR - T["fadeOut"] - 0.1), 0, 1)
# level the bed (music + effects) the same way with or without dialogue, then lay the voice on top
bed = (music_w + sfx_w) * fade_end[:, None]
act = np.abs(bed).mean(axis=1) > 1e-4
g = db(-19.5) / np.sqrt((bed[act] ** 2).mean())
mix = filt(sos_hp(28), (music_w + sfx_w + voice_w) * fade_end[:, None]) * g
lim = db(-1.2)
mix = np.where(np.abs(mix) > lim * 0.7, np.sign(mix) * (lim * 0.7 + (lim * 0.3) * np.tanh((np.abs(mix) - lim * 0.7) / (lim * 0.3))), mix)
rms = np.sqrt((mix ** 2).mean())
print(f"peak {20*np.log10(np.abs(mix).max()):.2f} dBFS, rms {20*np.log10(rms):.1f} dBFS, voice lines: {voice_found or 'none'}")

def write(name, x):
    y = np.clip(x[: at(DUR)], -1, 1)
    wavfile.write(f"public/audio/{name}.wav", SR, (y * 32767).astype(np.int16))
write(args.out, mix)
prefix = "stem" if args.out == "mix" else f"{args.out}_stem"
write(f"{prefix}_music", music_w * fade_end[:, None] * g)
write(f"{prefix}_sfx", sfx_w * fade_end[:, None] * g)
if voice_found:
    write(f"{prefix}_voice", voice_w * fade_end[:, None] * g)

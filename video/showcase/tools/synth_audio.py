"""Sound for the showcase: Miguel's narration (Corey), soft UI sounds and a quiet bed, mixed.

All sounds are synthesized here from the event lists that tools/export_events.ts writes, so they
land on the exact frames of the taps, the handoff light, the delivery steps and the call.

  uv run --with numpy --with scipy python tools/synth_audio.py
    → public/audio/mix.wav (+ stem_voice / stem_sfx / stem_music.wav) and mix-<scene>.wav per clip
"""
import json
import numpy as np
import scipy.signal as sg
from scipy.io import wavfile

SR = 48000
rng = np.random.default_rng(7)


def db(x): return 10 ** (x / 20)
def tt(n): return np.arange(n) / SR
def at(t): return int(round(t * SR))
def note(m): return 440 * 2 ** ((m - 69) / 12)


def n2f(name):
    names = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
    s = names[name[0]] + (1 if "#" in name else -1 if name[1:2] == "b" else 0)
    return note(12 * (int(name[-1]) + 1) + s)


def place(buf, x, t0, gain=1.0, pan=0.0):
    i = at(t0)
    if i >= len(buf) or i + len(x) <= 0:
        return
    if x.ndim == 1:
        a = (pan + 1) * np.pi / 4
        x = np.stack([x * np.cos(a), x * np.sin(a)], axis=1)
    if i < 0:
        x, i = x[-i:], 0
    j = min(len(buf), i + len(x))
    buf[i:j] += x[: j - i] * gain


def bp(x, lo, hi, order=2): return sg.sosfilt(sg.butter(order, [lo, hi], "band", fs=SR, output="sos"), x)
def lp(x, fc, order=2): return sg.sosfilt(sg.butter(order, fc, "low", fs=SR, output="sos"), x)


# ---------------------------------------------------------------- sounds
def click(f=2300, dur=0.045):
    """A soft glassy tap: a tiny sine tick and a breath of filtered noise."""
    n = at(dur); t = tt(n)
    x = np.sin(2 * np.pi * f * t) * np.exp(-t / 0.006) * 0.6
    x += bp(rng.standard_normal(n), 1800, 6000) * np.exp(-t / 0.004) * 0.35
    return x * np.clip(t / 0.0008, 0, 1)


def bell(f, dur=1.6, decay=0.6, index=1.2):
    n = at(dur); t = tt(n)
    mod = index * np.exp(-t / (decay * 0.4)) * np.sin(2 * np.pi * f * 3.5 * t)
    x = np.sin(2 * np.pi * f * t + mod) + 0.3 * np.sin(2 * np.pi * f * 2.01 * t) * np.exp(-t / (decay * 0.5))
    return x * np.exp(-t / decay) * np.clip(t / 0.003, 0, 1) * 0.5


def pluck(f, dur=0.6):
    n = at(dur); t = tt(n)
    x = np.sin(2 * np.pi * f * t) * np.exp(-t / 0.16) + 0.25 * np.sin(2 * np.pi * f * 3.98 * t) * np.exp(-t / 0.03)
    return x * np.clip(t / 0.002, 0, 1) * 0.6


def swish(dur=0.32, lo=500, hi=4200):
    n = at(dur); t = tt(n)
    env = np.sin(np.pi * np.clip(t / dur, 0, 1)) ** 2
    return bp(rng.standard_normal(n), lo, hi) * env * 0.25


def shimmer(dur=0.42):
    """The handoff light: a soft rising glint that travels from the left phone to the right."""
    n = at(dur); t = tt(n); u = t / dur
    f = 900 * 2 ** (0.9 * u)
    ph = 2 * np.pi * np.cumsum(f) / SR
    x = (np.sin(ph) + 0.35 * np.sin(2 * ph) + 0.2 * np.sin(3.01 * ph)) * np.sin(np.pi * u) ** 1.5 * 0.35
    x += bp(rng.standard_normal(n), 3000, 9000) * np.sin(np.pi * u) ** 2 * 0.05
    a = (np.linspace(-0.45, 0.45, n) + 1) * np.pi / 4
    return np.stack([x * np.cos(a), x * np.sin(a)], axis=1)


def pad(freqs, dur, attack=0.8, release=1.2, bright=1500):
    n = at(dur + release); t = tt(n)
    x = np.zeros(n)
    for f in freqs:
        for d in (-0.004, 0.004):
            x += sg.sawtooth(2 * np.pi * f * (1 + d) * t + rng.uniform(0, 6.28)) * (0.7 if f > 500 else 1)
    x = lp(lp(x, bright), bright * 1.3, 1) * 0.12 / max(1, len(freqs))
    env = np.minimum(np.clip(t / attack, 0, 1), np.clip((dur + release - t) / release, 0, 1))
    return x * env


def reverb(x, seconds=1.6, decay=0.45, mix=0.18):
    n = at(seconds); t = tt(n)
    ir = rng.standard_normal((n, 2)) * np.exp(-t / decay)[:, None]
    ir = np.stack([lp(ir[:, 0], 7000), lp(ir[:, 1], 6000)], axis=1)
    ir /= np.sqrt((ir ** 2).sum(axis=0).mean())
    wet = np.stack([sg.fftconvolve(x[:, c], ir[:, c])[: len(x)] for c in (0, 1)], axis=1)
    return x + mix * wet


# ---------------------------------------------------------------- one mix
CHORDS = {  # a calm progression that resolves on the last scene
    "day": ["C3", "G3", "E4", "B4"], "send": ["A2", "E3", "C4", "G4"],
    "checkin": ["F2", "C3", "A3", "E4"], "summary": ["G2", "D3", "B3", "E4"],
}


def build(name: str):
    E = json.load(open(f"public/audio/events-{name}.json"))
    N = at(E["duration"]) + 1
    sfx = np.zeros((N, 2)); music = np.zeros((N, 2)); voice = np.zeros((N, 2))

    # Miguel, slightly to the left where his bubble is
    lines = {}
    for v in E["voice"]:
        sr, x = wavfile.read(f"public/audio/voice/{v['id']}.wav")
        x = x.astype(float) / 32767
        lines[v["id"]] = (v["t"], len(x) / SR)
        place(voice, x, v["t"], db(-1.5), -0.18)

    for e in E["events"]:
        t, k, pan = e["t"], e["kind"], e.get("pan", 0)
        if k == "open":
            for i, nm in enumerate(["G5", "C6", "E6"]):
                place(sfx, bell(n2f(nm), 2.0, 0.7), t + 0.05 + i * 0.07, db(-26 - 2 * i), -0.2 + 0.2 * i)
        elif k == "scene":
            place(sfx, swish(0.5, 300, 2500), t - 0.05, db(-25), 0)
        elif k in ("nav", "select", "send"):
            place(sfx, click(2400 if k != "send" else 2100), t, db(-17), pan)
            if k == "select":
                place(sfx, pluck(n2f("G5")), t + 0.01, db(-27), pan)
            if k == "nav":
                place(sfx, swish(0.22, 900, 5000), t + 0.06, db(-30), pan)
        elif k == "swipe":
            place(sfx, swish(max(0.25, e.get("dur", 0.8) * 0.45), 700, 5500), t, db(-29), pan)
        elif k == "handoff":
            place(sfx, shimmer(0.42), t - 0.02, db(-21))
        elif k == "wake":
            place(sfx, pluck(n2f("C6"), 0.9), t, db(-24), pan)
            place(sfx, bell(n2f("E6"), 1.4, 0.5), t + 0.04, db(-31), pan)
        elif k == "step":
            place(sfx, click(3100, 0.03), t, db(-27), pan)
            place(sfx, pluck(n2f("E5"), 0.4), t, db(-31), pan)
        elif k == "delivered":
            for i, nm in enumerate(["E5", "A5", "C#6"]):
                place(sfx, bell(n2f(nm), 2.2, 0.8, 1.0), t + i * 0.085, db(-21 - 2 * i), pan - 0.1 + 0.1 * i)
        elif k == "connect":
            for i, nm in enumerate(["C5", "E5", "G5", "C6"]):
                place(sfx, bell(n2f(nm), 2.2, 0.85, 0.9), t + i * 0.06, db(-22 - 1.5 * i), pan - 0.15 + 0.1 * i)
            place(music, pad([n2f(x) for x in ["C4", "E4", "G4"]], 1.6, 0.25, 1.4, 2200), t, db(-7))

    # the bed: one soft chord per scene, crossfading at the changes; it resolves to C at the end
    for s in E["scenes"]:
        f = [n2f(x) for x in CHORDS[s["id"]]]
        place(music, pad(f, s["end"] - s["start"] + 0.4, 0.9, 1.0), s["start"] - 0.3, db(-1))
    if E["scenes"][-1]["id"] == "summary":
        end = E["scenes"][-1]["end"]
        place(music, pad([n2f(x) for x in ["C3", "G3", "E4", "G4"]], E["duration"] - end + 0.2, 0.6, 1.0), end - 0.6, db(-1))

    sfx = reverb(sfx, 1.4, 0.35, 0.22)
    music = reverb(music, 2.2, 0.8, 0.3)

    # duck the bed and the sounds a little while Miguel talks
    ts = np.arange(N) / SR
    duck = np.ones(N)
    for t0, d in lines.values():
        duck = np.minimum(duck, np.interp(ts, [t0 - 0.25, t0 + 0.05, t0 + d - 0.1, t0 + d + 0.35], [1, db(-6), db(-6), 1]))
    music *= duck[:, None]
    sfx *= (0.6 + 0.4 * duck)[:, None]

    # levels: speech at about -17.5 dBFS RMS, taps and chimes clearly under it, the bed far below
    act = np.abs(voice).mean(axis=1) > 1e-3
    gv = db(-17.5) / np.sqrt((voice[act] ** 2).mean()) if act.any() else 1
    voice *= gv
    music *= db(-33.5) / (np.sqrt((music ** 2).mean()) + 1e-12)
    sfx *= db(-13) / (np.abs(sfx).max() + 1e-12)

    fade = np.clip((E["duration"] - ts) / 0.8, 0, 1) * np.clip(ts / 0.05, 0, 1)
    voice *= fade[:, None]; sfx *= fade[:, None]; music *= fade[:, None]
    mix = voice + sfx + music
    mix = sg.sosfilt(sg.butter(2, 30, "high", fs=SR, output="sos"), mix, axis=0)
    lim = db(-1.0)
    mix = np.where(np.abs(mix) > lim * 0.75, np.sign(mix) * (lim * 0.75 + lim * 0.25 * np.tanh((np.abs(mix) - lim * 0.75) / (lim * 0.25))), mix)

    def write(n, x):
        wavfile.write(f"public/audio/{n}.wav", SR, (np.clip(x, -1, 1) * 32767).astype(np.int16))

    write(name, mix)
    if name == "mix":
        write("stem_voice", voice); write("stem_sfx", sfx); write("stem_music", music)
    r = lambda x: 20 * np.log10(np.sqrt((x ** 2).mean()) + 1e-12)
    print(f"{name}: {E['duration']:.2f} s, peak {20*np.log10(np.abs(mix).max()):.1f} dBFS, rms {r(mix):.1f}, "
          f"voice rms (speaking) {r(voice[act]):.1f}, bed rms {r(music):.1f}, sfx peak {20*np.log10(np.abs(sfx).max()):.1f}")


for name in ["mix", "mix-day", "mix-send", "mix-checkin", "mix-summary"]:
    build(name)

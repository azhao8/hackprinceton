"""Miguel's mouth for the narrator bubble, from Corey's actual audio.

For every narration line: Cartesia's phoneme timings (IPA) pick the mouth *shape* (closed for
m/b/p, round for oo/oh/w, spread for ee/ay, open for ah), the line's loudness envelope sets how far
it *opens*, and a short forward-backward smoothing blends one shape into the next the way lips
move (coarticulation), returning to a closed smile in pauses. The mouth leads the sound by 25 ms,
which reads as in sync.

  uv run --with numpy --with scipy python tools/lipsync.py      → src/lipsync.json (120 Hz tracks)
"""
import json
import numpy as np
from scipy.io import wavfile

HZ = 120
LEAD = 0.025

# (open, round, wide) per sound
SHAPES = {
    "closed": (0.0, 0.0, 0.0),  # p b m
    "lip": (0.12, 0.0, 0.25),  # f v: lower lip to teeth
    "tongue": (0.28, 0.0, 0.15),  # t d n l s z th
    "hush": (0.3, 0.55, 0.0),  # sh zh ch j
    "back": (0.32, 0.0, 0.0),  # k g ng h
    "w": (0.22, 0.95, 0.0),
    "r": (0.3, 0.45, 0.0),
    "y": (0.3, 0.0, 0.6),
    "ee": (0.38, 0.0, 0.9),
    "eh": (0.55, 0.0, 0.6),
    "ah": (0.9, 0.0, 0.15),
    "uh": (0.55, 0.1, 0.0),
    "oh": (0.65, 0.75, 0.0),
    "oo": (0.4, 0.95, 0.0),
}
SOUND = {}
for keys, shape in [
    ("p b m", "closed"), ("f v", "lip"), ("t d n l s z θ ð ɾ", "tongue"), ("ʃ ʒ tʃ dʒ", "hush"),
    ("k g ɡ ŋ h ʔ", "back"), ("w", "w"), ("ɹ r", "r"), ("j", "y"), ("i iː ɪ", "ee"), ("e ɛ ɛː", "eh"),
    ("æ a ɑ ɑː ɐ", "ah"), ("ʌ ə ɚ ɜ ɜː ɝ", "uh"), ("ɔ ɔː ɒ o oː", "oh"), ("u uː ʊ", "oo"),
]:
    for k in keys.split():
        SOUND[k] = shape
DIPHTHONGS = {"aɪ": ("ah", "ee"), "eɪ": ("eh", "ee"), "aʊ": ("ah", "oo"), "oʊ": ("oh", "oo"), "əʊ": ("uh", "oo"), "ɔɪ": ("oh", "ee")}


def shape_at(p: str, u: float):
    p = p.replace("ˈ", "").replace("ˌ", "")
    if p in DIPHTHONGS:
        a, b = (np.array(SHAPES[s]) for s in DIPHTHONGS[p])
        return a + (b - a) * min(1.0, max(0.0, (u - 0.25) / 0.6))
    if p in SOUND:
        return np.array(SHAPES[SOUND[p]])
    base = p.replace("ː", "")
    if base in SOUND:
        return np.array(SHAPES[SOUND[base]])
    if p == "ᵻ":
        return np.array(SHAPES["ee"])
    # r- or l-colored vowels (ɔːɹ, ɪɹ, ʊɹ, əl): the vowel, gliding into the consonant
    for k in sorted(SOUND, key=len, reverse=True):
        rest = p[len(k):]
        if p.startswith(k) and rest in SOUND:
            a, b = np.array(SHAPES[SOUND[k]]), np.array(SHAPES[SOUND[rest]])
            return a + (b - a) * min(1.0, max(0.0, (u - 0.4) / 0.5))
    return np.array(SHAPES["uh"])  # anything else: a neutral open vowel


def smooth(x: np.ndarray, tau: float) -> np.ndarray:
    a = 1 - np.exp(-1 / (HZ * tau))
    y = x.copy()
    for i in range(1, len(y)):
        y[i] = y[i - 1] + a * (y[i] - y[i - 1])
    for i in range(len(y) - 2, -1, -1):
        y[i] = y[i + 1] + a * (y[i] - y[i + 1])
    return y


def envelope(path: str, n: int) -> np.ndarray:
    sr, x = wavfile.read(path)
    x = x.astype(float) / 32767
    hop, win = sr // HZ, int(sr * 0.03)
    env = np.array([np.sqrt(np.mean(x[max(0, i * hop - win // 2): i * hop + win // 2] ** 2) + 1e-12) for i in range(n)])
    env /= np.percentile(env, 95) + 1e-9
    return np.clip(env, 0, 1)


narr = json.load(open("src/narration.json"))
out = []
for line in narr["lines"]:
    d = json.load(open(f"public/audio/voice/{line['id']}.json"))
    n = int(np.ceil(d["seconds"] * HZ)) + 1
    t = np.arange(n) / HZ + LEAD
    env = envelope(f"public/audio/voice/{line['id']}.wav", n)
    env_lead = np.interp(t, np.arange(n) / HZ, env)
    tgt = np.zeros((n, 3))
    for i, ti in enumerate(t):
        ph = next((p for p in d["phonemes"] if p["start"] <= ti < p["end"]), None)
        if ph is None:
            continue  # between words: lips together, resting
        u = (ti - ph["start"]) / max(1e-3, ph["end"] - ph["start"])
        s = shape_at(ph["p"], u)
        loud = env_lead[i]
        s = s.copy()
        s[0] *= (0.45 + 0.55 * loud) if loud > 0.05 else 0.3
        tgt[i] = s
    opn = np.clip(smooth(tgt[:, 0], 0.022), 0, 1)
    rnd = np.clip(smooth(tgt[:, 1], 0.04), 0, 1)
    wid = np.clip(smooth(tgt[:, 2], 0.04), 0, 1)
    level = np.clip(smooth(env, 0.06), 0, 1)
    out.append({
        "id": line["id"], "scene": line["scene"], "at": line["at"], "seconds": d["seconds"], "text": line["text"],
        "open": [round(v, 3) for v in opn], "round": [round(v, 3) for v in rnd],
        "wide": [round(v, 3) for v in wid], "level": [round(v, 3) for v in level],
        "words": [{"text": w["text"], "start": round(w["start"], 3), "end": round(w["end"], 3)} for w in d["words"]],
    })
    closed = int(np.sum(opn < 0.06)); print(f"{line['id']}: {n} samples, mouth open {np.mean(opn > 0.06)*100:.0f}% of the line, peak open {opn.max():.2f}")
json.dump({"hz": HZ, "lines": out}, open("src/lipsync.json", "w"))
print("wrote src/lipsync.json")

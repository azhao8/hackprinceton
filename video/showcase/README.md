# Miguel — family app showcase

A standalone section for the Devpost video. Two phones side by side show the real family app (`web/`, `/family`): the **left phone is where you act**, the **right phone is what happens**. One phone is lit at a time, and the light moves to the right the moment the action is made. Miguel narrates it himself, in Corey's voice, from a talking bubble in the top-left corner. 45.5 seconds, 1920×1080, 60 fps, with sound.

| # | Heading | Left phone (action) | Right phone (outcome) |
| --- | --- | --- | --- |
| 1 | Stay close, even from far away. | Home: glance, scroll, tap **See all** | Mom's day: the timeline, scrolled |
| 2 | A little help, whenever it's needed. | Send something → Water → "Love you, Mom ❤️" → **Send with Miguel** | The delivery: heads to his station → on his tray → brings it to her → delivered at 4:12 pm |
| 3 | Be there, without being there. | Check in → **Ask Mom** | "Asking Mom…" (Miguel asks her first), then the live check-in: she waves and talks |
| 4 | The little things add up. | Mom's day → **Miguel's summary** | The summary: Miguel's read of the day, walking pace for the week, her routine, what the family sent |

## Outputs

| File | What |
| --- | --- |
| `deliverables/miguel-family-showcase.mp4` | The whole section |
| `deliverables/clips/feature-*.mp4` | Each feature on its own (11.5–14 s, each with its own mix), to rearrange in the edit |
| `deliverables/frames/` | Review stills |
| `NARRATION.md` | Miguel's lines and when they play |
| `public/audio/stem_voice.wav`, `stem_sfx.wav`, `stem_music.wav` | The section's sound in three stems, for remixing under the Devpost music |

## How it's made

The phones show **captured frames of the real app**, not mockups. Nothing on the screens is drawn by the video except the iPhone's status bar, Dynamic Island, home indicator and the touch marks.

1. **`tools/build-app.sh`** builds `web/` for filming: the seeded demo day (`NEXT_PUBLIC_FAMILY_SOURCE=demo`) with the demo's steps shortened to a watchable pace (`NEXT_PUBLIC_DEMO_TIMING`).
2. **`capture/capture.mjs`** opens the app in Chrome at iPhone 15 Pro size (393 × 793 pt below the status bar, at 2×) and plays each scene in `capture/scenes.mjs` as real taps and swipes. `capture/vt.js` gives the page a virtual clock (timers, animation frames, `Date`, CSS animations and transitions all wait for it), so every frame is exact at 60 fps and loading takes no screen time. Each scene runs twice: once for the left phone, where the last tap is pressed but not let through so it stays on the screen where it happened, and once for the right phone, where it goes through.
3. **`tools/voice.mjs`** asks Cartesia for each line in `src/narration.json` (Corey, with word and phoneme timings). **`tools/lipsync.py`** turns the phonemes and the loudness of each line into mouth shapes (closed, open, round, wide) at 120 Hz.
4. **`src/`** (Remotion) lays the frames into the two phones with the headings, side labels, touch marks and the light that moves between phones. **`src/Narrator.tsx`** is the bubble: the intro's 3D Miguel (`src/miguel/`, rebuilt from the sticker), lip-synced, blinking, glancing at the phones when something happens there, with an amber ring that follows his voice.
5. **`tools/export_events.ts`** lists every tap, swipe, handoff, delivery step and line on the video's clock; **`tools/synth_audio.py`** synthesizes the UI sounds and a quiet bed from it and mixes them under the narration.
6. **`tools/render.sh`** renders the section and the clips (image sequence, WebGL glitch check, encode with the mix). `tools/build.sh` does it all; `--new-voice` also regenerates the narration.

```bash
npm install
tools/build.sh                 # build the app, capture, lip sync, sound, render everything
npx remotion studio src/index.ts   # preview after a capture
```

Rendering uses the installed Google Chrome (`--chrome-mode=chrome-for-testing --browser-executable=...`); the headless shell Remotion downloads doesn't start on this Mac.

## What is simulated

The family app runs on its **demo source** (`web/lib/family/source.ts`): a seeded Saturday at Margaret's home with Sarah (her daughter) as the viewer. In the video:

- **Times are shortened.** A delivery takes seconds instead of about five minutes, and Mom answers a check-in in 3 seconds.
- **The check-in shows an illustration of Margaret,** not camera video. With the real server, the same screen shows Miguel's camera.
- **Miguel's summary is written from the day's timeline by the app** (`web/lib/family/summary.ts`), not by a language model. It's labeled on screen as Miguel's read, and the app says it isn't a medical assessment.
- **The story carries across scenes.** The water sent in scene 2 and the check-in from scene 3 (at 4:20 pm, six minutes) are in Mom's day and the summary by scene 4. The status bar shows the demo clock: 4:12 pm, then 4:20, then 4:26.
- **Not shown:** "Finding Mom…" before "Asking Mom…". The app and server have no such step today; Miguel asks from where he is.

A small "Miguel family app · demo data" note sits in the corner of the whole section. Miguel's lines describe what the app is for; they don't claim the delivery took seconds.

## Credits

Remotion, React, three.js, Puppeteer (Apache-2.0), NumPy and SciPy, Literata, DM Mono and Figtree (SIL Open Font License, via Fontsource). Miguel's voice: Cartesia (Corey). The app itself: see `web/README.md`.

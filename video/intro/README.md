# Miguel — animated introduction

A 20.97-second, 1920×1080, 60 fps intro for the Devpost video. Three statistics, then Miguel — a real 3D model rebuilt from the sticker — drives in, introduces himself, turns to face the I in his own name, knocks it over, drives into its place, thinks about Grandma and her family, and settles into the final logo, which holds for about 1.6 s before the fade.

## Outputs

| File | What |
| --- | --- |
| `deliverables/miguel-intro.mp4` | The intro: picture, Corey's three lines (Cartesia), original music and sound effects |
| `deliverables/miguel-turnaround.png` | The model from eight angles (the quality gate) |
| `deliverables/miguel-turnaround.mp4` | The model spinning, for the Devpost video or slides |
| `deliverables/frames/` | Review stills from every stage |
| `public/audio/stem_music.wav`, `stem_sfx.wav`, `stem_voice.wav` | Stems, for remixing under the rest of the Devpost video |

## The 3D Miguel

`src/three/miguel3d.ts` builds him from primitives, matched part by part to the sticker (`assets/source/miguel-sticker.png`):

- **Phone:** a gold iPhone with real thickness. Its back faces his front, with the two-lens camera bump and the black mount; the screen faces his back.
- **Holder:** the white phone holder with its strap, its curved opening showing the mount, and the face panel. The face is a live texture (eyes, blinks, happy eyes, talking mouth, "o").
- **Middle:** the white mast with its little house icon, the pale-blue neck bracket and the black post. Black, red, blue, orange and green cables are routed as 3D tubes and sway on springs.
- **Electronics:** the ESP32 board stack with its glowing red LED and green terminals, the driver board and switch.
- **Base:** the deck with its pale-blue corner plates, the battery tray on posts, the motors and axles, and the pale-blue kickstand foot.
- **Wheels:** two treaded rubber wheels with spoked hubs.

**Rig.** These all move independently:
- position and full 360° yaw;
- body pitch about the axle (balancing);
- each wheel's own spin (differential steering);
- head tilt and nod;
- cable sway;
- face.

**Look.** Cel shading (`MeshToonMaterial`), plus an ink-outline pass in `src/three/stage.ts` that draws the sticker's dark lines on Miguel only. The lines come from depth and normal edges.

**Check it:**
- **`Turnaround` composition:** eight angles. `--props='{"spin":true}'` makes them spin.
- **`ModelVsSticker` composition:** the model at the sticker's angle, next to the sticker.

## How it's built

| Path | What |
| --- | --- |
| `src/timeline.json` | Every beat's time in seconds. Picture and sound both read it |
| `src/Intro.tsx` | The composition: statistics (SVG), floor and shadows (SVG), the 3D stage, thoughts (SVG) |
| `src/scene/Stats.tsx` | Act I typography (opentype.js glyph paths, masked rolls) |
| `src/scene/layout.ts` | The wordmark, centred on the frame. The I's slot is sized to Miguel, wheels and all, so no other letter moves |
| `src/three/letters.ts` | MIGUEL as extruded 3D letters in the same scene. The I is its own block on a pivot |
| `src/scene/choreo3d.ts` | The performance. Position and heading always agree (he drives where he faces, reverses, turns in place); each wheel's speed comes from differential-drive maths; the balancing pitch, cable springs, head and face acting are layered on top; the I's topple is simulated |
| `src/scene/Stage3D.tsx` | Renders the 3D stage with real sub-frame motion blur |
| `src/lib/camera.ts` | The single fixed camera, shared by the 3D renderer and the SVG layers |
| `src/scene/Thoughts.tsx` | Grandma, the heart and the family phone as small stickers. They float above the centred wordmark and never move it |
| `tools/` | Motion export, audio synthesis, voice, review helpers |

## Corey's voice (Cartesia)

Miguel speaks with Cartesia's "Corey — Supportive Buddy" (`630ed21c-2c5c-41cf-9d82-10a7fd668370`, model `sonic-3.6`). The key lives in `video/intro/.env` (git-ignored), and the current take is saved in `public/audio/voice/`.

- `tools/build.sh` reuses the saved take, derives mouth movement from it, remixes (ducking the music under the lines and warning if a line runs past its beat) and renders. It renders an image sequence, re-renders any frame a GPU hiccup glitched (`tools/check_sequence.py`), then encodes (`tools/render_final.sh`).
- `tools/build.sh --new-voice` asks Cartesia for a fresh take.

## Sound

All music and effects are synthesized from scratch in `tools/synth_audio.py`:
- **Music:** a vi–IV–ii pad under the statistics that resolves to I on the wordmark, bells on the thoughts, and a plagal ending.
- **Motors:** driven by the wheel speeds that `tools/export_motion.ts` exports from the animation.
- **Effects:** the chirp, the bonk, and the clunk from behind the ledge.

## Render it yourself

```bash
npm install
npx remotion studio src/index.ts      # preview
tools/build.sh                        # full build (reuses the saved Corey take)
```

Rendering uses the installed Google Chrome (`--chrome-mode=chrome-for-testing --browser-executable=...`). The headless shell that Remotion downloads hangs on this Mac. WebGL needs the GPU, so `build.sh` renders with concurrency 4.

## Credits

Three.js (MIT), Remotion (free for individuals and small teams), React, opentype.js (MIT), Outfit and Inter Tight (SIL Open Font License, via Fontsource), NumPy and SciPy. Statistics: [CDC](https://www.cdc.gov/falls/data-research/index.html), [Fleming & Brayne, BMJ 2008](https://www.bmj.com/content/337/bmj.a2227.abstract), and National Academies, *Social Isolation and Loneliness in Older Adults* (2020).

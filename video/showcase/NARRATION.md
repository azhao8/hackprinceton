# Miguel's narration

Miguel narrates the showcase himself, in Corey's voice (Cartesia, voice `630ed21c-2c5c-41cf-9d82-10a7fd668370`, model sonic-3.6), the same voice as the intro. It's in `deliverables/miguel-family-showcase.mp4` and the clips, and his lips move with it in the bubble in the corner.

The lines say why each thing matters rather than what's on screen, and leave the moments where something happens (the delivery arriving, Mom waving) to the sound effects.

| Time | Scene | On screen | Line |
| --- | --- | --- | --- |
| 0:00.7 | 1 · Stay close | Home, swiping to Mom's day | “I'm with your grandparents all day, so you always know how they're doing.” |
| 0:04.5 | 1 · Stay close | Mom's day scrolls: walks, lunch, tea with Ruth | “Your mom's walks, her lunch, tea with Ruth. No need to call and interrupt.” |
| 0:10.1 | 2 · A little help | Taps Send something, picks Water | “Need me to bring her something? Just let me know.” |
| 0:15.1 | 2 · A little help | The delivery's progress | “I'll take it right to her, and give her your note.” |
| 0:21.6 | 3 · Be there | Taps Check in | “And when you miss her, I can bring you right to her.” |
| 0:25.0 | 3 · Be there | Asking Mom… | “I always ask her first.” |
| 0:32.1 | 4 · The little things | Taps Miguel's summary | “At the end of the day, I'll tell you how it went.” |
| 0:36.5 | 4 · The little things | Walking pace, then what the family sent | “Every walk, every glass of water. I remember the little things, so you don't have to wonder.” |
| 0:42.9 | 4 · The little things | The final hold | “That's what I'm here for.” |

To change a line: edit `src/narration.json` (text and `at`, seconds into its scene), then `node --env-file=.env tools/voice.mjs <id>` (needs `CARTESIA_API_KEY` in `video/showcase/.env`, git-ignored), then `tools/build.sh` from the lip-sync step on (or the whole thing).

import { useEffect, useMemo, useState } from "react";
import { AbsoluteFill, Audio, continueRender, delayRender, staticFile, useCurrentFrame, useVideoConfig } from "remotion";
import T from "./timeline.json";
import { clamp, easeOutBack, invLerp, ramp } from "./lib/anim";
import { project } from "./lib/camera";
import { useFontSet } from "./lib/fonts";
import { buildChoreo3D } from "./scene/choreo3d";
import { Floor } from "./scene/Floor";
import { computeWordLayout, MIGUEL_PX } from "./scene/layout";
import { Stage3D } from "./scene/Stage3D";
import { Stats } from "./scene/Stats";
import { Thoughts } from "./scene/Thoughts";

export type IntroProps = { audio: string | null; voiceEnvelope: string | null };

/** Optional per-line mouth envelopes generated from the voice files (tools/voice_env.py). */
const useVoiceEnv = (file: string | null) => {
  const [env, setEnv] = useState<Record<string, number[]> | null>(file ? null : {});
  const [handle] = useState(() => (file ? delayRender("voice envelope") : null));
  useEffect(() => {
    if (!file || handle === null) return;
    fetch(staticFile(file))
      .then((r) => (r.ok ? r.json() : {}))
      .catch(() => ({}))
      .then((j) => {
        setEnv(j);
        continueRender(handle);
      });
  }, [file, handle]);
  return env;
};

/** Each letter rises from the floor, M first; index order M, I, G, U, E, L. */
const reveals = (t: number) =>
  [0, 1, 2, 3, 4, 5].map((i) => easeOutBack(1.2)(clamp(invLerp(T.wordIn + i * T.wordStagger, T.wordIn + i * T.wordStagger + T.wordDur, t))));

// While Miguel talks in front of the word, the letters fall a little into shadow so he reads clearly;
// the light comes back as he turns and charges into the word.
const dimAt = (t: number) => 1 - 0.42 * ramp(t, T.enterStart + 0.4, T.enterStop + 0.3) * (1 - ramp(t, T.turnToI, T.impact + 0.2));

export const Intro: React.FC<IntroProps> = ({ audio, voiceEnvelope }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const t = frame / fps;
  const fonts = useFontSet();
  const env = useVoiceEnv(voiceEnvelope);
  const layout = useMemo(() => (fonts ? computeWordLayout(fonts.word) : null), [fonts]);
  const choreo = useMemo(() => (layout && env ? buildChoreo3D(layout.slotX, env) : null), [layout, env]);

  if (!fonts || !layout || !choreo) return <AbsoluteFill style={{ background: "#000" }} />;

  const r = reveals(t);
  const iState = choreo.letterI(t);
  const fade = 1 - ramp(t, T.fadeOut, T.duration - 0.05);
  const pose = choreo.pose(t);
  const onStage = t > T.enterStart - 0.1;
  // the thoughts float above where his head ends up (they never move the wordmark)
  const rest = choreo.pose(Math.max(t, T.slotEnd));
  const head = project(rest.x, MIGUEL_PX * 1.0, rest.z);

  return (
    <AbsoluteFill style={{ background: "#000" }}>
      {audio && <Audio src={staticFile(audio)} />}
      <AbsoluteFill style={{ opacity: fade }}>
        <Stats fonts={fonts} t={t} />
        <Floor
          layout={layout}
          reveal={r.map((v) => clamp(v))}
          iShadow={1 - clamp(iState.roll / 0.6)}
          glow={clamp(invLerp(T.wordIn, T.wordIn + 0.8, t))}
          miguel={onStage ? { x: pose.x, z: pose.z, yaw: pose.yaw } : null}
        />
        <Stage3D choreo={choreo} layout={layout} reveal={reveals} dim={dimAt} />
        <Thoughts t={t} headX={head.X} headY={head.Y} />
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

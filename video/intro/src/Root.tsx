import { Composition } from "remotion";
import { Intro, IntroProps } from "./Intro";
import { ModelVsSticker, Spin, Turnaround } from "./Turnaround";
import T from "./timeline.json";
import media from "./media.json";

export const RemotionRoot: React.FC = () => (
  <>
    <Composition
      id="MiguelIntro"
      component={Intro}
      durationInFrames={Math.round(T.duration * T.fps)}
      fps={T.fps}
      width={1920}
      height={1080}
      defaultProps={{ audio: media.audio, voiceEnvelope: media.voiceEnvelope } as IntroProps}
    />
    <Composition id="Turnaround" component={Turnaround} durationInFrames={480} fps={60} width={1920} height={1080} defaultProps={{ spin: false }} />
    <Composition id="Spin" component={Spin} durationInFrames={420} fps={60} width={1920} height={1080} />
    <Composition id="ModelVsSticker" component={ModelVsSticker} durationInFrames={1} fps={60} width={1920} height={1080} defaultProps={{ yawDeg: -28, elev: 12 }} />
  </>
);

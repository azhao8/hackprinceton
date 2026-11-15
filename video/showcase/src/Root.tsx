import "@fontsource/dm-mono/400.css";
import "@fontsource/dm-mono/500.css";
import "@fontsource/figtree/600.css";
import "@fontsource/literata/400.css";
import "@fontsource/literata/500.css";
import { useEffect, useState } from "react";
import { Composition, continueRender, delayRender } from "remotion";
import { Showcase, showcaseDuration } from "./Showcase";
import { FPS, SCENES } from "./timeline";

/** Holds the first frame until the app's fonts (Literata, DM Mono, Figtree) are loaded. */
const WithFonts: React.FC<{ only?: string; audio?: string | null }> = ({ only, audio }) => {
  const [handle] = useState(() => delayRender("fonts"));
  useEffect(() => {
    Promise.all(
      ["500 50px Literata", "400 25px Literata", "500 15px 'DM Mono'", "400 12px 'DM Mono'", "600 17px Figtree"].map((f) => document.fonts.load(f)),
    ).then(() => continueRender(handle));
  }, [handle]);
  return <Showcase only={only} audio={audio} />;
};

const NAMES: Record<string, string> = { day: "1-KnowHowTheyreDoing", send: "2-SendSomething", checkin: "3-CheckIn", summary: "4-TheBiggerPicture" };

export const RemotionRoot: React.FC = () => (
  <>
    <Composition
      id="FamilyShowcase"
      component={WithFonts}
      durationInFrames={Math.round(showcaseDuration() * FPS)}
      fps={FPS}
      width={1920}
      height={1080}
      defaultProps={{ audio: "audio/mix.wav" }}
    />
    {SCENES.map((s) => (
      <Composition
        key={s.id}
        id={`Feature${NAMES[s.id]}`}
        component={WithFonts}
        durationInFrames={Math.round(showcaseDuration(s.id) * FPS)}
        fps={FPS}
        width={1920}
        height={1080}
        defaultProps={{ only: s.id, audio: `audio/mix-${s.id}.wav` }}
      />
    ))}
  </>
);

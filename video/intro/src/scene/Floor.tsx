import { CAM, project, W } from "../lib/camera";
import { MIGUEL_PX, WordLayout } from "./layout";

/** A barely-there warm floor, contact shadows under the letters, and Miguel's shadow (drawn under the 3D layer). */
export const Floor: React.FC<{
  layout: WordLayout;
  reveal: number[]; // M, I, G, U, E, L
  iShadow: number;
  glow: number;
  miguel: { x: number; z: number; yaw: number } | null;
}> = ({ layout, reveal, iShadow, glow, miguel }) => {
  const Y0 = CAM.Y0;
  const letterShadows = [
    { x0: layout.letters[0].x0, x1: layout.letters[0].x1, r: reveal[0] },
    { x0: layout.I.x0, x1: layout.I.x1, r: reveal[1] * iShadow },
    ...layout.letters.slice(1).map((l, i) => ({ x0: l.x0, x1: l.x1, r: reveal[i + 2] })),
  ];
  let mig = null;
  if (miguel) {
    const p = project(miguel.x, 0, miguel.z);
    const along = 0.36 * MIGUEL_PX * p.s, across = 0.62 * MIGUEL_PX * p.s;
    const c = Math.abs(Math.cos(miguel.yaw)), s = Math.abs(Math.sin(miguel.yaw));
    const rx = across * c + along * s;
    const ry = (along * c + across * s) * (CAM.HC / (CAM.D - miguel.z)) * 0.9;
    mig = { X: p.X, Y: p.Y, rx, ry: Math.max(6, ry) };
  }
  return (
    <svg width={W} height={1080} style={{ position: "absolute", inset: 0 }}>
      <defs>
        <radialGradient id="floorGlow" cx="0.5" cy="0.5" r="0.5">
          <stop offset="0" stopColor="#FFC891" stopOpacity="0.1" />
          <stop offset="0.55" stopColor="#FFB878" stopOpacity="0.036" />
          <stop offset="1" stopColor="#FFB878" stopOpacity="0" />
        </radialGradient>
        <radialGradient id="contact" cx="0.5" cy="0.5" r="0.5">
          <stop offset="0" stopColor="#000" stopOpacity="1" />
          <stop offset="0.55" stopColor="#000" stopOpacity="0.75" />
          <stop offset="1" stopColor="#000" stopOpacity="0" />
        </radialGradient>
      </defs>
      <ellipse cx={960} cy={Y0 + 40} rx={1080} ry={170} fill="url(#floorGlow)" opacity={glow} />
      {letterShadows.map((l, i) => (
        <ellipse key={i} cx={(l.x0 + l.x1) / 2} cy={Y0 + 2} rx={(l.x1 - l.x0) * 0.62 + 8} ry={13} fill="url(#contact)" opacity={0.95 * Math.max(0, l.r) ** 3} />
      ))}
      {mig && <ellipse cx={mig.X} cy={mig.Y + 2} rx={mig.rx} ry={mig.ry} fill="url(#contact)" opacity={0.95} />}
    </svg>
  );
};

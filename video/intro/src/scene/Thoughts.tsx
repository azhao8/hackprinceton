// Miguel's thoughts: three small dimensional stickers in his own visual language (dark ink outlines, warm
// colours, a cream die-cut edge): Grandma, a heart, and her kid waving from a phone.
import T from "../timeline.json";
import { clamp, easeInOutSine, easeOutBack, easeOutCubic, invLerp, lerp, ring } from "../lib/anim";

const INK = "#2b2526";
const CREAM = "#FFF6E8";

/** A sticker: soft shadow and warm bloom underneath (gradients, no filters), the cream die-cut edge, the art. */
const Sticker: React.FC<{ children: React.ReactNode; edge: React.ReactNode; rx: number; ry: number }> = ({ children, edge, rx, ry }) => (
  <g>
    <ellipse cx={0} cy={ry * 0.18} rx={rx * 1.5} ry={ry * 1.45} fill="url(#stickerBloom)" />
    <ellipse cx={0} cy={ry * 0.95 + 4} rx={rx * 0.95} ry={Math.max(8, ry * 0.2)} fill="url(#stickerShadow)" />
    {edge}
    {children}
  </g>
);

const Grandma: React.FC = () => (
  <Sticker edge={<circle r={63} fill={CREAM} />} rx={63} ry={63}>
    <defs>
      <radialGradient id="gmBg" cx="0.4" cy="0.35" r="0.8">
        <stop offset="0" stopColor="#FCEBD0" />
        <stop offset="1" stopColor="#EFCB98" />
      </radialGradient>
      <clipPath id="gmClip">
        <circle r={55} />
      </clipPath>
    </defs>
    <circle r={55} fill="url(#gmBg)" />
    <g clipPath="url(#gmClip)">
      {/* cardigan + collar */}
      <path d="M-52 62 C-48 30 -30 22 0 22 C30 22 48 30 52 62 Z" fill="#B9707C" stroke={INK} strokeWidth={3} />
      <path d="M-14 22 L0 40 L14 22 Z" fill="#FFF8F0" stroke={INK} strokeWidth={2.5} strokeLinejoin="round" />
      <path d="M-6 21 L-6 26 Q0 30 6 26 L6 21" fill="#F1C3A0" stroke={INK} strokeWidth={2.5} />
      {[-12, -6, 0, 6, 12].map((x, i) => (
        <circle key={i} cx={x} cy={30 + Math.abs(x) * -0.35 + 2} r={2.2} fill="#FFFDF8" stroke="#bfb3a6" strokeWidth={0.8} />
      ))}
    </g>
    {/* hair back + bun */}
    <circle cx={0} cy={-37} r={11} fill="#F4F1EC" stroke={INK} strokeWidth={3} />
    <path d="M-29 -2 C-34 -26 -18 -38 0 -38 C18 -38 34 -26 29 -2 C24 -8 22 -14 0 -16 C-22 -14 -24 -8 -29 -2 Z" fill="#EDE9E3" stroke={INK} strokeWidth={3} strokeLinejoin="round" />
    {/* face */}
    <ellipse cx={0} cy={0} rx={23} ry={25} fill="#F3C9A6" stroke={INK} strokeWidth={3} />
    {/* hair front: soft waves */}
    <path d="M-24 -6 C-26 -22 -12 -30 0 -27 C12 -30 26 -22 24 -6 C20 -15 12 -18 6 -15 C2 -20 -6 -20 -9 -15 C-14 -18 -21 -15 -24 -6 Z" fill="#F7F4EF" stroke={INK} strokeWidth={2.6} strokeLinejoin="round" />
    {/* glasses */}
    <g stroke="#7A4A2E" strokeWidth={2.4} fill="rgba(255,255,255,0.28)">
      <circle cx={-10} cy={1} r={8} />
      <circle cx={10} cy={1} r={8} />
      <path d="M-2 0 Q0 -2 2 0" fill="none" />
    </g>
    {/* smiling eyes behind the lenses */}
    <g stroke={INK} strokeWidth={2.2} fill="none" strokeLinecap="round">
      <path d="M-14 2 Q-10 -2 -6 2" />
      <path d="M6 2 Q10 -2 14 2" />
      <path d="M-6 13 Q0 18 6 13" />
    </g>
    <ellipse cx={-15} cy={11} rx={4.5} ry={2.6} fill="#E98F82" opacity={0.55} />
    <ellipse cx={15} cy={11} rx={4.5} ry={2.6} fill="#E98F82" opacity={0.55} />
    <circle r={55} fill="none" stroke={INK} strokeWidth={3} />
  </Sticker>
);

const HEART_D = "M0 15 C-6 9 -20 1 -20 -9 C-20 -17 -14 -21 -9 -21 C-4 -21 -1 -18 0 -14 C1 -18 4 -21 9 -21 C14 -21 20 -17 20 -9 C20 1 6 9 0 15 Z";
const Heart: React.FC = () => (
  <Sticker edge={<path d={HEART_D} fill={CREAM} stroke={CREAM} strokeWidth={14} strokeLinejoin="round" />} rx={27} ry={24}>
    <defs>
      <linearGradient id="heartG" x1="0" y1="-1" x2="0" y2="1">
        <stop offset="0" stopColor="#F8C766" />
        <stop offset="1" stopColor="#E9922F" />
      </linearGradient>
    </defs>
    <path d={HEART_D} fill="url(#heartG)" stroke={INK} strokeWidth={3} strokeLinejoin="round" />
    <ellipse cx={-9} cy={-12} rx={4.5} ry={2.8} fill="#FFF3D6" opacity={0.85} transform="rotate(-30 -9 -12)" />
  </Sticker>
);

const FamilyPhone: React.FC<{ wave: number }> = ({ wave }) => (
  <Sticker edge={<rect x={-41} y={-68} width={82} height={136} rx={20} fill={CREAM} />} rx={41} ry={68}>
    <defs>
      <linearGradient id="skyG" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0" stopColor="#D5EAF3" />
        <stop offset="1" stopColor="#A9CFE3" />
      </linearGradient>
      <clipPath id="screenClip">
        <rect x={-29} y={-56} width={58} height={112} rx={9} />
      </clipPath>
    </defs>
    <rect x={-35} y={-62} width={70} height={124} rx={15} fill="#34302F" stroke={INK} strokeWidth={3} />
    <rect x={-29} y={-56} width={58} height={112} rx={9} fill="url(#skyG)" />
    <g clipPath="url(#screenClip)">
      {/* waving arm (behind the body) */}
      <g transform={`rotate(${wave} 22 26)`}>
        <path d="M14 34 L24 10" stroke="#3F8F8B" strokeWidth={9} strokeLinecap="round" />
        <path d="M14 34 L24 10" stroke={INK} strokeWidth={0} />
        <circle cx={25} cy={4} r={6.2} fill="#E8B38D" stroke={INK} strokeWidth={2.2} />
      </g>
      {/* shoulders */}
      <path d="M-30 60 C-28 36 -16 30 0 30 C16 30 28 36 30 60 Z" fill="#3F8F8B" stroke={INK} strokeWidth={2.6} />
      <path d="M-5 30 L-5 35 Q0 38 5 35 L5 30" fill="#E8B38D" stroke={INK} strokeWidth={2.2} />
      {/* head */}
      <ellipse cx={0} cy={14} rx={14} ry={15.5} fill="#E8B38D" stroke={INK} strokeWidth={2.6} />
      <path d="M-15 12 C-17 -4 -6 -7 2 -5 C10 -6 17 0 15 12 C12 5 6 2 -2 3 C-8 4 -12 6 -15 12 Z" fill="#4C3427" stroke={INK} strokeWidth={2.2} strokeLinejoin="round" />
      <g stroke={INK} strokeWidth={2} fill="none" strokeLinecap="round">
        <path d="M-7 15 Q-5 12.5 -3 15" />
        <path d="M3 15 Q5 12.5 7 15" />
        <path d="M-4.5 20.5 Q0 24.5 4.5 20.5" />
      </g>
      <ellipse cx={-8.5} cy={19} rx={2.6} ry={1.5} fill="#E2877A" opacity={0.5} />
      <ellipse cx={8.5} cy={19} rx={2.6} ry={1.5} fill="#E2877A" opacity={0.5} />
    </g>
    <rect x={-8} y={-52} width={16} height={4} rx={2} fill="#34302F" />
  </Sticker>
);

const appear = (t: number, t0: number, dur = 0.45) => clamp(invLerp(t0, t0 + dur, t));

/** Positions are screen px; the layer floats above Miguel's head. */
export const Thoughts: React.FC<{ t: number; headX: number; headY: number }> = ({ t, headX, headY }) => {
  if (t < T.grandma - 0.05) return null;
  const bob = (seed: number) => Math.sin((t - T.grandma) * 2.1 + seed) * 3;
  const tilt = (seed: number) => Math.sin((t - T.grandma) * 1.6 + seed) * 2.2;

  const ga = appear(t, T.grandma, 0.5);
  const gDrift = easeInOutSine(clamp(invLerp(T.grandma + 0.05, T.grandma + 1.05, t)));
  const gx = lerp(headX + 104, headX - 126, gDrift), gy = lerp(headY - 100, headY - 138, gDrift) + bob(0);
  const gs = lerp(0.82, 1, easeOutBack(1.6)(ga));

  const ha = appear(t, T.heart, 0.42);
  // the heart beats once when the family appears, and once more, softly, in the closing hold
  const hs = easeOutBack(2.4)(ha) * (1 + ring(t, T.phone + 0.5, 0.1, 1.8, 3.2) + ring(t, T.idleBlink + 0.35, 0.06, 1.8, 3.2));
  const hx = headX, hy = headY - 205 + bob(1.3);

  const pa = appear(t, T.phone, 0.48);
  const px = lerp(headX + 166, headX + 132, easeOutCubic(pa)), py = lerp(headY - 100, headY - 128, easeOutCubic(pa)) + bob(2.4);
  const ps = lerp(0.82, 1, easeOutBack(1.5)(pa));
  const waveT = t - T.phone - 0.12;
  const wave = waveT > 0 ? -12 + 22 * Math.sin(waveT * 2 * Math.PI * 2.3) * Math.exp(-0.9 * Math.max(0, waveT - 0.6)) : -12;

  return (
    <svg width={1920} height={1080} style={{ position: "absolute", inset: 0 }}>
      <defs>
        <radialGradient id="stickerBloom" cx="0.5" cy="0.5" r="0.5">
          <stop offset="0" stopColor="#FFB86E" stopOpacity="0.14" />
          <stop offset="1" stopColor="#FFB86E" stopOpacity="0" />
        </radialGradient>
        <radialGradient id="stickerShadow" cx="0.5" cy="0.5" r="0.5">
          <stop offset="0" stopColor="#000" stopOpacity="0.6" />
          <stop offset="1" stopColor="#000" stopOpacity="0" />
        </radialGradient>
      </defs>
      {ga > 0 && (
        <g opacity={clamp(ga * 2)} transform={`translate(${gx} ${gy}) rotate(${tilt(0.4)}) scale(${gs * 1.14})`}>
          <Grandma />
        </g>
      )}
      {ha > 0 && (
        <g opacity={clamp(ha * 3)} transform={`translate(${hx} ${hy}) rotate(${tilt(2)}) scale(${hs * 1.14})`}>
          <Heart />
        </g>
      )}
      {pa > 0 && (
        <g opacity={clamp(pa * 2)} transform={`translate(${px} ${py}) rotate(${4 + tilt(3.1)}) scale(${ps * 1.14})`}>
          <FamilyPhone wave={wave} />
        </g>
      )}
    </svg>
  );
};

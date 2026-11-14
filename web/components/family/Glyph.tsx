// Small illustrated objects for the field guide. Each is an ink drawing over a color
// plate printed slightly off-register, like a two-color riso print.
// With `diecut`, the silhouette gets a white paper edge, so it reads as a sticker.

import type { ReactNode } from "react";

export type GlyphName =
  | "water"
  | "medication"
  | "note"
  | "parcel"
  | "walk"
  | "wake"
  | "meal"
  | "rest"
  | "message"
  | "checkIn"
  | "company"
  | "night"
  | "alert"
  | "charge"
  | "people"
  | "heart";

type Plate = "sun" | "sky" | "ember" | "sand" | "alarm";

const PLATE: Record<Plate, string> = {
  sun: "#f6c445",
  sky: "#9cbbe4",
  ember: "#ef9468",
  sand: "#e2d2b6",
  alarm: "#f1a291",
};

interface Drawing {
  plate: Plate;
  /** Filled color shapes (drawn offset). */
  fill: ReactNode;
  /** Ink lines. */
  ink: ReactNode;
}

const DRAWINGS: Record<GlyphName, Drawing> = {
  water: {
    plate: "sky",
    fill: <path d="M10.4 14.2h11.2l-1.25 12.1a1.6 1.6 0 0 1-1.6 1.45h-5.5a1.6 1.6 0 0 1-1.6-1.45z" />,
    ink: (
      <>
        <path d="M8.8 6.5h14.4l-1.95 20a2 2 0 0 1-2 1.8h-6.5a2 2 0 0 1-2-1.8z" />
        <path d="M10.2 14.3c1.9.9 3.7-.9 5.8 0s3.9.9 5.8 0" />
        <path d="M13.2 19.6l.5 4.6" opacity="0.5" />
      </>
    ),
  },
  medication: {
    plate: "ember",
    fill: <path d="M16 11.5h5.5a4.5 4.5 0 0 1 0 9H16z" transform="rotate(-35 16 16)" />,
    ink: (
      <g transform="rotate(-35 16 16)">
        <rect x="6" y="11.5" width="20" height="9" rx="4.5" />
        <path d="M16 11.5v9" />
        <path d="M9.6 14.3c.6-.6 1.4-.9 2.3-.9" opacity="0.6" />
      </g>
    ),
  },
  note: {
    plate: "sun",
    fill: <circle cx="16" cy="18.2" r="3.4" />,
    ink: (
      <>
        <rect x="5.5" y="9" width="21" height="15.5" rx="2.2" />
        <path d="M6.2 10.2l9.8 7.4 9.8-7.4" />
        <path d="M16 20.6c-1.6-1-2.5-1.8-2.5-2.8a1.25 1.25 0 0 1 2.5-.3 1.25 1.25 0 0 1 2.5.3c0 1-.9 1.8-2.5 2.8z" />
      </>
    ),
  },
  parcel: {
    plate: "sand",
    fill: <path d="M8 13.5h16v11.6a1.4 1.4 0 0 1-1.4 1.4H9.4A1.4 1.4 0 0 1 8 25.1z" />,
    ink: (
      <>
        <path d="M7 13h18v12a2 2 0 0 1-2 2H9a2 2 0 0 1-2-2z" />
        <path d="M5.8 9.5h20.4v3.5H5.8z" />
        <path d="M16 9.5V27" />
        <path d="M16 9.5c-1.6-3.4-5.4-3.6-5.4-1.5 0 1.3 2.4 1.5 5.4 1.5 3 0 5.4-.2 5.4-1.5 0-2.1-3.8-1.9-5.4 1.5z" />
      </>
    ),
  },
  walk: {
    plate: "sky",
    fill: <path d="M7 21.5c.3-3.6 1.7-8.2 4.4-8.2 1.4 0 1.8 1.5 3.3 2.3 1.8 1 4.3 1 6.4 1.8 2.4 1 3.8 2.4 3.9 4.1z" />,
    ink: (
      <>
        <path d="M6 21.4c0-4.3 2.1-9.6 5.3-9.6 1.6 0 2 1.6 3.6 2.5 1.9 1.1 4.6 1.1 6.8 2 2.8 1.1 4.3 2.8 4.3 4.9v1.6H6z" />
        <path d="M6 23h20" />
        <path d="M13.5 15.4l1.8-1.2M15.6 16.6l1.8-1.1" />
      </>
    ),
  },
  wake: {
    plate: "sun",
    fill: <path d="M9.5 21.5a6.5 6.5 0 0 1 13 0z" />,
    ink: (
      <>
        <path d="M8.5 21.5a7.5 7.5 0 0 1 15 0" />
        <path d="M5 21.5h22M16 7.5v3M8.2 11l2 2M23.8 11l-2 2M5.6 16.6l2.7.7M26.4 16.6l-2.7.7" />
        <path d="M10 25.3h12" opacity="0.6" />
      </>
    ),
  },
  meal: {
    plate: "ember",
    fill: <path d="M7.5 16.8h17a8.5 8.5 0 0 1-17 0z" />,
    ink: (
      <>
        <path d="M6 16h20a10 10 0 0 1-20 0z" />
        <path d="M12.5 12.2c-1-1.2.8-2.2-.2-3.6M16.2 12.2c-1-1.2.8-2.2-.2-3.6M19.9 12.2c-1-1.2.8-2.2-.2-3.6" />
      </>
    ),
  },
  rest: {
    plate: "sky",
    fill: <path d="M6.5 18c0-2.4 2.6-3.6 9.5-3.6s9.5 1.2 9.5 3.6-2.6 4.6-9.5 4.6-9.5-2.2-9.5-4.6z" />,
    ink: (
      <>
        <path d="M5.5 18.3c0-2.8 3-4.3 10.5-4.3s10.5 1.5 10.5 4.3-3 5.2-10.5 5.2-10.5-2.4-10.5-5.2z" />
        <path d="M19 6.5h4.2l-4.2 4.6h4.4" />
      </>
    ),
  },
  message: {
    plate: "sun",
    fill: <path d="M7.5 9.5h17a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H14l-5 3.6v-3.6H7.5a2 2 0 0 1-2-2v-9a2 2 0 0 1 2-2z" />,
    ink: (
      <>
        <path d="M7 8.5h18a2 2 0 0 1 2 2v9.5a2 2 0 0 1-2 2H13.6L8.5 25.6V22H7a2 2 0 0 1-2-2v-9.5a2 2 0 0 1 2-2z" />
        <path d="M10.5 15.2v1.2M13.5 13.2v5.2M16.5 12v7.6M19.5 13.4v4.8M22.5 14.8v2" />
      </>
    ),
  },
  checkIn: {
    plate: "ember",
    fill: <path d="M16 21.4c-2.7-1.7-4.3-3.1-4.3-4.8a2.1 2.1 0 0 1 4.3-.6 2.1 2.1 0 0 1 4.3.6c0 1.7-1.6 3.1-4.3 4.8z" />,
    ink: (
      <>
        <rect x="9" y="4.5" width="14" height="23" rx="3" />
        <path d="M14 7.4h4" />
        <path d="M16 21c-2.6-1.6-4.1-3-4.1-4.6a2 2 0 0 1 4.1-.6 2 2 0 0 1 4.1.6c0 1.6-1.5 3-4.1 4.6z" />
      </>
    ),
  },
  company: {
    plate: "sun",
    fill: (
      <>
        <path d="M5.5 15h9v4.5a4.5 4.5 0 0 1-9 0z" />
        <path d="M17.5 13h9v5.5a4.5 4.5 0 0 1-9 0z" />
      </>
    ),
    ink: (
      <>
        <path d="M4.5 14.5h10v5a5 5 0 0 1-10 0z" />
        <path d="M14.5 16h1a1.8 1.8 0 0 1 0 3.6h-1" />
        <path d="M17.5 12.5h10v6a5 5 0 0 1-10 0z" />
        <path d="M17.5 14h-1a1.8 1.8 0 0 0 0 3.6h1" />
        <path d="M8 11.4c-.7-.9.6-1.6-.1-2.6M22.5 9.6c-.7-.9.6-1.6-.1-2.6" />
      </>
    ),
  },
  night: {
    plate: "sun",
    fill: <path d="M19.5 7.5a9 9 0 1 0 6 13.8 7.5 7.5 0 0 1-6-13.8z" />,
    ink: (
      <>
        <path d="M18.5 6.5a9.5 9.5 0 1 0 6.5 14.5 8 8 0 0 1-6.5-14.5z" />
        <path d="M24.5 7.5v3M23 9h3" />
      </>
    ),
  },
  alert: {
    plate: "alarm",
    fill: <path d="M16 7.5l9.2 16H6.8z" />,
    ink: (
      <>
        <path d="M14.3 6.4a2 2 0 0 1 3.4 0l9.6 16.6a2 2 0 0 1-1.7 3H6.4a2 2 0 0 1-1.7-3z" />
        <path d="M16 12.5v6" />
        <path d="M16 22.2v.2" />
      </>
    ),
  },
  charge: {
    plate: "sun",
    fill: <path d="M17.5 5.5L9.5 18h6l-1.5 8.5 8.5-12.5h-6z" />,
    ink: <path d="M17 5L9 17.5h6.5L14 27l9-13h-6.5z" />,
  },
  people: {
    plate: "sky",
    fill: (
      <>
        <circle cx="12" cy="11.5" r="3.6" />
        <path d="M5.8 25c.5-4 3-6.4 6.2-6.4s5.7 2.4 6.2 6.4z" />
      </>
    ),
    ink: (
      <>
        <circle cx="12" cy="11" r="4" />
        <path d="M5 25c.6-4.4 3.3-7 7-7s6.4 2.6 7 7z" />
        <circle cx="21.5" cy="12.5" r="3.2" />
        <path d="M20.5 18.6c3.3-.2 5.8 2 6.5 6.4h-5.3" />
      </>
    ),
  },
  heart: {
    plate: "ember",
    fill: <path d="M16 25c-6-3.8-9.5-7.2-9.5-11a4.6 4.6 0 0 1 9.5-1.6 4.6 4.6 0 0 1 9.5 1.6c0 3.8-3.5 7.2-9.5 11z" />,
    ink: <path d="M16 25.5c-6.2-3.9-10-7.4-10-11.4a5 5 0 0 1 10-1.7 5 5 0 0 1 10 1.7c0 4-3.8 7.5-10 11.4z" />,
  },
};

export function Glyph({
  name,
  size = 28,
  diecut = false,
  className = "",
  title,
}: {
  name: GlyphName;
  size?: number;
  diecut?: boolean;
  className?: string;
  title?: string;
}) {
  const d = DRAWINGS[name];
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 32 32"
      className={className}
      role={title ? "img" : undefined}
      aria-label={title}
      aria-hidden={title ? undefined : true}
      overflow="visible"
    >
      {diecut && (
        <g fill="#fffdf8" stroke="#fffdf8" strokeWidth={5.5} strokeLinejoin="round" strokeLinecap="round">
          {d.fill}
          {d.ink}
        </g>
      )}
      <g fill={PLATE[d.plate]} transform="translate(1.1 1.3)">
        {d.fill}
      </g>
      <g fill="none" stroke="#2a2630" strokeWidth={1.6} strokeLinecap="round" strokeLinejoin="round">
        {d.ink}
      </g>
    </svg>
  );
}

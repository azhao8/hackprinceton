"use client";

// Shared pieces for the family app: the status note, sticker buttons, page header,
// sheets, toggles and avatars.

import Link from "next/link";
import { useEffect, useRef, type ReactNode } from "react";
import type { MiguelMode, Tone } from "@/lib/family/types";
import { Glyph, type GlyphName } from "./Glyph";
import { MODE_META } from "./meta";

/** Miguel's state as a small field note: dot, label, one line. */
export function StatusNote({
  mode,
  note,
  onLongPress,
}: {
  mode: MiguelMode;
  note: string;
  onLongPress?: () => void;
}) {
  const meta = MODE_META[mode];
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const start = () => {
    if (!onLongPress) return;
    timer.current = setTimeout(onLongPress, 650);
  };
  const cancel = () => clearTimeout(timer.current);
  return (
    <div
      className="select-none"
      onPointerDown={start}
      onPointerUp={cancel}
      onPointerLeave={cancel}
      onPointerCancel={cancel}
      onContextMenu={(e) => onLongPress && e.preventDefault()}
    >
      <div className="flex items-center gap-2">
        <span
          className="fg-dot inline-block"
          style={{
            color: meta.color,
            background: meta.hollow ? "transparent" : meta.color,
            border: meta.hollow ? `1.5px solid ${meta.color}` : undefined,
            animation: meta.hollow ? "none" : undefined,
          }}
          aria-hidden
        />
        <span className="fg-label !text-ink !tracking-[0.14em]">Miguel · {meta.label}</span>
      </div>
      <p className="mt-1 pl-[17px] text-[13px] leading-snug text-ink-2">{note}</p>
    </div>
  );
}

type StickerTone = "sun" | "sky" | "ember" | "paper";
const STICKER_BG: Record<StickerTone, string> = {
  sun: "#f6cf63",
  sky: "#b5cbea",
  ember: "#f2ae8b",
  paper: "#fffaf1",
};

/** A primary action with the most personality: a die-cut sticker with a little object on it. */
export function StickerButton({
  href,
  onClick,
  tone,
  glyph,
  title,
  subtitle,
  tilt = 0,
  disabled,
}: {
  href?: string;
  onClick?: () => void;
  tone: StickerTone;
  glyph: GlyphName;
  title: string;
  subtitle?: string;
  tilt?: number;
  disabled?: boolean;
}) {
  const body = (
    <>
      <span
        className="absolute -right-2 -top-4 rotate-[8deg] drop-shadow-[0_2px_0_rgba(42,38,48,0.12)]"
        aria-hidden
      >
        <Glyph name={glyph} size={44} diecut />
      </span>
      <span className="block text-left">
        <span className="fg-display block pr-7 text-[21px] font-[560] leading-[1.05] text-ink">{title}</span>
        {subtitle && <span className="mt-1.5 block text-[12.5px] leading-tight text-ink/70">{subtitle}</span>}
      </span>
    </>
  );
  const className = `sticker block w-full px-4 pb-4 pt-[18px] ${disabled ? "opacity-50" : ""}`;
  const style = { background: STICKER_BG[tone], transform: `rotate(${tilt}deg)` };
  if (href && !disabled) {
    return (
      <Link href={href} className={className} style={style}>
        {body}
      </Link>
    );
  }
  return (
    <button type="button" onClick={onClick} disabled={disabled} className={className} style={style}>
      {body}
    </button>
  );
}

/** A quiet text action: "See all →". */
export function QuietLink({ href, children, onClick }: { href?: string; children: ReactNode; onClick?: () => void }) {
  const cls =
    "fg-label inline-flex items-center gap-1 !text-ink underline decoration-sand decoration-[1.5px] underline-offset-[5px] active:opacity-60";
  if (href)
    return (
      <Link href={href} className={cls}>
        {children}
      </Link>
    );
  return (
    <button type="button" className={cls} onClick={onClick}>
      {children}
    </button>
  );
}

/** Back button + optional right slot. */
export function TopBar({ back = "/family", right }: { back?: string; right?: ReactNode }) {
  return (
    <div className="flex h-11 items-center justify-between">
      <Link
        href={back}
        aria-label="Back"
        className="-ml-1 flex h-10 w-10 items-center justify-center rounded-full bg-paper-2 text-ink active:scale-95"
      >
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
          <path d="M15 5l-7 7 7 7" />
        </svg>
      </Link>
      {right}
    </div>
  );
}

/** Big editorial page title with a small label above. */
export function PageTitle({ label, title, children }: { label?: string; title: ReactNode; children?: ReactNode }) {
  return (
    <header className="mt-5">
      {label && <p className="fg-label">{label}</p>}
      <h1 className="fg-display mt-2 text-[38px] font-[520] leading-[1.02] text-ink">{title}</h1>
      {children && <div className="mt-3 text-[15px] leading-relaxed text-ink-2">{children}</div>}
    </header>
  );
}

/** Section heading with a hairline, field-guide style. */
export function SectionLabel({ children, right }: { children: ReactNode; right?: ReactNode }) {
  return (
    <div className="flex items-center gap-3">
      <h2 className="fg-label shrink-0">{children}</h2>
      <span className="h-px flex-1 bg-sand" aria-hidden />
      {right}
    </div>
  );
}

export function Toggle({ on, onChange, label }: { on: boolean; onChange: () => void; label: string }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={on}
      aria-label={label}
      onClick={onChange}
      className={`relative h-[30px] w-[50px] shrink-0 rounded-full border-[1.5px] border-ink transition-colors ${
        on ? "bg-sun" : "bg-paper-2"
      }`}
    >
      <span
        className={`absolute left-0 top-[2.5px] h-[22px] w-[22px] rounded-full border-[1.5px] border-ink bg-[#fffdf8] transition-transform duration-200 ${
          on ? "translate-x-[21.5px]" : "translate-x-[2.5px]"
        }`}
      />
    </button>
  );
}

const TONE_BG: Record<Tone, string> = { sun: "#f6cf63", sky: "#b5cbea", ember: "#f2ae8b", sand: "#e6d9c3" };

export function Avatar({ initials, tone, size = 44 }: { initials: string; tone: Tone; size?: number }) {
  return (
    <span
      className="fg-display flex shrink-0 items-center justify-center rounded-full border-[1.5px] border-ink text-ink"
      style={{ width: size, height: size, background: TONE_BG[tone], fontSize: size * 0.42, fontWeight: 600 }}
      aria-hidden
    >
      {initials}
    </span>
  );
}

/** A bottom sheet. Closes on scrim tap. */
export function Sheet({ open, onClose, children, label }: { open: boolean; onClose: () => void; children: ReactNode; label: string }) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center" role="dialog" aria-modal aria-label={label}>
      <button type="button" aria-label="Close" className="fg-scrim absolute inset-0 bg-ink/30" onClick={onClose} />
      <div className="fg-sheet relative w-full max-w-[440px] rounded-t-[28px] border-t-[1.5px] border-ink bg-paper px-6 pb-[calc(env(safe-area-inset-bottom,0px)+28px)] pt-3">
        <div className="mx-auto mb-4 h-1 w-10 rounded-full bg-sand" aria-hidden />
        {children}
      </div>
    </div>
  );
}

/** A full-width, quieter button for sheets and flows. */
export function PlainButton({
  children,
  onClick,
  tone = "ink",
  type = "button",
  disabled,
}: {
  children: ReactNode;
  onClick?: () => void;
  tone?: "ink" | "paper" | "alarm";
  type?: "button" | "submit";
  disabled?: boolean;
}) {
  const styles = {
    ink: "bg-ink text-paper",
    paper: "bg-paper-2 text-ink",
    alarm: "bg-alarm text-[#fffaf4]",
  }[tone];
  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled}
      className={`flex h-14 w-full items-center justify-center gap-2 rounded-2xl text-[16px] font-semibold transition active:scale-[0.98] disabled:opacity-40 ${styles}`}
    >
      {children}
    </button>
  );
}

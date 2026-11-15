"use client";

// Hidden demo controls. Open with a long press on Miguel's status (Home), "d" on a keyboard,
// or ?demo in the URL. Nothing here shows up while filming unless you open it.

import { useEffect, useState } from "react";
import { useDemoControls, useFamily } from "@/lib/family/store";
import type { MiguelMode } from "@/lib/family/types";
import { MODE_META } from "./meta";
import { Sheet } from "./ui";

const EVENT = "family:demo-panel";

export function openDemoPanel() {
  window.dispatchEvent(new Event(EVENT));
}

const MODES: MiguelMode[] = ["withMom", "delivering", "charging", "listening", "nightLight", "idle", "offline"];

export function DemoPanel() {
  const demo = useDemoControls();
  const s = useFamily();
  const [open, setOpen] = useState(false);

  useEffect(() => {
    const show = () => setOpen(true);
    const onKey = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement | null;
      if (el && (el.tagName === "INPUT" || el.tagName === "TEXTAREA")) return;
      if (e.key === "d") setOpen((o) => !o);
    };
    window.addEventListener(EVENT, show);
    window.addEventListener("keydown", onKey);
    let first: ReturnType<typeof setTimeout> | undefined;
    if (new URLSearchParams(window.location.search).has("demo")) first = setTimeout(show, 0);
    return () => {
      window.removeEventListener(EVENT, show);
      window.removeEventListener("keydown", onKey);
      clearTimeout(first);
    };
  }, []);

  if (!demo) return null;
  const close = () => setOpen(false);
  const chip = (active: boolean) =>
    `rounded-full border-[1.5px] border-ink px-3.5 py-2 text-[13.5px] font-semibold transition active:scale-95 ${
      active ? "bg-ink text-paper" : "bg-[#fffaf1] text-ink"
    }`;

  return (
    <Sheet open={open} onClose={close} label="Demo controls">
      <p className="fg-label">Demo controls · not part of the app</p>
      <h2 className="fg-display mt-1 text-[24px] font-[540]">Set the scene</h2>

      <p className="fg-label mt-5">Miguel is…</p>
      <div className="mt-2 flex flex-wrap gap-2">
        {MODES.map((m) => (
          <button
            key={m}
            type="button"
            className={chip(s.mode === m)}
            onClick={() => (m === "nightLight" ? demo.night() : demo.setMode(m))}
          >
            {MODE_META[m].label}
          </button>
        ))}
      </div>

      <p className="fg-label mt-5">When you ask to check in, Mom says…</p>
      <div className="mt-2 flex gap-2">
        <button type="button" className={chip(s.checkInAnswer === "yes")} onClick={() => demo.setCheckInAnswer("yes")}>
          Yes, come in
        </button>
        <button type="button" className={chip(s.checkInAnswer === "no")} onClick={() => demo.setCheckInAnswer("no")}>
          Not right now
        </button>
      </div>

      <div className="mt-6 grid grid-cols-2 gap-3">
        <button
          type="button"
          className="h-12 rounded-2xl bg-alarm text-[15px] font-semibold text-[#fffaf4] active:scale-[0.98]"
          onClick={() => {
            demo.triggerAlert();
            close();
          }}
        >
          Possible fall
        </button>
        <button
          type="button"
          className="h-12 rounded-2xl bg-paper-2 text-[15px] font-semibold active:scale-[0.98]"
          onClick={() => {
            demo.reset();
            close();
          }}
        >
          Reset the day
        </button>
      </div>
    </Sheet>
  );
}

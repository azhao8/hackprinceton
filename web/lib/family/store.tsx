"use client";

import { createContext, useContext, useEffect, useState, useSyncExternalStore, type ReactNode } from "react";
import { DemoSource, demoControls, demoNow, type DemoControls, type FamilySource } from "./source";
import type { FamilyState } from "./types";

interface FamilyContextValue {
  source: FamilySource;
  demo: DemoControls | null;
}

const FamilyContext = createContext<FamilyContextValue | null>(null);

let demoSingleton: DemoSource | null = null;
function getDemoSource(): DemoSource {
  // On the server (prerender), use a clock-free copy: reading the time there isn't allowed
  // and nothing on screen depends on it until the page mounts.
  if (typeof window === "undefined") return new DemoSource(() => 0);
  // In the browser, one source for the whole app session, so state survives page changes.
  if (!demoSingleton) demoSingleton = new DemoSource();
  return demoSingleton;
}

export function FamilyProvider({ children }: { children: ReactNode }) {
  const [value] = useState<FamilyContextValue>(() => {
    const source = getDemoSource();
    return { source, demo: demoControls(source) };
  });
  return <FamilyContext.Provider value={value}>{children}</FamilyContext.Provider>;
}

function useCtx(): FamilyContextValue {
  const ctx = useContext(FamilyContext);
  if (!ctx) throw new Error("useFamily must be used inside <FamilyProvider>");
  return ctx;
}

/** The current family state; re-renders when it changes. */
export function useFamily(): FamilyState {
  const { source } = useCtx();
  return useSyncExternalStore(source.subscribe, source.getState, source.getState);
}

export function useFamilyActions(): FamilySource {
  return useCtx().source;
}

export function useDemoControls(): DemoControls | null {
  return useCtx().demo;
}

/** Minutes since midnight on the demo clock, ticking every 20 s. Null until mounted (no clock on the server). */
export function useDemoMinutes(): number | null {
  const state = useFamily();
  const [nowMs, setNowMs] = useState<number | null>(null);
  useEffect(() => {
    const tick = () => setNowMs(Date.now());
    const first = setTimeout(tick, 0);
    const id = setInterval(tick, 20000);
    return () => {
      clearTimeout(first);
      clearInterval(id);
    };
  }, [state.clockSetAt]);
  return nowMs === null ? null : demoNow(state, Math.max(nowMs, state.clockSetAt));
}

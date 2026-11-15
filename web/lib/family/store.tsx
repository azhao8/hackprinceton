"use client";

import { createContext, useContext, useEffect, useState, useSyncExternalStore, type ReactNode } from "react";
import { DEMO_BY_ENV, FAMILY_TOKEN, familyWsUrl, wantsDemo } from "./config";
import { seedState } from "./seed";
import { ServerSource, serverBootState } from "./server-source";
import { DemoSource, demoControls, demoNow, type DemoControls, type FamilySource } from "./source";
import type { FamilyState } from "./types";

interface FamilyContextValue {
  source: FamilySource;
  /** Only on the demo source; the hidden demo panel needs it. */
  demo: DemoControls | null;
}

const FamilyContext = createContext<FamilyContextValue | null>(null);

/**
 * What the server prerenders and the browser hydrates with. It depends only on build-time
 * settings, so both sides agree even when `?demo` (which only the browser sees) picks the demo;
 * React then switches to the real source's state right after hydrating.
 */
const BOOT: FamilyState = DEMO_BY_ENV ? seedState(0) : serverBootState(0);
const getBoot = () => BOOT;

let singleton: FamilyContextValue | null = null;
function getSource(): FamilyContextValue {
  // On the server (prerender), a source that never connects or reads the clock.
  if (typeof window === "undefined") {
    if (DEMO_BY_ENV) return { source: new DemoSource(() => 0), demo: null };
    const url = familyWsUrl({ protocol: "http:", hostname: "localhost" });
    return { source: new ServerSource({ url, token: "", viewer: BOOT.viewer.id, now: () => 0 }), demo: null };
  }
  // In the browser, one source for the whole app session, so state survives page changes.
  if (!singleton) {
    if (wantsDemo(window.location.search)) {
      const source = new DemoSource();
      singleton = { source, demo: demoControls(source) };
    } else {
      // Viewer: the seed's circle member id until per-person tokens (T-22) say who's signed in.
      const source = new ServerSource({ url: familyWsUrl(window.location), token: FAMILY_TOKEN, viewer: BOOT.viewer.id });
      singleton = { source, demo: null };
    }
  }
  return singleton;
}

export function FamilyProvider({ children }: { children: ReactNode }) {
  const [value] = useState<FamilyContextValue>(getSource);
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
  return useSyncExternalStore(source.subscribe, source.getState, getBoot);
}

/** The latest check-in video frame (data: URL), or null. Only the check-in screen listens. */
export function useLiveFrame(): string | null {
  const { source } = useCtx();
  return useSyncExternalStore(source.subscribeFrame, source.getFrame, () => null);
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

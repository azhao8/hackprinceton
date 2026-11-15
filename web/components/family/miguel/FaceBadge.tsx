"use client";

import { useEffect, useRef } from "react";
import type { Expression } from "@/lib/family/types";
import { drawFace } from "./face";
import { voiceLevel } from "./voice";

/** Miguel's face on its own, as a small phone-shaped badge (no 3D). */
export function FaceBadge({ expression, width = 56, className = "" }: { expression: Expression; width?: number; className?: string }) {
  const ref = useRef<HTMLCanvasElement>(null);
  const height = Math.round(width * 1.42);

  useEffect(() => {
    const canvas = ref.current;
    if (!canvas) return;
    const dpr = Math.min(window.devicePixelRatio || 1, 3);
    canvas.width = Math.round(width * dpr);
    canvas.height = Math.round(height * dpr);
    const ctx = canvas.getContext("2d")!;
    let raf = 0;
    let nextBlink = 1.5;
    let blinkStart = -1;
    let mouth = 0;
    const t0 = performance.now();
    const loop = () => {
      const t = (performance.now() - t0) / 1000;
      if (t > nextBlink) {
        blinkStart = t;
        nextBlink = t + 2.6 + ((t * 7.3) % 2.2);
      }
      const bt = t - blinkStart;
      const blink = bt >= 0 && bt < 0.17 ? Math.sin((bt / 0.17) * Math.PI) : 0;
      mouth += (voiceLevel() - mouth) * 0.35;
      ctx.save();
      ctx.scale(dpr, dpr);
      // Crop the top of the phone screen: just the face.
      ctx.translate(0, -width * 0.32);
      drawFace(ctx, width, width * 2.2, {
        expression,
        blink,
        lookX: expression === "concerned" ? -0.3 : 0,
        lookY: expression === "concerned" ? 0.6 : 0,
        mouth,
        time: t,
        island: false,
      });
      ctx.restore();
      raf = requestAnimationFrame(loop);
    };
    raf = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(raf);
  }, [expression, width, height]);

  return (
    <span
      className={`inline-block overflow-hidden rounded-[14px] border-[2px] border-[#d8b57a] shadow-[0_0_0_1.5px_#2a2630] ${className}`}
      style={{ width, height }}
    >
      <canvas ref={ref} style={{ width, height, display: "block" }} aria-hidden />
    </span>
  );
}

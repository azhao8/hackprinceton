"use client";

import dynamic from "next/dynamic";
import type { Miguel3DProps } from "./Miguel3D";

const Miguel3D = dynamic(() => import("./Miguel3D"), {
  ssr: false,
  loading: () => <div className="h-full w-full" aria-hidden />,
});

/** Miguel on his little stage. The parent sets the size. */
export function MiguelStage({ className = "", floor = true, ...props }: Miguel3DProps & { className?: string; floor?: boolean }) {
  return (
    <div className={`relative ${className}`}>
      {floor && <div className="stage-floor" aria-hidden />}
      <div className="absolute inset-0">
        <Miguel3D {...props} />
      </div>
    </div>
  );
}

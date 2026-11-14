import type { Sample } from "@/lib/use-robot";

export interface Series {
  key: "pitch" | "vl" | "vr";
  label: string;
  color: string;
}

interface LineChartProps {
  title: string;
  unit: string;
  samples: Sample[];
  series: Series[];
  now: number;
  windowS: number;
  /** The y axis is symmetric around zero and grows past this to fit the data. */
  minRange: number;
}

const W = 600;
const H = 180;

/** A small dependency-free SVG chart of the last few seconds. */
export function LineChart({ title, unit, samples, series, now, windowS, minRange }: LineChartProps) {
  const peak = samples.reduce(
    (m, s) => Math.max(m, ...series.map((ser) => Math.abs(s[ser.key]))),
    0,
  );
  const range = Math.max(minRange, Math.ceil(peak * 1.2 * 10) / 10);
  const x = (at: number) => W - ((now - at) / (windowS * 1000)) * W;
  const y = (v: number) => H / 2 - (v / range) * (H / 2);

  return (
    <figure className="rounded-lg border border-line bg-panel p-4">
      <figcaption className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
        <span className="text-sm font-medium">{title}</span>
        <span className="flex gap-3 text-xs text-muted">
          {series.map((ser) => (
            <span key={ser.key} className="flex items-center gap-1.5">
              <span className="inline-block h-0.5 w-3 rounded" style={{ background: ser.color }} />
              {ser.label}
            </span>
          ))}
        </span>
      </figcaption>
      <div className="relative">
        <svg
          viewBox={`0 0 ${W} ${H}`}
          preserveAspectRatio="none"
          className="h-40 w-full"
          role="img"
          aria-label={`${title}, last ${windowS} seconds`}
        >
          <line x1={0} x2={W} y1={H / 2} y2={H / 2} className="stroke-line" strokeWidth={1} vectorEffect="non-scaling-stroke" />
          <line x1={0} x2={W} y1={1} y2={1} className="stroke-line" strokeDasharray="4 4" strokeWidth={1} vectorEffect="non-scaling-stroke" />
          <line x1={0} x2={W} y1={H - 1} y2={H - 1} className="stroke-line" strokeDasharray="4 4" strokeWidth={1} vectorEffect="non-scaling-stroke" />
          {series.map((ser) => (
            <polyline
              key={ser.key}
              fill="none"
              stroke={ser.color}
              strokeWidth={2}
              strokeLinejoin="round"
              vectorEffect="non-scaling-stroke"
              points={samples.map((s) => `${x(s.at).toFixed(1)},${y(s[ser.key]).toFixed(1)}`).join(" ")}
            />
          ))}
        </svg>
        <span className="pointer-events-none absolute left-1 top-0 font-mono text-[11px] text-muted">
          +{range} {unit}
        </span>
        <span className="pointer-events-none absolute bottom-0 left-1 font-mono text-[11px] text-muted">
          −{range} {unit}
        </span>
      </div>
      <div className="mt-1 flex justify-between font-mono text-[11px] text-muted">
        <span>−{windowS} s</span>
        <span>now</span>
      </div>
    </figure>
  );
}

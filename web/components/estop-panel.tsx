interface EStopPanelProps {
  active: boolean;
  sendFailed: boolean;
  onChange: (on: boolean) => void;
}

/** E-stop zeroes speed and turn; the robot keeps balancing (decision 0043). */
export function EStopPanel({ active, sendFailed, onChange }: EStopPanelProps) {
  return (
    <section
      aria-label="Emergency stop"
      className={`flex flex-col gap-3 rounded-lg border p-4 ${
        active ? "border-danger bg-danger/10" : "border-line bg-panel"
      }`}
    >
      <button
        type="button"
        onClick={() => onChange(true)}
        className="h-24 w-full rounded-lg bg-danger text-2xl font-bold tracking-wide text-white shadow-sm transition active:scale-[0.98] hover:bg-danger-strong focus-visible:outline-4 focus-visible:outline-offset-2 focus-visible:outline-danger"
      >
        STOP
      </button>
      {active ? (
        <div className="flex items-center justify-between gap-3">
          <p className="text-sm">
            <span className="font-semibold text-danger">E-stop on.</span> Speed and turn held at zero; still
            balancing.
          </p>
          <button
            type="button"
            onClick={() => onChange(false)}
            className="shrink-0 rounded-md border border-line bg-panel px-3 py-1.5 text-sm font-medium hover:bg-background"
          >
            Release
          </button>
        </div>
      ) : (
        <p className="text-sm text-muted">Zeroes speed and turn. The robot keeps balancing.</p>
      )}
      {sendFailed && (
        <p role="alert" className="text-sm font-medium text-danger">
          Not sent: no connection to the server.
        </p>
      )}
    </section>
  );
}

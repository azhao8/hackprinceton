"use client";

// The possible-fall alert. It takes over every screen while it's active: clear, serious,
// and built around the next step. No playfulness here.

import { useEffect, useState } from "react";
import { clockLabel } from "@/lib/family/format";
import { useFamily, useFamilyActions } from "@/lib/family/store";
import { FaceBadge } from "./miguel/FaceBadge";
import { HoldToTalk } from "./HoldToTalk";
import { PlainButton, Sheet } from "./ui";

export function AlertLayer() {
  const s = useFamily();
  const actions = useFamilyActions();
  const [confirm911, setConfirm911] = useState(false);
  const [neighborSheet, setNeighborSheet] = useState(false);
  const [dismissed, setDismissed] = useState<string | null>(null);
  const alert = s.alert;

  useEffect(() => {
    if (alert && alert.status === "active") window.scrollTo({ top: 0 });
  }, [alert]);

  if (!alert || dismissed === alert.id) return null;
  const handled = alert.status === "handled";
  const mom = s.resident.short;
  // Someone nearby who can get there fast: the circle's neighbor, if there is one.
  const neighbor = s.members.find((m) => /neighbo/i.test(m.relation));
  const byOther = alert.handledBy && alert.handledBy !== s.viewer.name ? alert.handledBy : null;
  const request = s.requests.alert;
  const waiting = request?.status === "waiting";
  const failed = request?.status === "error" ? request.message : null;

  return (
    <div className="fixed inset-0 z-40 overflow-y-auto bg-paper" role="alertdialog" aria-modal aria-labelledby="alert-title">
      <div className="fg-alert-in mx-auto max-w-[440px] px-[22px] pb-[calc(env(safe-area-inset-bottom,0px)+28px)] pt-[calc(env(safe-area-inset-top,0px)+18px)]">
        {/* Band */}
        <div className={`flex items-center gap-2.5 rounded-full px-3.5 py-2 ${handled ? "bg-paper-2" : "bg-alarm-soft"}`}>
          <span className="relative flex h-2.5 w-2.5">
            {!handled && <span className="fg-pulse-ring absolute inset-0 rounded-full bg-alarm" />}
            <span className={`relative h-2.5 w-2.5 rounded-full ${handled ? "bg-ink-3" : "bg-alarm"}`} />
          </span>
          <span className={`fg-label !tracking-[0.14em] ${handled ? "" : "!text-alarm"}`}>
            {handled ? "Handled" : "Possible fall"} · {clockLabel(alert.at)}
          </span>
        </div>

        <h1 id="alert-title" className="mt-5 text-[34px] font-[750] leading-[1.05] tracking-[-0.02em] text-ink">
          {handled ? (byOther ? `${byOther} is on it.` : "You're on it.") : `${mom} may have fallen.`}
        </h1>
        {alert.place && <p className="mt-2 text-[15px] text-ink-2">{alert.place}</p>}

        <div className="mt-6 flex items-center gap-3.5 rounded-2xl border-[1.5px] border-ink bg-[#fffaf1] p-3.5">
          <FaceBadge expression="concerned" width={50} />
          <div>
            <p className="text-[15px] font-semibold leading-snug">Miguel is staying beside her.</p>
            <p className="mt-0.5 text-[13px] leading-snug text-ink-2">He told the family at {clockLabel(alert.at)}.</p>
          </div>
        </div>

        <dl className="mt-7 space-y-5">
          <div>
            <dt className="fg-label">What Miguel saw</dt>
            <dd className="mt-1.5 text-[16px] leading-snug">{alert.saw}</dd>
            {alert.photo && (
              <dd className="mt-3">
                {/* eslint-disable-next-line @next/next/no-img-element -- a snapshot from Miguel's server, not a page asset */}
                <img src={alert.photo} alt="What Miguel's camera saw" className="w-full rounded-2xl border-[1.5px] border-ink object-cover" />
              </dd>
            )}
          </div>
          {alert.heard && (
            <div>
              <dt className="fg-label">What she said</dt>
              <dd className="fg-display mt-1.5 text-[22px] italic leading-snug">“{alert.heard}”</dd>
            </div>
          )}
          <div>
            <dt className="fg-label">What Miguel did</dt>
            <dd className="mt-2">
              <ul className="space-y-1.5">
                {alert.did.map((d) => (
                  <li key={d} className="flex items-center gap-2.5 text-[15px]">
                    <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden>
                      <circle cx="8" cy="8" r="7.2" fill="#e9e1d1" />
                      <path d="M4.6 8.3l2.2 2.1 4.6-4.8" fill="none" stroke="#2a2630" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" />
                    </svg>
                    {d}
                  </li>
                ))}
              </ul>
            </dd>
          </div>
        </dl>

        <div className="mt-8 space-y-3">
          {!handled && <HoldToTalk who={mom} tone="alarm" />}
          <div className="grid grid-cols-2 gap-3">
            <PlainButton tone="paper" onClick={() => setNeighborSheet(true)}>
              Call {neighbor ? neighbor.name : "a neighbor"}
            </PlainButton>
            <button
              type="button"
              onClick={() => setConfirm911(true)}
              className="flex h-14 items-center justify-center rounded-2xl border-[1.5px] border-alarm text-[16px] font-semibold text-alarm active:scale-[0.98]"
            >
              Call 911
            </button>
          </div>
          {handled ? (
            <PlainButton tone="ink" onClick={() => setDismissed(alert.id)}>
              Back to {mom}&rsquo;s day
            </PlainButton>
          ) : (
            <PlainButton tone="ink" onClick={() => actions.handleAlert()} disabled={waiting}>
              {waiting ? "Telling the family…" : <>I&rsquo;m on it · tell the family</>}
            </PlainButton>
          )}
          {failed && !handled && (
            <p className="text-center text-[14px] leading-snug text-alarm" role="status">
              {failed}
            </p>
          )}
        </div>
      </div>

      <Sheet open={neighborSheet} onClose={() => setNeighborSheet(false)} label={`Call ${neighbor ? neighbor.name : "a neighbor"}`}>
        <p className="fg-label">{neighbor ? neighbor.relation : "Neighbor"}</p>
        <h2 className="fg-display mt-1 text-[26px] font-[540]">{neighbor ? neighbor.name : "A neighbor"}</h2>
        <p className="mt-2 text-[15px] text-ink-2">Close by, and already has Miguel&rsquo;s alert. They can be with {mom} in minutes.</p>
        <div className="mt-5">
          <PlainButton tone="ink" onClick={() => setNeighborSheet(false)}>
            Calling… (demo)
          </PlainButton>
        </div>
      </Sheet>

      <Sheet open={confirm911} onClose={() => setConfirm911(false)} label="Call 911">
        <h2 className="text-[24px] font-[750] leading-tight">Call 911 for {mom}?</h2>
        <p className="mt-2 text-[15px] leading-relaxed text-ink-2">
          Have her address ready. Miguel stays beside her and keeps the family posted until help arrives.
        </p>
        <p className="fg-label mt-3 !text-alarm">Demo: this won&rsquo;t place a real call.</p>
        <div className="mt-5 space-y-3">
          <PlainButton tone="alarm" onClick={() => setConfirm911(false)}>
            Call 911
          </PlainButton>
          <PlainButton tone="paper" onClick={() => setConfirm911(false)}>
            Not now
          </PlainButton>
        </div>
      </Sheet>
    </div>
  );
}

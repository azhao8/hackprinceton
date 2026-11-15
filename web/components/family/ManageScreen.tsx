"use client";

import { useState, type FormEvent } from "react";
import { useFamily, useFamilyActions } from "@/lib/family/store";
import type { Routine } from "@/lib/family/types";
import { Glyph, type GlyphName } from "./Glyph";
import { Avatar, PageTitle, PlainButton, QuietLink, SectionLabel, Sheet, Toggle, TopBar } from "./ui";

const ROUTINE_GLYPH: Record<Routine["kind"], GlyphName> = {
  water: "water",
  medication: "medication",
  checkIn: "checkIn",
  nightWalk: "night",
  walk: "walk",
};

export function ManageScreen() {
  const s = useFamily();
  const actions = useFamilyActions();
  const [inviteOpen, setInviteOpen] = useState(false);
  const [name, setName] = useState("");
  const [relation, setRelation] = useState("");
  const [prefs, setPrefs] = useState({ sounds: true, pace: true, quiet: true });

  const invite = (e: FormEvent) => {
    e.preventDefault();
    actions.invite(name, relation);
    setName("");
    setRelation("");
    setInviteOpen(false);
  };

  return (
    <main className="family-page">
      <TopBar />
      <PageTitle label="Manage" title={<>Care for {s.resident.short}, together.</>}>
        What Miguel does each day, and who&rsquo;s looking after her with you.
      </PageTitle>

      <section className="fg-rise-2 mt-10">
        <SectionLabel>Routines</SectionLabel>
        <ul className="mt-2 divide-y divide-sand">
          {s.routines.map((r) => (
            <li key={r.id} className="flex items-start gap-3.5 py-4">
              <span className="mt-0.5">
                <Glyph name={ROUTINE_GLYPH[r.kind]} size={30} />
              </span>
              <div className="min-w-0 flex-1">
                <p className={`text-[16px] font-semibold leading-snug ${r.on ? "" : "text-ink-2"}`}>{r.title}</p>
                <p className="fg-label mt-1 !text-[10.5px] !tracking-[0.08em] !normal-case">{r.schedule}</p>
                <p className="mt-1 text-[13.5px] leading-snug text-ink-2">{r.detail}</p>
              </div>
              <Toggle on={r.on} onChange={() => actions.toggleRoutine(r.id)} label={`${r.title} routine`} />
            </li>
          ))}
        </ul>
      </section>

      <section className="fg-rise-3 mt-9">
        <SectionLabel right={<QuietLink onClick={() => setInviteOpen(true)}>Invite</QuietLink>}>Family circle</SectionLabel>
        <ul className="mt-5 space-y-5">
          {s.members.map((m) => (
            <li key={m.id} className="flex items-center gap-3.5">
              <Avatar initials={m.initials} tone={m.tone} />
              <div className="min-w-0 flex-1">
                <p className="text-[16px] font-semibold leading-snug">
                  {m.name}
                  {m.you && <span className="font-normal text-ink-2"> (you)</span>}
                </p>
                <p className="text-[13.5px] leading-snug text-ink-2">
                  {m.relation} · {m.access}
                </p>
              </div>
              {m.invited && (
                <span className="fg-label shrink-0 rounded-full border border-sand px-2 py-1 !text-[9.5px]">Invited</span>
              )}
            </li>
          ))}
        </ul>
      </section>

      <section className="fg-rise-4 mt-10">
        <SectionLabel>Preferences</SectionLabel>
        <ul className="mt-2 divide-y divide-sand">
          {(
            [
              ["sounds", "Alert sounds, even on silent", "For a possible fall only"],
              ["pace", "Share her walking pace with Dr. Patel", "A summary each Monday"],
              ["quiet", "Quiet hours for check-ins", "9 pm – 8 am, unless it's urgent"],
            ] as const
          ).map(([key, title, hint]) => (
            <li key={key} className="flex items-center gap-4 py-4">
              <div className="min-w-0 flex-1">
                <p className="text-[15.5px] font-semibold leading-snug">{title}</p>
                <p className="mt-0.5 text-[13px] text-ink-2">{hint}</p>
              </div>
              <Toggle on={prefs[key]} onChange={() => setPrefs((p) => ({ ...p, [key]: !p[key] }))} label={title} />
            </li>
          ))}
        </ul>
      </section>

      <p className="fg-label mt-10 text-center !text-[10px] text-ink-3">
        Miguel · Room 12 · {s.resident.home}
      </p>

      <Sheet open={inviteOpen} onClose={() => setInviteOpen(false)} label="Invite someone">
        <form onSubmit={invite}>
          <p className="fg-label">Family circle</p>
          <h2 className="fg-display mt-1 text-[26px] font-[540]">Invite someone</h2>
          <p className="mt-2 text-[14.5px] leading-relaxed text-ink-2">
            They&rsquo;ll get alerts and can send things and messages. You can change what they see later.
          </p>
          <div className="mt-5 space-y-3">
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Name"
              autoComplete="off"
              className="h-13 w-full rounded-2xl border-[1.5px] border-sand bg-[#fffaf1] px-4 py-3.5 text-[16px] outline-none placeholder:text-ink-3 focus:border-ink"
            />
            <input
              value={relation}
              onChange={(e) => setRelation(e.target.value)}
              placeholder="Relationship (granddaughter, neighbor…)"
              autoComplete="off"
              className="h-13 w-full rounded-2xl border-[1.5px] border-sand bg-[#fffaf1] px-4 py-3.5 text-[16px] outline-none placeholder:text-ink-3 focus:border-ink"
            />
          </div>
          <div className="mt-5">
            <PlainButton type="submit" disabled={!name.trim()}>
              Send invite
            </PlainButton>
          </div>
        </form>
      </Sheet>
    </main>
  );
}

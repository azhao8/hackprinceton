"use client";

// "Ask Miguel": a free-text question about her day. The server's agent answers with a
// "message" event titled "Miguel…" (contract/web/family.md, `ask`); the newest one after
// the question shows here, and it lands in her day like any other event.

import { useState, type FormEvent } from "react";
import { useFamily, useFamilyActions } from "@/lib/family/store";
import type { TimelineEvent } from "@/lib/family/types";
import { ASK_MAX } from "@/lib/family/wire";
import { FaceBadge } from "./miguel/FaceBadge";
import { SectionLabel } from "./ui";

const isAnswer = (e: TimelineEvent) => e.kind === "message" && e.title.startsWith("Miguel");

export function AskMiguel() {
  const s = useFamily();
  const actions = useFamilyActions();
  const [text, setText] = useState("");
  // The question, and the events that were already there when it was asked.
  const [asked, setAsked] = useState<{ question: string; before: Set<string> } | null>(null);
  const mom = s.resident.short;

  const request = s.requests.ask;
  const error = asked && request?.status === "error" ? request.message : null;
  const answer = asked ? [...s.events].reverse().find((e) => isAnswer(e) && !asked.before.has(e.id)) : undefined;

  const submit = (e: FormEvent) => {
    e.preventDefault();
    const question = text.trim();
    if (!question) return;
    setAsked({ question, before: new Set(s.events.map((x) => x.id)) });
    actions.ask(question);
    setText("");
  };

  return (
    <section className="fg-rise-3 mt-10">
      <SectionLabel>Ask Miguel</SectionLabel>
      <form onSubmit={submit} className="mt-4 flex items-center gap-2.5">
        <input
          value={text}
          onChange={(e) => setText(e.target.value)}
          maxLength={ASK_MAX}
          placeholder={`Did ${mom} have lunch?`}
          aria-label="Ask Miguel a question"
          enterKeyHint="send"
          autoComplete="off"
          className="h-13 min-w-0 flex-1 rounded-2xl border-[1.5px] border-sand bg-[#fffaf1] px-4 py-3.5 text-[16px] outline-none placeholder:text-ink-3 focus:border-ink"
        />
        <button
          type="submit"
          disabled={!text.trim()}
          aria-label="Ask"
          className="flex h-13 w-13 shrink-0 items-center justify-center rounded-2xl bg-ink text-paper transition active:scale-95 disabled:opacity-40"
        >
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
            <path d="M5 12h14M13 6l6 6-6 6" />
          </svg>
        </button>
      </form>

      {asked && (
        <div className="fg-rise mt-4 flex items-start gap-3.5 rounded-2xl border-[1.5px] border-ink bg-[#fffaf1] p-3.5" aria-live="polite">
          <FaceBadge expression={error ? "concerned" : answer ? "happy" : "listening"} width={40} />
          <div className="min-w-0 flex-1">
            <p className="text-[13px] leading-snug text-ink-2">
              You asked <span className="fg-display italic">“{asked.question}”</span>
            </p>
            {error ? (
              <p className="mt-1.5 text-[15px] leading-snug text-alarm">{error}</p>
            ) : answer ? (
              <>
                <p className="mt-1.5 text-[15.5px] leading-snug">{answer.note ?? answer.quote ?? answer.title}</p>
                {answer.photo && (
                  // eslint-disable-next-line @next/next/no-img-element -- a photo from Miguel's server, not a page asset
                  <img src={answer.photo} alt="What Miguel saw" className="mt-3 max-h-[240px] w-full rounded-xl border-[1.5px] border-ink object-cover" />
                )}
              </>
            ) : (
              <p className="mt-1.5 text-[15.5px] leading-snug text-ink-2">
                Miguel&rsquo;s thinking
                <span className="fg-ellipsis">
                  <span>.</span>
                  <span>.</span>
                  <span>.</span>
                </span>
              </p>
            )}
          </div>
        </div>
      )}
    </section>
  );
}

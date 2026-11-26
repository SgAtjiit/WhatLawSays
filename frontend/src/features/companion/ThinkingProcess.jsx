import { cn } from "cn";
import { BookOpen, Check, ChevronDown, ChevronUp, Scale, Search, Sparkles } from "lucide-react";
import { useEffect, useState } from "react";

const FALLBACK_PHRASES = [
  "Analyzing scenario facts & determining legal domain…",
  "Identifying applicable Indian statutes (penal, civil, procedural)…",
  "Querying vector database across BNS, BNSS, TPA & Contract Act…",
  "Evaluating statutory sections & legal exceptions…",
  "Cross-verifying facts against statutory requirements…",
  "Synthesizing legal explanation with direct statutory citations…",
];

export function ThinkingProcess({
  currentStatus,
  steps = [],
  sources = [],
  startTime,
  isStreaming = false,
  isDone = false,
  className,
}) {
  const [expanded, setExpanded] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [fallbackIndex, setFallbackIndex] = useState(0);

  // Live elapsed timer
  useEffect(() => {
    if (!startTime || isDone) return;
    const interval = setInterval(() => {
      setElapsed(Math.max(1, Math.round((Date.now() - startTime) / 1000)));
    }, 1000);
    return () => clearInterval(interval);
  }, [startTime, isDone]);

  // Subtle cycling of contextual legal thoughts if backend is quiet
  useEffect(() => {
    if (isStreaming || isDone) return;
    const interval = setInterval(() => {
      setFallbackIndex((prev) => (prev + 1) % FALLBACK_PHRASES.length);
    }, 3200);
    return () => clearInterval(interval);
  }, [isStreaming, isDone]);

  const activeMessage = currentStatus || FALLBACK_PHRASES[fallbackIndex];
  const sourcesCount = sources?.length || 0;

  // Once text is streaming or turn is finished: show a sleek collapsible summary bar
  if (isStreaming || isDone) {
    return (
      <div className={cn("mb-4 rounded-md border border-rule/80 bg-sheet-sunk/60 text-sm transition-all", className)}>
        <button
          type="button"
          onClick={() => setExpanded((prev) => !prev)}
          className="flex w-full cursor-pointer items-center justify-between px-3.5 py-2 text-left text-xs font-medium text-graphite hover:text-ink hover:bg-sheet-sunk/90 rounded-md transition-colors"
          aria-expanded={expanded}
        >
          <div className="flex items-center gap-2">
            <span className="flex size-4.5 items-center justify-center rounded-full bg-seal-tint text-seal">
              <Sparkles className="size-2.5 animate-pulse" />
            </span>
            <span className="font-semibold text-seal-strong">
              Thought for {elapsed || 1}s
            </span>
            {sourcesCount > 0 && (
              <span className="text-graphite">
                · Referenced {sourcesCount} statute section{sourcesCount === 1 ? "" : "s"}
              </span>
            )}
          </div>
          <div className="flex items-center gap-1 text-faint">
            <span className="text-[11px]">{expanded ? "Hide thinking" : "View thinking"}</span>
            {expanded ? <ChevronUp className="size-3.5" /> : <ChevronDown className="size-3.5" />}
          </div>
        </button>

        {expanded && (
          <div className="border-t border-rule/60 px-3.5 py-2.5 space-y-2 text-xs">
            <div className="space-y-1.5">
              {steps.map((step, i) => (
                <div key={i} className="flex items-center gap-2 text-graphite">
                  <span className="flex size-3.5 shrink-0 items-center justify-center rounded-full bg-ok-tint text-ok">
                    <Check className="size-2.5 stroke-[2.5]" />
                  </span>
                  <span>{step.message}</span>
                </div>
              ))}
              {sourcesCount > 0 && (
                <div className="mt-2 pt-2 border-t border-rule/40">
                  <p className="font-medium text-ink mb-1.5 flex items-center gap-1.5">
                    <BookOpen className="size-3 text-seal" />
                    Statutes evaluated:
                  </p>
                  <div className="flex flex-wrap gap-1.5">
                    {sources.map((s) => (
                      <span
                        key={s.n}
                        className="inline-flex items-center gap-1 rounded bg-sheet px-2 py-0.5 text-[11px] text-seal ring-1 ring-rule"
                      >
                        <span className="font-bold">[{s.n}]</span> {s.short_act} s.{s.section_number.replace(/^Section\s+/i, "")}
                      </span>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    );
  }

  // Active Thinking Mode (While waiting for first tokens)
  return (
    <div
      className={cn(
        "relative overflow-hidden rounded-lg border border-seal/30 bg-sheet p-4 shadow-xs transition-all animate-in fade-in duration-300",
        className,
      )}
    >
      {/* Top shimmering subtle accent line */}
      <div className="absolute inset-x-0 top-0 h-0.5 bg-gradient-to-r from-seal/20 via-seal to-seal/20 animate-pulse" />

      {/* Header bar */}
      <div className="flex items-center justify-between pb-3 border-b border-rule/60">
        <div className="flex items-center gap-2.5">
          <div className="relative flex size-6 items-center justify-center rounded-full bg-seal-tint text-seal ring-2 ring-seal/20">
            <Sparkles className="size-3.5 animate-spin duration-3000" />
            <span className="absolute -top-0.5 -right-0.5 size-2 rounded-full bg-seal animate-ping" />
          </div>
          <div>
            <h4 className="text-xs font-semibold uppercase tracking-wider text-seal-strong">
              Researching Indian Law
            </h4>
          </div>
        </div>

        {/* Live elapsed timer & wave indicator */}
        <div className="flex items-center gap-2">
          <div className="flex items-center gap-0.5" aria-hidden>
            <span className="size-1 rounded-full bg-seal animate-bounce [animation-delay:-0.3s]" />
            <span className="size-1 rounded-full bg-seal animate-bounce [animation-delay:-0.15s]" />
            <span className="size-1 rounded-full bg-seal animate-bounce" />
          </div>
          <span className="rounded-full bg-seal-tint px-2 py-0.5 text-[11px] font-medium text-seal tabular-nums">
            {elapsed}s
          </span>
        </div>
      </div>

      {/* Active Thought & Step List */}
      <div className="mt-3.5 space-y-2">
        {/* Completed steps so far */}
        {steps.map((step, idx) => (
          <div key={idx} className="flex items-center gap-2.5 text-xs text-graphite transition-all">
            <span className="flex size-4 shrink-0 items-center justify-center rounded-full bg-ok-tint text-ok">
              <Check className="size-2.5 stroke-[2.5]" />
            </span>
            <span className="line-clamp-1">{step.message}</span>
          </div>
        ))}

        {/* Current Active Step */}
        <div className="flex items-center gap-2.5 text-xs font-medium text-ink bg-seal-tint/40 rounded-md p-2 ring-1 ring-seal/20">
          <span className="relative flex size-4 shrink-0 items-center justify-center">
            <span className="absolute size-2 rounded-full bg-seal animate-ping" />
            <span className="size-2 rounded-full bg-seal" />
          </span>
          <span className="flex-1 animate-pulse">{activeMessage}</span>
        </div>

        {/* Sources retrieved preview chips */}
        {sourcesCount > 0 && (
          <div className="mt-2.5 pt-2 border-t border-rule/50">
            <p className="text-[11px] font-medium text-graphite mb-1.5 flex items-center gap-1">
              <Scale className="size-3 text-seal" />
              Retrieved {sourcesCount} statutory sections:
            </p>
            <div className="flex flex-wrap gap-1">
              {sources.map((s) => (
                <span
                  key={s.n}
                  className="inline-flex items-center gap-1 rounded bg-sheet px-1.5 py-0.5 text-[10px] text-seal-strong ring-1 ring-rule animate-in fade-in"
                >
                  <span className="font-bold">[{s.n}]</span> {s.short_act} s.{s.section_number.replace(/^Section\s+/i, "")}
                </span>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

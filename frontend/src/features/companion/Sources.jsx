import { ChevronDown, ExternalLink } from "lucide-react";
import { cn } from "cn";
import { useEffect, useRef, useState } from "react";

import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { sourceLabel } from "./AnswerText";

const PREVIEW_CHARS = 420;

/**
 * One statute section, in its own words. `collapsible` cards (under an answer,
 * on narrower screens) show one line until opened or chosen from the answer.
 */
export function SourceCard({ source, active, collapsible = false }) {
  const [whole, setWhole] = useState(false);
  const [opened, setOpened] = useState(false);
  const open = !collapsible || opened || active;
  const ref = useRef(null);
  const long = source.text.length > PREVIEW_CHARS;
  const shown = whole || !long ? source.text : `${source.text.slice(0, PREVIEW_CHARS).trimEnd()}…`;

  // Brought into view, with the marker swept across it, when its number is chosen.
  useEffect(() => {
    const title = ref.current?.querySelector("[data-sweep]");
    title?.classList.remove("marker-sweep");
    if (!active || !ref.current) return;
    ref.current.scrollIntoView({ block: "nearest", behavior: "smooth" });
    void title?.offsetWidth;
    title?.classList.add("marker-sweep");
  }, [active]);

  return (
    <article
      ref={ref}
      aria-label={`Source ${source.n}: ${sourceLabel(source)}`}
      className={cn(
        "scroll-mt-24 rounded-md border bg-sheet p-4 transition-colors",
        active ? "border-seal" : "border-rule",
        collapsible && !open && "py-3",
      )}
    >
      <header className="relative flex items-start gap-2.5">
        <span
          aria-hidden
          className="mt-0.5 grid h-5 min-w-5 shrink-0 place-items-center rounded-sm bg-seal-tint px-1 text-xs font-semibold tabular-nums text-seal"
        >
          {source.n}
        </span>
        <div className="min-w-0">
          <p className="text-xs text-graphite">
            {source.short_act} · {source.section_number}
            {source.weak && <span className="ml-2 text-medium">Weak match</span>}
          </p>
          <p className="mt-0.5 font-medium leading-snug">
            <span data-sweep className="px-0.5">{source.title}</span>
          </p>
        </div>
        {collapsible && (
          <button
            type="button"
            aria-expanded={open}
            aria-label={`${open ? "Hide" : "Show"} ${sourceLabel(source)}`}
            onClick={() => setOpened(!open)}
            className="ml-auto shrink-0 cursor-pointer rounded-sm p-1 text-graphite after:absolute after:inset-0 hover:text-seal"
          >
            <ChevronDown aria-hidden className={cn("size-4 transition-transform", open && "rotate-180")} />
          </button>
        )}
      </header>
      {open && (
        <>
          <p className="mt-3 font-serif text-[0.9375rem] leading-relaxed whitespace-pre-line text-ink">{shown}</p>
          <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs">
            {long && (
              <button
                type="button"
                onClick={() => setWhole((w) => !w)}
                className="cursor-pointer text-seal underline underline-offset-4"
              >
                {whole ? "Show less" : "Show the whole section"}
              </button>
            )}
            {source.truncated && whole && <span className="text-graphite">Shortened here. The full text is on India Code.</span>}
            {source.source_url && (
              <a
                href={source.source_url}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1 text-seal underline underline-offset-4"
              >
                Read on India Code <ExternalLink aria-hidden className="size-3" />
                <span className="sr-only">(opens in a new tab)</span>
              </a>
            )}
          </div>
        </>
      )}
    </article>
  );
}

function split(message) {
  const byN = new Map(message.sources.map((s) => [s.n, s]));
  const cited = message.cited.map((n) => byN.get(n)).filter(Boolean);
  const rest = message.sources.filter((s) => !message.cited.includes(s.n));
  return { cited, rest };
}

/** The sections behind one answer: the ones it cites, then the rest it was shown. */
export function SourceList({ message, activeN, heading, collapsible = false }) {
  const { cited, rest } = split(message);
  const [open, setOpen] = useState(false);
  const activeInRest = rest.some((s) => s.n === activeN);
  if (!message.sources.length) return null;

  return (
    <div className="space-y-3">
      {heading}
      {cited.map((source) => (
        <SourceCard key={source.n} source={source} active={activeN === source.n} collapsible={collapsible} />
      ))}
      {rest.length > 0 && (
        <Collapsible open={open || activeInRest} onOpenChange={setOpen}>
          <CollapsibleTrigger className="group flex cursor-pointer items-center gap-1.5 text-xs text-graphite hover:text-ink">
            <ChevronDown aria-hidden className="size-4 transition-transform group-data-[state=open]:rotate-180" />
            {cited.length ? `Also searched (${rest.length})` : `Sections searched (${rest.length})`}
          </CollapsibleTrigger>
          <CollapsibleContent className="mt-3 space-y-3">
            {rest.map((source) => (
              <SourceCard key={source.n} source={source} active={activeN === source.n} collapsible={collapsible} />
            ))}
          </CollapsibleContent>
        </Collapsible>
      )}
    </div>
  );
}

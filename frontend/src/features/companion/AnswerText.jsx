import { cn } from "cn";
import { useMemo } from "react";

import { parseAnswer } from "@/lib/answerText";

export function sourceLabel(source) {
  return `${source.short_act}, ${source.section_number.replace(/^Section /, "section ")}`;
}

/** A citation number in the text: a real button that shows its section. */
export function CiteButton({ n, source, active, onCite }) {
  const label = source ? `Source ${n}: ${sourceLabel(source)}` : `Source ${n}`;
  return (
    <button
      type="button"
      aria-label={label}
      title={source ? `${sourceLabel(source)}: ${source.title}` : undefined}
      aria-pressed={active}
      onClick={() => onCite?.(n)}
      className={cn(
        "mx-[0.15em] inline-grid h-[1.35em] min-w-[1.35em] cursor-pointer place-items-center rounded-sm px-[0.3em] align-[0.1em] text-[0.72em] font-semibold tabular-nums transition-colors",
        active
          ? "bg-seal text-white"
          : "bg-seal-tint text-seal ring-1 ring-seal/30 ring-inset hover:bg-seal hover:text-white",
      )}
    >
      {n}
    </button>
  );
}

function Inline({ pieces, sources, activeN, onCite }) {
  return pieces.map((piece, index) => {
    if (piece.cite != null) {
      return (
        <CiteButton
          key={index}
          n={piece.cite}
          source={sources?.find((s) => s.n === piece.cite)}
          active={activeN === piece.cite}
          onCite={onCite}
        />
      );
    }
    if (piece.bold != null) return <strong key={index} className="font-semibold">{piece.bold}</strong>;
    // A quoted phrase is usually the statute's own words, so it is set as source text.
    if (piece.quote != null) return <q key={index} className="font-serif text-[1.0625em]">{piece.quote}</q>;
    return piece.text;
  });
}

/** The companion's answer text, with its [n] markers as buttons. */
export function AnswerText({ text, sources, activeN, onCite, className }) {
  const blocks = useMemo(() => parseAnswer(text), [text]);
  return (
    <div className={cn("space-y-4", className)}>
      {blocks.map((block, index) => {
        if (block.type === "p") {
          return (
            <p key={index}>
              <Inline pieces={block.inline} sources={sources} activeN={activeN} onCite={onCite} />
            </p>
          );
        }
        const List = block.type === "ol" ? "ol" : "ul";
        return (
          <List
            key={index}
            className={cn("space-y-2 pl-6", block.type === "ol" ? "list-decimal" : "list-disc marker:text-graphite")}
          >
            {block.items.map((item, i) => (
              <li key={i}>
                <Inline pieces={item} sources={sources} activeN={activeN} onCite={onCite} />
              </li>
            ))}
          </List>
        );
      })}
    </div>
  );
}

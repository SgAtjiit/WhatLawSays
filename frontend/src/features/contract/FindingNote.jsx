import { ChevronDown, ScanText, TextSearch } from "lucide-react";
import { cn } from "cn";

import { SeverityTag, SourceQuote } from "@/components/common";
import { Button } from "@/components/ui/button";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";

export function clauseLabel(review, index, number) {
  if (number) return `Clause ${number}`;
  if (index == null) return null;
  const clause = review.clauses.find((c) => c.index === index);
  if (clause?.number) return `Clause ${clause.number}`;
  if (clause?.heading) return clause.heading;
  return index === 0 ? "Opening" : `Paragraph ${index + 1}`;
}

export function Citations({ citations, className }) {
  if (!citations?.length) return null;
  return (
    <div className={cn("space-y-1", className)}>
      {citations.map((citation) => (
        <Collapsible key={`${citation.act}-${citation.section_number}`}>
          <CollapsibleTrigger className="group inline-flex cursor-pointer items-center gap-1.5 text-left text-xs font-medium text-seal hover:text-seal-strong">
            {citation.section_number}, {citation.act}
            <ChevronDown aria-hidden className="size-3.5 transition-transform group-data-[state=open]:rotate-180" />
          </CollapsibleTrigger>
          {citation.note && (
            <CollapsibleContent className="mt-1 max-w-measure text-xs text-graphite">{citation.note}</CollapsibleContent>
          )}
        </Collapsible>
      ))}
    </div>
  );
}

/**
 * One finding: what the clause says (quoted), what it means, why it matters,
 * and the law behind it.
 */
export function FindingNote({ finding, review, compact = false, onShowInDocument, showQuote = true }) {
  const where = clauseLabel(review, finding.clause_index, finding.clause_number);
  const fromScan = Boolean(finding.evidence_image);

  return (
    <article className="min-w-0 [&_p]:max-w-measure">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <SeverityTag severity={finding.severity} />
        {where && <span className="text-xs text-graphite">{where}</span>}
        {finding.detector === "llm" && <span className="text-xs text-graphite">Suggested by the model</span>}
      </div>
      <h3 className={cn("mt-2 font-medium", compact ? "text-base" : "text-xl")}>{finding.title}</h3>

      {showQuote && <SourceQuote className="mt-3">{finding.matched_quote}</SourceQuote>}

      {fromScan && (
        <figure className="mt-3">
          <img
            src={finding.evidence_image}
            alt={`The part of the scanned page this was read from: ${finding.matched_quote}`}
            className="max-h-48 rounded-sm border border-rule bg-sheet object-contain"
          />
          <figcaption className="mt-1.5 flex items-start gap-1.5 text-xs text-graphite">
            <ScanText aria-hidden className="mt-0.5 size-3.5 shrink-0" />
            Read from your scan
            {finding.read_confidence != null && ` (lowest word confidence ${Math.round(finding.read_confidence)}%)`}. If
            the image doesn't match the quote, ignore this finding.
          </figcaption>
        </figure>
      )}

      {finding.plain_summary && <p className={cn("mt-3", compact && "text-[0.9375rem]")}>{finding.plain_summary}</p>}
      {finding.why_it_matters && (
        <p className={cn("mt-2 text-graphite", compact && "text-[0.9375rem]")}>{finding.why_it_matters}</p>
      )}

      <Citations citations={finding.citations} className="mt-3" />

      {onShowInDocument && (
        <Button variant="link" size="sm" className="mt-3" onClick={() => onShowInDocument(finding)}>
          <TextSearch aria-hidden /> Show in the document
        </Button>
      )}
    </article>
  );
}

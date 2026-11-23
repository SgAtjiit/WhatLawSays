import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, ChevronDown, Copy, Download, Loader2, Trash2 } from "lucide-react";
import { useCallback, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router";
import { toast } from "sonner";
import { cn } from "cn";

import { deleteContract, downloadReport, getContract } from "@/api/endpoints";
import { ConfidenceBreakdown } from "@/components/Confidence";
import { EmptyState, ErrorState, Notice, SeverityTag, SourceQuote, Working } from "@/components/common";
import { Splash } from "@/components/Splash";
import { TechnicalDetails } from "@/components/TechnicalDetails";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { AskSheet } from "@/features/contract/AskSheet";
import { DocumentView } from "@/features/contract/DocumentView";
import { Citations, FindingNote, clauseLabel } from "@/features/contract/FindingNote";
import {
  CONTRACT_COMPONENT_LABEL,
  CONTRACT_TYPE_LABEL,
  POSITION_LABEL,
  SEVERITY_ORDER,
  TIER_LABEL,
  bySeverity,
  confidenceWord,
  findingKey,
  humanize,
  percent,
} from "@/lib/legal";
import { NotFound } from "@/routes/NotFound";

const RISK_HEADLINE = {
  CRITICAL: "Critical risks",
  HIGH: "High risk",
  MEDIUM: "Some risk",
  LOW: "Low risk",
};

function SectionTitle({ children, lead }) {
  return (
    <header className="mb-6">
      <h2 className="text-2xl font-semibold tracking-tight">{children}</h2>
      {lead && <p className="mt-1.5 max-w-measure text-graphite">{lead}</p>}
    </header>
  );
}

// --- Sections -----------------------------------------------------------------

function Overview({ review, go }) {
  const counts = SEVERITY_ORDER.map((s) => [s, review.risk_counts[s] || 0]).filter(([, n]) => n > 0);
  const top = [...review.findings].sort(bySeverity).slice(0, 3);
  const declared = review.position_source === "USER_DECLARED";
  const side = POSITION_LABEL[review.position];

  return (
    <div className="space-y-10">
      <div>
        <p className="text-3xl font-semibold tracking-tight">
          {RISK_HEADLINE[review.overall_risk] || "Risk not assessed"}
          {review.position !== "UNKNOWN" && <span className="text-graphite"> for {side}</span>}
        </p>
        {counts.length > 0 && (
          <dl className="mt-5 flex flex-wrap gap-x-8 gap-y-3">
            {counts.map(([severity, count]) => (
              <div key={severity} className="flex items-baseline gap-2">
                <dd className="tabular text-2xl font-semibold">{count}</dd>
                <dt>
                  <SeverityTag severity={severity} />
                </dt>
              </div>
            ))}
          </dl>
        )}
        <dl className="mt-6 grid max-w-2xl gap-x-8 gap-y-2 sm:grid-cols-2">
          <div className="flex justify-between gap-4 border-b border-rule py-2">
            <dt className="text-graphite">Clauses analysed</dt>
            <dd className="tabular">
              {review.analysed_clause_count} of {review.clause_count}
            </dd>
          </div>
          <div className="flex justify-between gap-4 border-b border-rule py-2">
            <dt className="text-graphite">Confidence</dt>
            <dd>
              <button type="button" onClick={() => go("confidence")} className="cursor-pointer underline decoration-rule-strong underline-offset-4 hover:decoration-seal">
                {confidenceWord(review.confidence_score)} ({percent(review.confidence_score)})
              </button>
            </dd>
          </div>
          <div className="flex justify-between gap-4 border-b border-rule py-2">
            <dt className="text-graphite">Missing protections</dt>
            <dd className="tabular">{review.missing_clauses.length}</dd>
          </div>
          {review.governing_law && (
            <div className="flex justify-between gap-4 border-b border-rule py-2">
              <dt className="text-graphite">Governing law</dt>
              <dd className="text-right">{review.governing_law}</dd>
            </div>
          )}
        </dl>
      </div>

      <div className="space-y-3">
        {!declared && (
          <Notice tone="warning" title={review.position_source === "LLM_INFERRED" ? `We assumed you are ${side}` : "No side was chosen"}>
            {review.position_source === "LLM_INFERRED"
              ? "If that's wrong, review the contract again and choose your side: the same clause can be serious for one party and routine for the other."
              : "Severities aren't weighted for you. Review again and choose your side for a sharper result."}
          </Notice>
        )}
        {review.source === "ocr" && (
          <Notice tone="warning" title="Read from an image">
            This document had no text layer, so we read it by OCR
            {review.ocr_confidence != null && ` with ${Math.round(review.ocr_confidence)}% mean confidence`}
            {review.ocr_basis?.low_confidence_words ? `, and ${review.ocr_basis.low_confidence_words} words were hard to read` : ""}.
            Digits in amounts are the most common misreading. Each red flag shows the part of the page it came from.
          </Notice>
        )}
        {review.extraction_warnings.map((warning) => (
          <Notice key={warning} tone="warning">
            {warning}
          </Notice>
        ))}
        {review.degraded_nodes.length > 0 && (
          <Notice title="Part of the review ran in a reduced mode">
            Some stages fell back to fixed rules ({review.degraded_nodes.map(humanize).join(", ")}), so confidence
            is capped. Every red flag shown is still quoted from your document.
          </Notice>
        )}
        {review.clarification_questions.length > 0 && (
          <Notice title="Worth checking">
            <ul className="mt-1 list-disc space-y-1 pl-5">
              {review.clarification_questions.map((question) => (
                <li key={question}>{question}</li>
              ))}
            </ul>
          </Notice>
        )}
      </div>

      <div>
        <h2 className="text-xl font-medium">Most serious</h2>
        {top.length === 0 ? (
          <NoFlags review={review} className="mt-4" />
        ) : (
          <ul className="mt-4 divide-y divide-rule border-y border-rule">
            {top.map((finding) => (
              <li key={findingKey(finding)}>
                <button
                  type="button"
                  onClick={() => go("flags")}
                  className="flex w-full cursor-pointer flex-col items-start gap-1 py-3.5 text-left hover:text-seal-strong sm:flex-row sm:items-center sm:gap-3"
                >
                  <SeverityTag severity={finding.severity} />
                  <span className="font-medium">{finding.title}</span>
                  <span className="text-xs text-graphite">
                    {clauseLabel(review, finding.clause_index, finding.clause_number)}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        )}
        {review.findings.length > 3 && (
          <Button variant="link" className="mt-3" onClick={() => go("flags")}>
            See all {review.findings.length} red flags
          </Button>
        )}
      </div>
    </div>
  );
}

function NoFlags({ review, className }) {
  return (
    <EmptyState className={className} title="No red flags matched">
      None of the known risky patterns matched the {review.analysed_clause_count} clauses analysed. That isn't a clean
      bill of health: check what's missing, and have a lawyer read anything you're about to be bound by.
    </EmptyState>
  );
}

function RedFlags({ review, showInDocument }) {
  const findings = [...review.findings].sort(bySeverity);
  return (
    <div>
      <SectionTitle lead="Terms that work against you, each quoted from your document with the law behind it.">
        Red flags
      </SectionTitle>
      {findings.length === 0 ? (
        <NoFlags review={review} />
      ) : (
        <ol className="divide-y divide-rule">
          {findings.map((finding) => (
            <li key={findingKey(finding)} className="py-8 first:pt-0">
              <FindingNote finding={finding} review={review} onShowInDocument={showInDocument} />
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}

function CopyButton({ text }) {
  const [copied, setCopied] = useState(false);
  return (
    <Button
      variant="ghost"
      size="sm"
      onClick={async () => {
        await navigator.clipboard.writeText(text);
        setCopied(true);
        setTimeout(() => setCopied(false), 1800);
      }}
    >
      {copied ? <Check aria-hidden /> : <Copy aria-hidden />}
      {copied ? "Copied" : "Copy wording"}
    </Button>
  );
}

function Redlines({ review }) {
  return (
    <div>
      <SectionTitle lead="Negotiation asks for each red flag, worst first. Use the wording as a starting point, not as drafting to paste unread.">
        What to ask for
      </SectionTitle>
      {review.redlines.length === 0 ? (
        <p className="text-graphite">Nothing to ask for: no red flags matched.</p>
      ) : (
        <ol className="divide-y divide-rule">
          {review.redlines.map((redline) => (
            <li key={`${redline.rule_id}-${redline.clause_index}`} className="py-8 first:pt-0">
              <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                <SeverityTag severity={redline.severity} />
                <span className="text-xs text-graphite">
                  {clauseLabel(review, redline.clause_index, redline.clause_number)}
                </span>
              </div>
              <h3 className="mt-2 text-xl font-medium">{redline.title}</h3>
              <dl className="mt-4 max-w-measure space-y-4">
                <div>
                  <dt className="font-medium">Ask for</dt>
                  <dd className="mt-1">{redline.ask}</dd>
                </div>
                {redline.suggested_wording && (
                  <div>
                    <dt className="flex items-center justify-between gap-2 font-medium">
                      Suggested wording
                      <CopyButton text={redline.suggested_wording} />
                    </dt>
                    <dd className="mt-1">
                      <SourceQuote>{redline.suggested_wording}</SourceQuote>
                    </dd>
                  </div>
                )}
                {redline.fallback && (
                  <div>
                    <dt className="font-medium">If they refuse</dt>
                    <dd className="mt-1 text-graphite">{redline.fallback}</dd>
                  </div>
                )}
              </dl>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}

function Clauses({ review, openClause, onOpenClause }) {
  const [flaggedOnly, setFlaggedOnly] = useState(false);
  const clauses = flaggedOnly ? review.clauses.filter((c) => c.findings.length) : review.clauses;
  return (
    <div>
      <SectionTitle lead="Every clause in plain words: what it says, what it asks of you, and what to watch.">
        Clause by clause
      </SectionTitle>
      <label className="mb-4 inline-flex cursor-pointer items-center gap-2 text-[0.9375rem]">
        <input
          type="checkbox"
          checked={flaggedOnly}
          onChange={(event) => setFlaggedOnly(event.target.checked)}
          className="size-4 accent-seal"
        />
        Only clauses with red flags
      </label>
      <ul className="divide-y divide-rule border-y border-rule">
        {clauses.map((clause) => {
          const worst = [...clause.findings].sort(bySeverity)[0];
          return (
            <li key={clause.index} id={`clause-${clause.index}`} className="scroll-mt-32">
              <Collapsible
                open={openClause === clause.index}
                onOpenChange={(open) => onOpenClause(open ? clause.index : null)}
              >
                <CollapsibleTrigger className="group flex w-full cursor-pointer items-start gap-3 py-4 text-left">
                  <span className="tabular w-12 shrink-0 pt-0.5 text-xs text-graphite">{clause.number || `¶ ${clause.index + 1}`}</span>
                  <span className="min-w-0 flex-1">
                    <span className="font-medium">{clause.heading || humanize(clause.category)}</span>
                    <span className="mt-0.5 block text-xs text-graphite">
                      {humanize(clause.category)}, {(TIER_LABEL[clause.tier] || clause.tier).toLowerCase()}
                    </span>
                  </span>
                  {worst && <SeverityTag severity={worst.severity} />}
                  <ChevronDown aria-hidden className="mt-1 size-4 shrink-0 text-graphite transition-transform group-data-[state=open]:rotate-180" />
                </CollapsibleTrigger>
                <CollapsibleContent className="pb-6 pl-0 sm:pl-15">
                  <div className="max-w-measure space-y-4">
                    {clause.plain_english && <p>{clause.plain_english}</p>}
                    {clause.obligations.length > 0 && (
                      <div>
                        <h4 className="font-medium">What it asks of you</h4>
                        <ul className="mt-1 list-disc space-y-1 pl-5 text-graphite">
                          {clause.obligations.map((item) => (
                            <li key={item}>{item}</li>
                          ))}
                        </ul>
                      </div>
                    )}
                    {clause.watch_outs.length > 0 && (
                      <div>
                        <h4 className="font-medium">Watch out for</h4>
                        <ul className="mt-1 list-disc space-y-1 pl-5 text-graphite">
                          {clause.watch_outs.map((item) => (
                            <li key={item}>{item}</li>
                          ))}
                        </ul>
                      </div>
                    )}
                    {clause.findings.length > 0 && (
                      <ul className="space-y-1">
                        {clause.findings.map((finding) => (
                          <li key={findingKey(finding)} className="flex flex-wrap items-center gap-2">
                            <SeverityTag severity={finding.severity} />
                            {finding.title}
                          </li>
                        ))}
                      </ul>
                    )}
                    <Citations citations={clause.citations} />
                    <div>
                      <h4 className="mb-2 text-xs text-graphite">The clause as written{clause.page ? `, page ${clause.page}` : ""}</h4>
                      <SourceQuote>
                        <span className="whitespace-pre-line">{clause.text}</span>
                      </SourceQuote>
                    </div>
                  </div>
                </CollapsibleContent>
              </Collapsible>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

function Missing({ review }) {
  const items = [...review.missing_clauses].sort(bySeverity);
  return (
    <div>
      <SectionTitle lead="Protections a contract like this usually gives you, and this one doesn't.">What's missing</SectionTitle>
      {items.length === 0 ? (
        <p className="text-graphite">Nothing from the usual checklist is missing for this kind of contract.</p>
      ) : (
        <ul className="divide-y divide-rule">
          {items.map((item) => (
            <li key={`${item.category}-${item.title}`} className="py-6 first:pt-0">
              <SeverityTag severity={item.severity} />
              <h3 className="mt-2 text-xl font-medium">{item.title}</h3>
              <p className="mt-1 max-w-measure text-graphite">{item.why_it_matters}</p>
              <Citations citations={item.citations} className="mt-3" />
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function Consistency({ review, goToClause }) {
  return (
    <div>
      <SectionTitle lead="Places where the contract contradicts itself or points at something that isn't there.">
        Consistency
      </SectionTitle>
      {review.consistency_issues.length === 0 ? (
        <p className="text-graphite">No contradictions or broken references were found.</p>
      ) : (
        <ul className="divide-y divide-rule">
          {review.consistency_issues.map((issue) => (
            <li key={issue.description} className="py-6 first:pt-0">
              <SeverityTag severity={issue.severity} />
              <p className="mt-2 max-w-measure">{issue.description}</p>
              {issue.quotes.length > 0 && (
                <div className="mt-4 space-y-3">
                  {issue.quotes.map((quote) => (
                    <SourceQuote key={quote}>{quote}</SourceQuote>
                  ))}
                </div>
              )}
              {issue.clause_indices.length > 0 && (
                <div className="mt-3 flex flex-wrap gap-2">
                  {issue.clause_indices.map((index) => (
                    <Button key={index} variant="outline" size="sm" onClick={() => goToClause(index)}>
                      {clauseLabel(review, index)}
                    </Button>
                  ))}
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

// --- Page -------------------------------------------------------------------

const SECTIONS = [
  ["overview", "Overview"],
  ["flags", "Red flags"],
  ["asks", "What to ask for"],
  ["clauses", "Clauses"],
  ["missing", "What's missing"],
  ["consistency", "Consistency"],
  ["confidence", "Confidence"],
  ["document", "Document"],
  ["technical", "Technical details"],
];

function counts(review) {
  return {
    flags: review.findings.length,
    asks: review.redlines.length,
    clauses: review.clause_count,
    missing: review.missing_clauses.length,
    consistency: review.consistency_issues.length,
  };
}

function Actions({ contractId, onOpenClause }) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const download = useMutation({
    mutationFn: () => downloadReport(contractId),
    onError: (error) => toast.error(error.message),
  });
  const remove = useMutation({
    mutationFn: () => deleteContract(contractId),
    onSuccess: () => {
      queryClient.removeQueries({ queryKey: ["contract", contractId] });
      queryClient.removeQueries({ queryKey: ["contract-document", contractId] });
      queryClient.invalidateQueries({ queryKey: ["contracts"] });
      try {
        sessionStorage.removeItem(`whatlawsays:ask:${contractId}`);
      } catch {
        // Nothing stored.
      }
      toast.success("The contract and its review were deleted.");
      navigate("/reviews", { replace: true });
    },
    onError: (error) => toast.error(error.message),
  });

  return (
    <div className="flex flex-wrap gap-2">
      <AskSheet contractId={contractId} onOpenClause={onOpenClause} />
      <Button variant="outline" onClick={() => download.mutate()} disabled={download.isPending}>
        {download.isPending ? <Loader2 aria-hidden className="animate-spin" /> : <Download aria-hidden />}
        Report (PDF)
      </Button>
      <AlertDialog>
        <AlertDialogTrigger asChild>
          <Button variant="ghost" aria-label="Delete this review">
            <Trash2 aria-hidden />
            <span className="sm:hidden lg:inline">Delete</span>
          </Button>
        </AlertDialogTrigger>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete this contract and its review?</AlertDialogTitle>
            <AlertDialogDescription>
              The uploaded text and every finding are removed for good. This can't be undone.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Keep it</AlertDialogCancel>
            <AlertDialogAction className="bg-critical hover:bg-critical/90" onClick={() => remove.mutate()}>
              Delete
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}

function StillWorking({ record }) {
  return (
    <div className="mx-auto max-w-3xl px-4 py-14 sm:px-6">
      <Working
        title={`Reviewing ${record.filename || "your contract"}`}
        note="This page updates by itself when the review is ready."
      />
    </div>
  );
}

export default function ContractReview() {
  const { contractId } = useParams();
  const [params, setParams] = useSearchParams();
  const section = SECTIONS.some(([id]) => id === params.get("section")) ? params.get("section") : "overview";
  const [focusKey, setFocusKey] = useState(null);
  const [openClause, setOpenClause] = useState(null);

  const query = useQuery({
    queryKey: ["contract", contractId],
    queryFn: ({ signal }) => getContract(contractId, { signal }),
    refetchInterval: (q) => (q.state.data && !("clauses" in q.state.data) && ["QUEUED", "RUNNING"].includes(q.state.data.status) ? 3000 : false),
  });

  const go = useCallback(
    (id) => {
      setParams(id === "overview" ? {} : { section: id }, { replace: false });
      window.scrollTo({ top: 0, behavior: "smooth" });
    },
    [setParams],
  );

  const goToClause = useCallback(
    (index) => {
      setOpenClause(index);
      setParams({ section: "clauses" });
      requestAnimationFrame(() =>
        document.getElementById(`clause-${index}`)?.scrollIntoView({ behavior: "smooth", block: "start" }),
      );
    },
    [setParams],
  );

  const showInDocument = useCallback(
    (finding) => {
      setFocusKey(findingKey(finding));
      setParams({ section: "document" });
    },
    [setParams],
  );
  const focusHandled = useCallback(() => setFocusKey(null), []);

  if (query.isPending) return <Splash />;
  if (query.isError) {
    if (query.error.kind === "not_found") {
      return (
        <NotFound title="We can't find that review">
          It may have been deleted, or it belongs to a different account.
        </NotFound>
      );
    }
    return (
      <div className="mx-auto max-w-3xl px-4 py-14 sm:px-6">
        <ErrorState error={query.error} onRetry={() => query.refetch()} />
      </div>
    );
  }

  const record = query.data;
  if (!("clauses" in record)) {
    if (record.status === "FAILED") {
      return (
        <div className="mx-auto max-w-3xl px-4 py-14 sm:px-6">
          <ErrorState error={{ message: record.error || "The review failed." }} />
          <Button asChild className="mt-6">
            <Link to="/contracts">Review another contract</Link>
          </Button>
        </div>
      );
    }
    return <StillWorking record={record} />;
  }

  const review = record;
  const tally = counts(review);
  const side = POSITION_LABEL[review.position];
  const parties = Object.values(review.party_names || {}).filter(Boolean);

  return (
    <div className="mx-auto max-w-7xl px-4 py-8 sm:px-6 sm:py-10">
      <div className="flex flex-col gap-5 border-b border-rule pb-6 lg:flex-row lg:items-end lg:justify-between">
        <div className="min-w-0">
          <p className="text-xs text-graphite">
            <Link to="/reviews" className="underline decoration-rule-strong underline-offset-4 hover:decoration-seal">
              My reviews
            </Link>
          </p>
          <h1 className="mt-2 text-3xl font-semibold tracking-tight">
            {CONTRACT_TYPE_LABEL[review.contract_type] || "Contract"}
          </h1>
          <p className="mt-1 text-graphite">
            {review.position !== "UNKNOWN" ? `Reviewed for ${side}` : "Reviewed without a side"}
            {parties.length >= 2 && `, between ${parties.slice(0, 2).join(" and ")}`}
          </p>
        </div>
        <Actions contractId={review.contract_id} onOpenClause={goToClause} />
      </div>

      <div className="mt-6 grid gap-8 lg:mt-8 lg:grid-cols-[12rem_minmax(0,1fr)] lg:gap-12">
        <nav aria-label="Review sections" className="-mx-4 overflow-x-auto px-4 lg:mx-0 lg:overflow-visible lg:px-0">
          <ul className="flex gap-1 lg:sticky lg:top-24 lg:flex-col">
            {SECTIONS.map(([id, label]) => (
              <li key={id} className="shrink-0">
                <button
                  type="button"
                  aria-current={section === id ? "page" : undefined}
                  onClick={() => go(id)}
                  className={cn(
                    "flex w-full cursor-pointer items-center justify-between gap-3 rounded-md px-3 py-2 text-left text-[0.9375rem] whitespace-nowrap transition-colors",
                    section === id ? "bg-sheet font-medium text-ink shadow-[inset_2px_0_0_var(--seal)]" : "text-graphite hover:text-ink",
                  )}
                >
                  {label}
                  {tally[id] != null && <span className="tabular text-xs text-graphite">{tally[id]}</span>}
                </button>
              </li>
            ))}
          </ul>
        </nav>

        <div className="min-w-0">
          {section === "overview" && <Overview review={review} go={go} />}
          {section === "flags" && <RedFlags review={review} showInDocument={showInDocument} />}
          {section === "asks" && <Redlines review={review} />}
          {section === "clauses" && <Clauses review={review} openClause={openClause} onOpenClause={setOpenClause} />}
          {section === "missing" && <Missing review={review} />}
          {section === "consistency" && <Consistency review={review} goToClause={goToClause} />}
          {section === "confidence" && (
            <div>
              <SectionTitle>How sure is this?</SectionTitle>
              <ConfidenceBreakdown score={review.confidence_score} basis={review.confidence_basis} labels={CONTRACT_COMPONENT_LABEL} />
            </div>
          )}
          {section === "document" && (
            <div>
              <SectionTitle lead="Your contract, with every red flag highlighted where it occurs.">Document</SectionTitle>
              <DocumentView review={review} focusKey={focusKey} onFocusHandled={focusHandled} />
            </div>
          )}
          {section === "technical" && (
            <div>
              <SectionTitle>Technical details</SectionTitle>
              <TechnicalDetails data={review} filename={`contract-review-${review.contract_id}.json`} />
            </div>
          )}
          {review.disclaimer && <p className="mt-12 max-w-measure text-xs text-graphite">{review.disclaimer}</p>}
        </div>
      </div>
    </div>
  );
}


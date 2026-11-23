import { useMutation } from "@tanstack/react-query";
import { CheckCircle2, ChevronDown, CircleHelp, ShieldCheck } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useLocation } from "react-router";
import { cn } from "cn";

import { analyseScenario } from "@/api/endpoints";
import { ConfidenceBreakdown } from "@/components/Confidence";
import { ErrorState, Notice, SourceQuote, Working } from "@/components/common";
import { TechnicalDetails } from "@/components/TechnicalDetails";
import { Button } from "@/components/ui/button";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { Textarea } from "@/components/ui/textarea";
import { SCENARIO_COMPONENT_LABEL, humanize } from "@/lib/legal";
import { SAMPLE_SCENARIOS } from "@/lib/samples";

const STORAGE_KEY = "whatlawsays:scenario";
const MIN_LENGTH = 20;
const MAX_LENGTH = 5000;

const STEPS = [
  "Separating what you stated from allegations and unknowns",
  "Finding the sections of the BNS, BNSS and BSA that could apply",
  "Checking every element of each offence against the facts",
  "Verifying the analysis against the statute text",
];

function load() {
  try {
    return JSON.parse(sessionStorage.getItem(STORAGE_KEY)) || null;
  } catch {
    return null;
  }
}

function save(value) {
  try {
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify(value));
  } catch {
    // Storage full or unavailable: the result still shows, it just won't survive reload.
  }
}

function verdict(result) {
  const offences = result.identified_offenses.filter((o) => o.applicability_status !== "EXCLUDED");
  if (result.status === "NEEDS_CLARIFICATION") {
    return { tone: "question", title: "We need to know more before saying anything" };
  }
  if (result.offense_status === "NOT_ESTABLISHED") {
    return { tone: "clear", title: "No offence is established on these facts" };
  }
  if (result.status === "UNDETERMINED" || result.offense_status === "UNDETERMINED") {
    return { tone: "question", title: "The facts don't settle it yet" };
  }
  if (offences.length) {
    return {
      tone: "serious",
      title:
        offences.length === 1
          ? "One offence appears to be made out"
          : `${offences.length} offences appear to be made out`,
    };
  }
  return { tone: "question", title: humanize(result.status) };
}

const VERDICT_ICON = { clear: ShieldCheck, question: CircleHelp, serious: null };

const APPLICABILITY = {
  ESTABLISHED: { label: "Made out on these facts", className: "bg-critical-tint text-critical" },
  POTENTIAL_UNDER_INVESTIGATION: { label: "Possible, needs investigation", className: "bg-medium-tint text-medium" },
  EXCLUDED: { label: "Ruled out", className: "bg-ok-tint text-ok" },
};

const PUNISHMENT = {
  CAPITAL_LIFE: "Death or life imprisonment possible",
  SERIOUS: "Serious offence",
  MINOR: "Minor offence",
};

const AUDIT = {
  SUPPORTED: { label: "Supported", className: "text-ok" },
  UNPROVEN: { label: "Not shown yet", className: "text-medium" },
  CONTRADICTED_BY_FACT: { label: "Contradicted by the facts", className: "text-critical" },
};

const URGENCY = {
  CRITICAL: { label: "Now", className: "bg-critical-tint text-critical" },
  HIGH: { label: "Soon", className: "bg-high-tint text-high" },
  MEDIUM: { label: "When you can", className: "bg-info-tint text-info" },
};

function Pill({ className, children }) {
  return <span className={cn("rounded-sm px-2 py-0.5 text-xs font-medium", className)}>{children}</span>;
}

function Section({ id, title, children }) {
  return (
    <section id={id} aria-labelledby={`${id}-title`} className="scroll-mt-28 border-t border-rule py-10 first:border-t-0 first:pt-0">
      <h2 id={`${id}-title`} className="text-2xl font-semibold tracking-tight">
        {title}
      </h2>
      <div className="mt-5">{children}</div>
    </section>
  );
}

function FactGroup({ title, items, serif }) {
  if (!items.length) return null;
  return (
    <div>
      <h3 className="font-medium">{title}</h3>
      <ul className={cn("mt-2 max-w-measure space-y-1.5", serif ? "font-serif text-lg" : "text-graphite")}>
        {items.map((item) => (
          <li key={item} className="flex gap-3">
            <span aria-hidden className="mt-[0.7em] size-1 shrink-0 rounded-full bg-rule-strong" />
            {item}
          </li>
        ))}
      </ul>
    </div>
  );
}

function Offence({ offence }) {
  const applicability = APPLICABILITY[offence.applicability_status] || {
    label: humanize(offence.applicability_status),
    className: "bg-info-tint text-info",
  };
  return (
    <article className="border-t border-rule py-7 first:border-t-0 first:pt-0">
      <div className="flex flex-wrap items-center gap-2">
        <Pill className={applicability.className}>{applicability.label}</Pill>
        {offence.punishment_severity && PUNISHMENT[offence.punishment_severity] && (
          <Pill className="bg-info-tint text-info">{PUNISHMENT[offence.punishment_severity]}</Pill>
        )}
        {offence.cognizable != null && (
          <Pill className="bg-info-tint text-info">
            {offence.cognizable ? "Police can arrest without a warrant" : "Needs a warrant to arrest"}
          </Pill>
        )}
        {offence.bailable != null && (
          <Pill className="bg-info-tint text-info">{offence.bailable ? "Bailable" : "Not bailable"}</Pill>
        )}
      </div>
      <h3 className="mt-3 text-xl font-medium">
        {offence.section_number}, {offence.act_name}
      </h3>
      {offence.offense_description && <p className="mt-1 max-w-measure text-graphite">{offence.offense_description}</p>}
      {offence.potential_punishment && (
        <p className="mt-3 max-w-measure">
          <span className="font-medium">Punishment: </span>
          {offence.potential_punishment}
        </p>
      )}

      {offence.reasoning_chain.length > 0 && (
        <div className="mt-5">
          <h4 className="font-medium">How we got here</h4>
          <ol className="mt-2 max-w-measure list-decimal space-y-1.5 pl-5 text-graphite marker:text-faint">
            {offence.reasoning_chain.map((step) => (
              <li key={step}>{step}</li>
            ))}
          </ol>
        </div>
      )}

      {offence.element_audits.length > 0 && (
        <div className="mt-5">
          <h4 className="font-medium">Each element of the offence, against the facts</h4>
          <div className="mt-3 overflow-x-auto">
            <table className="w-full min-w-[32rem] border-collapse text-left text-[0.9375rem]">
              <thead>
                <tr className="border-b border-rule text-xs text-graphite">
                  <th scope="col" className="py-2 pr-4 font-medium">Element</th>
                  <th scope="col" className="py-2 pr-4 font-medium">Status</th>
                  <th scope="col" className="py-2 font-medium">From the facts</th>
                </tr>
              </thead>
              <tbody>
                {offence.element_audits.map((audit) => {
                  const status = AUDIT[audit.status] || { label: humanize(audit.status), className: "" };
                  return (
                    <tr key={audit.element_name} className="border-b border-rule align-top">
                      <td className="py-2.5 pr-4">{audit.element_name}</td>
                      <td className={cn("py-2.5 pr-4 font-medium whitespace-nowrap", status.className)}>{status.label}</td>
                      <td className="py-2.5 font-serif text-graphite">{audit.evidence_quote || "—"}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {offence.statutory_exceptions.length > 0 && (
        <div className="mt-5">
          <h4 className="font-medium">Exceptions considered</h4>
          <ul className="mt-2 max-w-measure space-y-2 text-graphite">
            {offence.statutory_exceptions.map((exception) => (
              <li key={exception.exception_name}>
                <span className="text-ink">{exception.exception_name}</span> — {humanize(exception.status)}
                {exception.legal_effect && `. ${exception.legal_effect}`}
              </li>
            ))}
          </ul>
        </div>
      )}

      {offence.source_verified && (
        <p className="mt-4 inline-flex items-center gap-1.5 text-xs text-ok">
          <CheckCircle2 aria-hidden className="size-4" /> Checked against the statute text
        </p>
      )}
    </article>
  );
}

const NAV = [
  ["verdict", "Verdict"],
  ["facts", "Facts"],
  ["offences", "Offences"],
  ["procedure", "Procedure"],
  ["actions", "What to do now"],
  ["technical", "Technical details"],
];

function Report({ result, scenarioText }) {
  const v = verdict(result);
  const Icon = VERDICT_ICON[v.tone];
  const facts = result.extracted_facts;
  const offences = result.identified_offenses.filter((o) => o.applicability_status !== "EXCLUDED");
  const steps = [...result.immediate_action_steps].sort((a, b) => a.step_number - b.step_number);

  return (
    <div className="grid gap-10 lg:grid-cols-[11rem_1fr]">
      <nav aria-label="Report sections" className="hidden lg:block">
        <ul className="sticky top-24 space-y-1 text-[0.9375rem]">
          {NAV.map(([id, label]) => (
            <li key={id}>
              <a href={`#${id}`} className="block rounded-md px-2 py-1.5 text-graphite hover:bg-seal-tint hover:text-seal-strong">
                {label}
              </a>
            </li>
          ))}
        </ul>
      </nav>

      <div className="min-w-0">
        <Section id="verdict" title="Verdict">
          <div className="flex items-start gap-3">
            {Icon && <Icon aria-hidden className="mt-1 size-6 shrink-0 text-seal" />}
            <p className="text-2xl font-medium tracking-tight">{v.title}</p>
          </div>
          {result.reason && <p className="mt-4 max-w-measure">{result.reason}</p>}
          <p className="mt-3 text-xs text-graphite">Area of law: {humanize(result.scenario_domain)}</p>

          {result.clarification_questions.length > 0 && (
            <Notice className="mt-6" title="Answering these would change the analysis">
              <ul className="mt-1 list-disc space-y-1 pl-5">
                {result.clarification_questions.map((question) => (
                  <li key={question}>{question}</li>
                ))}
              </ul>
            </Notice>
          )}

          <Collapsible className="mt-6 rounded-md border border-rule bg-sheet">
            <CollapsibleTrigger className="group flex w-full cursor-pointer items-center justify-between gap-3 px-4 py-3 text-left font-medium">
              How sure is this?
              <ChevronDown aria-hidden className="size-4 transition-transform group-data-[state=open]:rotate-180" />
            </CollapsibleTrigger>
            <CollapsibleContent className="border-t border-rule px-4 py-5">
              <ConfidenceBreakdown
                score={result.confidence_score}
                basis={result.confidence_basis}
                labels={SCENARIO_COMPONENT_LABEL}
              />
            </CollapsibleContent>
          </Collapsible>
        </Section>

        <Section id="facts" title="The facts, separated">
          <SourceQuote cite="What you described">{scenarioText}</SourceQuote>
          {(facts.actor || facts.action) && (
            <dl className="mt-6 grid max-w-measure grid-cols-[6rem_1fr] gap-x-4 gap-y-1.5">
              {[
                ["Who", facts.actor],
                ["What", facts.action],
                ["Involving", facts.object_involved],
              ]
                .filter(([, value]) => value)
                .map(([term, value]) => (
                  <div key={term} className="contents">
                    <dt className="text-graphite">{term}</dt>
                    <dd>{value}</dd>
                  </div>
                ))}
            </dl>
          )}
          <div className="mt-6 grid gap-8 md:grid-cols-2">
            <FactGroup title="Stated as fact" items={facts.explicit_facts} serif />
            <FactGroup title="Not in dispute" items={facts.established_facts} />
            <FactGroup title="Allegations, still to be proved" items={facts.user_allegations} />
            <FactGroup title="Not known yet" items={facts.unknown_facts} />
          </div>
          <p className="mt-6 max-w-measure text-xs text-graphite">
            Something unknown is treated as unknown, never as true or false.
          </p>
        </Section>

        <Section id="offences" title="Offences">
          {offences.length === 0 ? (
            <p className="max-w-measure text-graphite">
              No offence is made out on the facts as described. If something important is missing, add it and
              analyse again.
            </p>
          ) : (
            offences.map((offence) => <Offence key={`${offence.act_name}-${offence.section_number}`} offence={offence} />)
          )}

          {result.excluded_provisions.length > 0 && (
            <div className="mt-8 rounded-md border border-rule bg-sheet p-5">
              <h3 className="font-medium">Considered and ruled out</h3>
              <ul className="mt-3 space-y-3">
                {result.excluded_provisions.map((excluded) => (
                  <li key={`${excluded.act_name}-${excluded.section_number}`} className="max-w-measure">
                    <p>
                      {excluded.section_number}, {excluded.act_name}
                      {excluded.offense_description && <span className="text-graphite"> — {excluded.offense_description}</span>}
                    </p>
                    {excluded.contradicted_elements.length > 0 && (
                      <p className="mt-0.5 text-xs text-graphite">
                        Contradicted by the facts: {excluded.contradicted_elements.join("; ")}
                      </p>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {result.applied_defences.length > 0 && (
            <div className="mt-8">
              <h3 className="font-medium">Defences that apply</h3>
              <ul className="mt-2 max-w-measure list-disc space-y-1 pl-5 text-graphite">
                {result.applied_defences.map((defence) => (
                  <li key={defence}>{defence}</li>
                ))}
              </ul>
            </div>
          )}
        </Section>

        <Section id="procedure" title="Procedure">
          {result.procedural_provisions.length ? (
            <ul className="max-w-measure space-y-2">
              {result.procedural_provisions.map((provision) => (
                <li key={provision} className="flex gap-3">
                  <span aria-hidden className="mt-[0.7em] size-1 shrink-0 rounded-full bg-seal" />
                  {provision}
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-graphite">No procedural rules were identified for these facts.</p>
          )}
        </Section>

        <Section id="actions" title="What to do now">
          {steps.length > 0 ? (
            <ol className="space-y-6">
              {steps.map((step) => {
                const urgency = URGENCY[step.urgency] || URGENCY.MEDIUM;
                return (
                  <li key={step.step_number} className="grid grid-cols-[2rem_1fr] gap-x-3">
                    <span aria-hidden className="tabular text-2xl leading-none font-semibold text-rule-strong">
                      {step.step_number}
                    </span>
                    <div>
                      <div className="flex flex-wrap items-center gap-2">
                        <p className="font-medium">{step.title}</p>
                        <Pill className={urgency.className}>{urgency.label}</Pill>
                      </div>
                      {step.action_details && <p className="mt-1 max-w-measure text-graphite">{step.action_details}</p>}
                      {step.statutory_duty_reference && (
                        <p className="mt-1 text-xs text-graphite">Under {step.statutory_duty_reference}</p>
                      )}
                    </div>
                  </li>
                );
              })}
            </ol>
          ) : (
            <p className="text-graphite">No immediate steps were identified.</p>
          )}

          {result.citizen_duties.length > 0 && (
            <div className="mt-8">
              <h3 className="font-medium">Your duties under the law</h3>
              <ul className="mt-2 max-w-measure list-disc space-y-1 pl-5 text-graphite">
                {result.citizen_duties.map((duty) => (
                  <li key={duty}>{duty}</li>
                ))}
              </ul>
            </div>
          )}
        </Section>

        <Section id="technical" title="Technical details">
          <TechnicalDetails data={result} filename="scenario-analysis.json" />
        </Section>

        {result.disclaimer && <p className="max-w-measure pb-4 text-xs text-graphite">{result.disclaimer}</p>}
      </div>
    </div>
  );
}

export default function Scenario() {
  // Arriving from Talk it through: the conversation so far, ready to analyse.
  const prefill = useLocation().state?.prefill;
  const saved = prefill ? null : load();
  const [text, setText] = useState(() => (prefill ? prefill.slice(0, MAX_LENGTH) : saved?.text || ""));
  const [lastRun, setLastRun] = useState(saved);
  const controller = useRef(null);
  const resultRef = useRef(null);

  const analysis = useMutation({
    mutationFn: ({ scenarioText, signal }) => analyseScenario({ scenarioText, signal }),
    onSuccess: (result, { scenarioText }) => {
      const run = { text: scenarioText, result };
      setLastRun(run);
      save(run);
    },
  });

  useEffect(() => {
    if (analysis.isSuccess) resultRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [analysis.isSuccess]);

  const trimmed = text.trim();
  const tooShort = trimmed.length > 0 && trimmed.length < MIN_LENGTH;

  function submit() {
    if (trimmed.length < MIN_LENGTH || analysis.isPending) return;
    controller.current = new AbortController();
    analysis.mutate({ scenarioText: trimmed, signal: controller.current.signal });
  }

  return (
    <div className="mx-auto max-w-7xl px-4 py-10 sm:px-6 sm:py-14">
      <div className="max-w-3xl">
        <h1 className="text-3xl font-semibold tracking-tight">Describe what happened</h1>
        <p className="mt-3 max-w-measure text-xl text-graphite">
          Tell it the way you'd tell a friend: who did what, to whom, where and when. Leave out what you don't
          know. We'll say what's missing.
        </p>

        <form
          className="mt-8"
          onSubmit={(event) => {
            event.preventDefault();
            submit();
          }}
        >
          <label htmlFor="scenario" className="sr-only">
            What happened
          </label>
          <Textarea
            id="scenario"
            value={text}
            maxLength={MAX_LENGTH}
            onChange={(event) => setText(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) {
                event.preventDefault();
                submit();
              }
            }}
            placeholder="Late at night, someone broke the lock on my front door and…"
            aria-describedby="scenario-help"
            aria-invalid={tooShort || undefined}
            className="min-h-44 resize-y border-rule-strong bg-sheet p-4 font-serif text-lg shadow-none focus-visible:border-seal"
          />
          <div id="scenario-help" className="mt-2 flex flex-wrap justify-between gap-2 text-xs text-graphite">
            <span>{tooShort ? `Add a little more detail (at least ${MIN_LENGTH} characters).` : "Press Ctrl + Enter to analyse."}</span>
            <span className="tabular">
              {text.length.toLocaleString("en-IN")} / {MAX_LENGTH.toLocaleString("en-IN")}
            </span>
          </div>

          <div className="mt-6 flex flex-wrap items-center gap-x-4 gap-y-3">
            <Button type="submit" size="lg" disabled={trimmed.length < MIN_LENGTH || analysis.isPending}>
              Analyse
            </Button>
            {lastRun && !analysis.isPending && (
              <Button
                type="button"
                variant="ghost"
                onClick={() => {
                  setText("");
                  setLastRun(null);
                  analysis.reset();
                  try {
                    sessionStorage.removeItem(STORAGE_KEY);
                  } catch {
                    // Nothing to clear.
                  }
                }}
              >
                Start over
              </Button>
            )}
          </div>
        </form>

        <div className="mt-8">
          <p className="text-xs text-graphite">Or try one of these:</p>
          <ul className="mt-2 flex flex-wrap gap-2">
            {SAMPLE_SCENARIOS.map((sample) => (
              <li key={sample.label}>
                <button
                  type="button"
                  onClick={() => setText(sample.text)}
                  className="cursor-pointer rounded-full border border-rule-strong bg-sheet px-3 py-1.5 text-xs text-ink transition-colors hover:border-seal hover:text-seal-strong"
                >
                  {sample.label}
                </button>
              </li>
            ))}
          </ul>
        </div>
      </div>

      <div ref={resultRef} className="mt-12 scroll-mt-24">
        {analysis.isPending && (
          <Working
            title="Analysing what happened"
            steps={STEPS}
            note="This usually takes under a minute."
            onCancel={() => controller.current?.abort()}
          />
        )}
        {analysis.isError && analysis.error.kind !== "aborted" && (
          <ErrorState error={analysis.error} onRetry={submit} />
        )}
        {!analysis.isPending && lastRun && <Report result={lastRun.result} scenarioText={lastRun.text} />}
      </div>
    </div>
  );
}

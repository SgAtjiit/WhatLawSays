import { useMutation } from "@tanstack/react-query";
import { ArrowUp, Loader2, MessageSquareText } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { askContract } from "@/api/endpoints";
import { ErrorState, Notice } from "@/components/common";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle, SheetTrigger } from "@/components/ui/sheet";
import { Textarea } from "@/components/ui/textarea";
import { Citations } from "./FindingNote";

const SUGGESTIONS = [
  "What is my notice period?",
  "Can they end this without a reason?",
  "What happens if I break this agreement?",
];

function storageKey(contractId) {
  return `whatlawsays:ask:${contractId}`;
}

function loadHistory(contractId) {
  try {
    return JSON.parse(sessionStorage.getItem(storageKey(contractId))) || [];
  } catch {
    return [];
  }
}

function clauseName(clause) {
  if (clause.number) return `Clause ${clause.number}`;
  if (clause.heading) return clause.heading;
  return `Paragraph ${clause.index + 1}`;
}

function Answer({ turn, onOpenClause }) {
  return (
    <div className="space-y-3">
      <p className="ml-auto w-fit max-w-[85%] rounded-md bg-seal-tint px-3 py-2 text-seal-strong">{turn.question}</p>
      <div className="space-y-3">
        {!turn.answered_from_contract && (
          <Notice tone="warning" title="Your contract doesn't address this">
            The answer below is not taken from your document. Don't assume the contract gives you this protection.
          </Notice>
        )}
        <p className="whitespace-pre-line">{turn.answer}</p>
        {turn.cited_clauses.length > 0 && (
          <div>
            <p className="text-xs text-graphite">From your contract:</p>
            <ul className="mt-1 flex flex-wrap gap-1.5">
              {turn.cited_clauses.map((clause) => (
                <li key={clause.index}>
                  <button
                    type="button"
                    onClick={() => onOpenClause(clause.index)}
                    className="cursor-pointer rounded-sm border border-rule-strong px-2 py-0.5 text-xs hover:border-seal hover:text-seal-strong"
                  >
                    {clauseName(clause)}
                  </button>
                </li>
              ))}
            </ul>
          </div>
        )}
        <Citations citations={turn.statutory_context} />
        {turn.degraded && (
          <p className="text-xs text-graphite">
            The language model was unavailable, so this answer was assembled from the matching clauses alone.
          </p>
        )}
      </div>
    </div>
  );
}

export function AskSheet({ contractId, onOpenClause }) {
  const [open, setOpen] = useState(false);
  const [question, setQuestion] = useState("");
  const [history, setHistory] = useState(() => loadHistory(contractId));
  const endRef = useRef(null);
  const side = typeof window !== "undefined" && window.matchMedia("(max-width: 640px)").matches ? "bottom" : "right";

  const ask = useMutation({
    mutationFn: (text) => askContract({ contractId, question: text }),
    onSuccess: (answer) => {
      setHistory((previous) => {
        const next = [...previous, answer];
        try {
          sessionStorage.setItem(storageKey(contractId), JSON.stringify(next));
        } catch {
          // History just won't survive a reload.
        }
        return next;
      });
      setQuestion("");
    },
  });

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [history.length, ask.isPending]);

  function submit(text = question) {
    const trimmed = text.trim();
    if (trimmed.length < 3 || ask.isPending) return;
    ask.mutate(trimmed);
  }

  return (
    <Sheet open={open} onOpenChange={setOpen}>
      <SheetTrigger asChild>
        <Button variant="secondary">
          <MessageSquareText aria-hidden /> Ask the contract
        </Button>
      </SheetTrigger>
      <SheetContent
        side={side}
        className="flex w-full flex-col gap-0 p-0 sm:max-w-md data-[side=bottom]:h-[92dvh]"
      >
        <SheetHeader className="border-b border-rule px-5 py-4">
          <SheetTitle className="text-xl">Ask the contract</SheetTitle>
          <SheetDescription>
            Answered only from the clauses in your document, with the ones it relied on.
          </SheetDescription>
        </SheetHeader>

        <div className="flex-1 space-y-8 overflow-y-auto px-5 py-6">
          {history.length === 0 && !ask.isPending && (
            <div>
              <p className="text-graphite">Try asking:</p>
              <ul className="mt-3 space-y-2">
                {SUGGESTIONS.map((suggestion) => (
                  <li key={suggestion}>
                    <button
                      type="button"
                      onClick={() => submit(suggestion)}
                      className="w-full cursor-pointer rounded-md border border-rule px-3 py-2 text-left hover:border-seal hover:text-seal-strong"
                    >
                      {suggestion}
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          )}
          {history.map((turn, i) => (
            <Answer
              key={`${i}-${turn.question}`}
              turn={turn}
              onOpenClause={(index) => {
                setOpen(false);
                onOpenClause(index);
              }}
            />
          ))}
          {ask.isPending && (
            <p className="flex items-center gap-2 text-graphite" role="status">
              <Loader2 aria-hidden className="size-4 animate-spin" /> Reading the relevant clauses…
            </p>
          )}
          {ask.isError && <ErrorState error={ask.error} />}
          <div ref={endRef} />
        </div>

        <form
          className="border-t border-rule p-4"
          onSubmit={(event) => {
            event.preventDefault();
            submit();
          }}
        >
          <label htmlFor="ask-question" className="sr-only">
            Your question
          </label>
          <div className="flex items-end gap-2">
            <Textarea
              id="ask-question"
              value={question}
              maxLength={1000}
              rows={2}
              onChange={(event) => setQuestion(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && !event.shiftKey) {
                  event.preventDefault();
                  submit();
                }
              }}
              placeholder="What is my notice period?"
              className="min-h-11 resize-none bg-sheet text-base shadow-none"
            />
            <Button
              type="submit"
              size="icon"
              aria-label="Ask"
              disabled={question.trim().length < 3 || ask.isPending}
            >
              <ArrowUp aria-hidden />
            </Button>
          </div>
        </form>
      </SheetContent>
    </Sheet>
  );
}

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowRight, ArrowUp, Loader2, PanelLeft, Square } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router";

import { ApiError } from "@/api/client";
import { createConversation, getConversation, sendMessage } from "@/api/endpoints";
import { ErrorState } from "@/components/common";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle, SheetTrigger } from "@/components/ui/sheet";
import { Textarea } from "@/components/ui/textarea";
import { AnswerText } from "@/features/companion/AnswerText";
import { ConversationList, UNTITLED } from "@/features/companion/ConversationList";
import { SourceList } from "@/features/companion/Sources";
import { ThinkingProcess } from "@/features/companion/ThinkingProcess";
import { situationFrom } from "@/lib/answerText";
import { NotFound } from "@/routes/NotFound";

const MESSAGE_LIMIT = 4000;

// Situations the twelve Acts actually cover, so the first answer is a good one.
const STARTERS = [
  "Someone posted private photos of me online without my consent.",
  "The police refused to register my FIR.",
  "My landlord won't return my security deposit after I moved out.",
  "My manager keeps making sexual comments at work.",
];

const ACTS =
  "the BNS, BNSS, BSA, the Constitution, the IT Act, the POSH Act, the Contract Act, the Transfer of Property Act, the Specific Relief Act, the Arbitration Act, the Consumer Protection Act and the DPDP Act";

function Intro({ onStart }) {
  return (
    <div className="max-w-measure py-6">
      <h1 className="text-3xl font-semibold tracking-tight">Talk it through</h1>
      <p className="mt-3 text-xl text-graphite">
        Tell it what happened, in your own words. It answers from the text of Indian law, shows you the sections it
        relies on, and asks when a detail would change the answer.
      </p>
      <p className="mt-8 text-graphite">Start with one of these, or write your own below:</p>
      <ul className="mt-3 space-y-2">
        {STARTERS.map((starter) => (
          <li key={starter}>
            <button
              type="button"
              onClick={() => onStart(starter)}
              className="group flex w-full cursor-pointer items-center gap-3 rounded-md border border-rule bg-sheet px-4 py-3 text-left transition-colors hover:border-seal hover:text-seal-strong"
            >
              <span className="flex-1">{starter}</span>
              <ArrowRight aria-hidden className="size-4 shrink-0 text-graphite group-hover:text-seal" />
            </button>
          </li>
        ))}
      </ul>
      <p className="mt-8 text-xs text-graphite">
        It reads {ACTS}. Questions outside them, such as labour, family or tax law, get an honest "not covered". It
        is not a lawyer.
      </p>
    </div>
  );
}

function UserMessage({ content }) {
  return (
    <div className="ml-auto w-fit max-w-[85%] rounded-md bg-seal-tint px-4 py-3 whitespace-pre-line text-ink">
      <span className="sr-only">You said: </span>
      {content}
    </div>
  );
}

function AssistantMessage({ message, activeN, onCite, streaming }) {
  return (
    <div className="max-w-measure">
      <span className="sr-only">WhatLawSays said: </span>
      <AnswerText text={message.content} sources={message.sources} activeN={activeN} onCite={onCite} />
      {streaming && (
        <span
          aria-hidden
          className="ml-1 inline-block h-4.5 w-1.5 animate-pulse rounded-xs bg-seal align-middle shadow-xs"
        />
      )}
      {!streaming && message.sources.length > 0 && (
        <div className="mt-5 xl:hidden">
          <SourceList
            message={message}
            activeN={activeN}
            collapsible
            heading={<p className="text-xs font-medium text-graphite">The law this rests on</p>}
          />
        </div>
      )}
    </div>
  );
}

function Pending({ turn, onRetry }) {
  return (
    <>
      <li>
        <UserMessage content={turn.question} />
      </li>
      <li>
        {turn.error ? (
          <ErrorState error={turn.error} onRetry={onRetry} className="max-w-measure" />
        ) : (
          <div className="max-w-measure space-y-3">
            <ThinkingProcess
              currentStatus={turn.currentStatus}
              steps={turn.steps ?? []}
              sources={turn.sources ?? []}
              startTime={turn.startTime}
              isStreaming={Boolean(turn.text)}
              isDone={false}
            />
            {turn.text && (
              <AssistantMessage
                message={{ content: turn.text, sources: turn.sources ?? [], cited: [] }}
                streaming
              />
            )}
          </div>
        )}
      </li>
    </>
  );
}

function Composer({ value, onChange, onSend, onStop, busy, inputRef, followUp }) {
  const near = value.length > MESSAGE_LIMIT - 500;
  return (
    <form
      className="sticky bottom-0 z-10 -mx-1 bg-paper px-1 pt-3 pb-4"
      onSubmit={(event) => {
        event.preventDefault();
        onSend();
      }}
    >
      <label htmlFor="companion-message" className="sr-only">
        Your message
      </label>
      <div className="flex items-end gap-2 rounded-md border border-rule-strong bg-sheet p-2 focus-within:border-seal">
        <Textarea
          id="companion-message"
          ref={inputRef}
          value={value}
          maxLength={MESSAGE_LIMIT}
          rows={1}
          onChange={(event) => onChange(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey) {
              event.preventDefault();
              onSend();
            }
          }}
          placeholder={followUp ? "Ask a follow-up or add a detail…" : "Tell it what happened…"}
          className="field-sizing-content max-h-48 min-h-10 resize-none border-0 bg-transparent px-2 text-base shadow-none focus-visible:ring-0"
        />
        {busy ? (
          <Button type="button" size="icon" variant="outline" aria-label="Stop the answer" onClick={onStop}>
            <Square aria-hidden className="size-3.5 fill-current" />
          </Button>
        ) : (
          <Button type="submit" size="icon" aria-label="Send" disabled={!value.trim()}>
            <ArrowUp aria-hidden />
          </Button>
        )}
      </div>
      <p className="mt-2 flex justify-between gap-4 text-xs text-graphite">
        <span>Answers quote Indian statute. It isn't a lawyer, and this isn't legal advice.</span>
        {near && (
          <span className="shrink-0 tabular-nums">
            {value.length.toLocaleString("en-IN")} / {MESSAGE_LIMIT.toLocaleString("en-IN")}
          </span>
        )}
      </p>
    </form>
  );
}

export default function Companion() {
  const { conversationId } = useParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState("");
  const [turn, setTurn] = useState(null);
  const [active, setActive] = useState(null);
  const [announcement, setAnnouncement] = useState("");
  const [listOpen, setListOpen] = useState(false);
  const controller = useRef(null);
  const inputRef = useRef(null);
  const endRef = useRef(null);

  const conversation = useQuery({
    queryKey: ["conversation", conversationId],
    queryFn: ({ signal }) => getConversation(conversationId, { signal }),
    enabled: Boolean(conversationId),
  });
  const messages = conversationId ? (conversation.data?.messages ?? []) : [];
  const answers = messages.filter((m) => m.role === "assistant");
  const activeMessage =
    answers.find((m) => m.message_id === active?.messageId) ?? (turn ? null : answers[answers.length - 1]);

  // Leaving a conversation stops its answer; starting one (which changes the URL) does not.
  useEffect(() => {
    if (controller.current && controller.current.conversationId !== conversationId) controller.current.abort();
  }, [conversationId]);

  const answering = Boolean(turn);
  useEffect(() => {
    endRef.current?.scrollIntoView({ block: "end" });
  }, [messages.length, answering]);

  useEffect(() => {
    // Follow a streaming answer only while the reader is already at the bottom.
    const atBottom = window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - 200;
    if (turn?.text && atBottom) endRef.current?.scrollIntoView({ block: "end" });
  }, [turn?.text]);

  async function send(content = draft) {
    const question = content.trim();
    if (!question || (turn && !turn.error)) return;
    setDraft("");
    setAnnouncement("");
    setTurn({
      question,
      sources: null,
      text: "",
      error: null,
      startTime: Date.now(),
      currentStatus: "Analyzing scenario facts & determining legal domain…",
      steps: [],
    });
    const ctrl = new AbortController();
    try {
      let id = conversationId;
      if (!id) {
        const created = await createConversation();
        id = created.conversation_id;
        queryClient.setQueryData(["conversation", id], { ...created, messages: [] });
        ctrl.conversationId = id;
        controller.current = ctrl;
        navigate(`/talk/${id}`);
      } else {
        ctrl.conversationId = id;
        controller.current = ctrl;
      }
      await sendMessage({
        conversationId: id,
        content: question,
        signal: ctrl.signal,
        onEvent: (name, data) => {
          if (name === "status") {
            setTurn((t) => {
              if (!t) return t;
              const newSteps = [...(t.steps ?? [])];
              if (
                t.currentStatus &&
                t.currentStatus !== data.message &&
                !newSteps.some((s) => s.message === t.currentStatus)
              ) {
                newSteps.push({ message: t.currentStatus, step: t.currentStep || "step" });
              }
              return {
                ...t,
                currentStatus: data.message,
                currentStep: data.step,
                steps: newSteps,
              };
            });
          } else if (name === "sources") {
            setTurn((t) => {
              if (!t) return t;
              const newSteps = [...(t.steps ?? [])];
              if (
                t.currentStatus &&
                !newSteps.some((s) => s.message === t.currentStatus)
              ) {
                newSteps.push({ message: t.currentStatus, step: t.currentStep || "step" });
              }
              return { ...t, sources: data.sources, steps: newSteps };
            });
          } else if (name === "delta") {
            setTurn((t) => t && { ...t, text: t.text + data.text });
          } else if (name === "error") {
            throw new ApiError("server", data.detail);
          } else if (name === "done") {
            queryClient.setQueryData(["conversation", id], (old) => ({
              ...(old ?? { conversation_id: id }),
              title: data.title ?? old?.title ?? null,
              messages: [...(old?.messages ?? []), data.question, data.answer],
            }));
            queryClient.invalidateQueries({ queryKey: ["conversations"] });
            // The new answer's sections take the margin; none is opened for the
            // reader, which on a phone would scroll them away from the answer.
            setActive({ messageId: data.answer.message_id, n: null });
            setAnnouncement(`Answer ready${data.answer.cited.length ? `, citing ${data.answer.cited.length} sections` : ""}.`);
            setTurn(null);
          }
        },
      });
    } catch (error) {
      if (error?.kind === "aborted") {
        setTurn(null);
        setDraft(question);
        return;
      }
      setTurn((t) => ({ ...(t ?? { question }), error }));
      setDraft(question);
      setAnnouncement(error.message);
    } finally {
      if (controller.current === ctrl) controller.current = null;
      inputRef.current?.focus();
    }
  }

  function cite(messageId, n) {
    setActive({ messageId, n });
  }

  const loading = Boolean(conversationId) && conversation.isPending;
  if (conversationId && conversation.isError) {
    if (conversation.error.kind === "not_found") {
      return (
        <NotFound title="We can't find that conversation">
          It may have been deleted, or it belongs to a different account.
        </NotFound>
      );
    }
    return (
      <div className="mx-auto max-w-7xl px-4 py-14 sm:px-6">
        <ErrorState error={conversation.error} onRetry={() => conversation.refetch()} className="max-w-measure" />
      </div>
    );
  }

  const title = conversation.data?.title || (messages.length || turn ? UNTITLED : null);
  const empty = messages.length === 0 && !turn && !loading;

  return (
    <div className="mx-auto max-w-7xl px-4 sm:px-6">
      <p className="sr-only" role="status" aria-live="polite">
        {announcement}
      </p>
      <div className="grid lg:grid-cols-[15rem_minmax(0,1fr)] lg:gap-10 xl:grid-cols-[15rem_minmax(0,1fr)_22rem]">
        <aside className="sticky top-[var(--header-h)] hidden h-[calc(100dvh-var(--header-h))] overflow-y-auto border-r border-rule py-8 pr-4 lg:block">
          <ConversationList activeId={conversationId} />
        </aside>

        <section aria-label="Conversation" className="flex min-h-[calc(100dvh-var(--header-h))] min-w-0 flex-col">
          <div className="flex items-center justify-between gap-3 border-b border-rule py-3 lg:hidden">
            <Sheet open={listOpen} onOpenChange={setListOpen}>
              <SheetTrigger asChild>
                <Button variant="ghost" size="sm">
                  <PanelLeft aria-hidden /> Conversations
                </Button>
              </SheetTrigger>
              <SheetContent side="left" className="w-[85vw] max-w-xs p-4">
                <SheetHeader className="p-0 pb-4">
                  <SheetTitle>Conversations</SheetTitle>
                  <SheetDescription className="sr-only">Your saved conversations</SheetDescription>
                </SheetHeader>
                <ConversationList activeId={conversationId} onNavigate={() => setListOpen(false)} />
              </SheetContent>
            </Sheet>
          </div>

          <div className="flex-1 pt-8">
            {loading ? (
              <p role="status" className="flex items-center gap-2 text-graphite">
                <Loader2 aria-hidden className="size-4 animate-spin" /> Opening the conversation…
              </p>
            ) : empty ? (
              <Intro onStart={(starter) => send(starter)} />
            ) : (
              <>
                <h1 className="sr-only max-w-measure truncate text-lg font-medium text-graphite md:not-sr-only">{title}</h1>
                <ol className="space-y-8 md:mt-8">
                  {messages.map((message) => (
                    <li key={message.message_id}>
                      {message.role === "user" ? (
                        <UserMessage content={message.content} />
                      ) : (
                        <AssistantMessage
                          message={message}
                          activeN={activeMessage?.message_id === message.message_id ? active?.n : null}
                          onCite={(n) => cite(message.message_id, n)}
                        />
                      )}
                    </li>
                  ))}
                  {turn && <Pending turn={turn} onRetry={() => send(turn.question)} />}
                </ol>
                {messages.length > 0 && !turn && (
                  <p className="mt-10 max-w-measure border-t border-rule pt-5 text-graphite">
                    Want the element-by-element view?{" "}
                    <Button
                      variant="link"
                      onClick={() => navigate("/scenario", { state: { prefill: situationFrom(messages) } })}
                    >
                      Turn this into a full analysis
                    </Button>
                  </p>
                )}
              </>
            )}
            <div ref={endRef} />
          </div>

          <Composer
            value={draft}
            onChange={setDraft}
            onSend={() => send()}
            onStop={() => controller.current?.abort()}
            busy={Boolean(turn && !turn.error)}
            inputRef={inputRef}
            followUp={!empty}
          />
        </section>

        <aside
          aria-label="Sources"
          className="sticky top-[var(--header-h)] hidden h-[calc(100dvh-var(--header-h))] overflow-y-auto py-8 pl-1 xl:block"
        >
          {turn?.sources && !turn.error ? (
            <SourceList
              message={{ sources: turn.sources, cited: [] }}
              activeN={null}
              heading={<MarginHeading>Searching these sections</MarginHeading>}
            />
          ) : activeMessage?.sources.length ? (
            <SourceList
              message={activeMessage}
              activeN={active?.messageId === activeMessage.message_id ? active.n : null}
              heading={<MarginHeading>The law behind this answer</MarginHeading>}
            />
          ) : (
            <div className="border-l-2 border-marker pl-4">
              <MarginHeading>The law, in its own words</MarginHeading>
              <p className="mt-2 text-xs text-graphite">
                The sections an answer relies on appear here. Choose a number in the answer to bring its section
                up.
              </p>
            </div>
          )}
        </aside>
      </div>
    </div>
  );
}

function MarginHeading({ children }) {
  return <h2 className="text-xs font-medium text-graphite">{children}</h2>;
}

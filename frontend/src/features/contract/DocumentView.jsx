import { useQuery } from "@tanstack/react-query";
import { X } from "lucide-react";
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { cn } from "cn";

import { getContractDocument } from "@/api/endpoints";
import { ErrorState, Notice } from "@/components/common";
import { Button } from "@/components/ui/button";
import { findingKey, reflow, segmentDocument } from "@/lib/legal";
import { FindingNote } from "./FindingNote";

const NOTE_GAP = 16;

const MARK_STYLE = {
  CRITICAL: "decoration-critical",
  HIGH: "decoration-high",
  MEDIUM: "decoration-medium",
  LOW: "decoration-low",
  INFO: "decoration-info",
};

function useWide() {
  const query = "(min-width: 1280px)";
  const [wide, setWide] = useState(() => window.matchMedia(query).matches);
  useEffect(() => {
    const list = window.matchMedia(query);
    const update = () => setWide(list.matches);
    list.addEventListener("change", update);
    return () => list.removeEventListener("change", update);
  }, []);
  return wide;
}

/**
 * The contract set as a page, every finding highlighted where it occurs, with
 * its note pinned in the margin beside it. Offsets index into exactly this
 * text, which is why the document comes from the server rather than the file.
 */
export function DocumentView({ review, focusKey, onFocusHandled }) {
  const wide = useWide();
  const documentQuery = useQuery({
    queryKey: ["contract-document", review.contract_id],
    queryFn: ({ signal }) => getContractDocument(review.contract_id, { signal }),
    staleTime: Infinity,
  });

  const segments = useMemo(
    () => (documentQuery.data ? segmentDocument(reflow(documentQuery.data.text), review.findings) : []),
    [documentQuery.data, review.findings],
  );
  const drawn = useMemo(() => segments.filter((s) => s.finding).map((s) => s.finding), [segments]);

  const [active, setActive] = useState(null);
  const [sweep, setSweep] = useState(null);
  const pageRef = useRef(null);
  const marks = useRef(new Map());
  const notes = useRef(new Map());
  const [{ tops, notesHeight }, setLayout] = useState({ tops: {}, notesHeight: 0 });

  // Pin each note level with its passage, pushed down only as far as needed
  // to clear the note above it.
  const layout = useCallback(() => {
    if (!wide || !pageRef.current) return;
    const origin = pageRef.current.getBoundingClientRect().top;
    const next = {};
    let floor = 0;
    for (const finding of drawn) {
      const key = findingKey(finding);
      const mark = marks.current.get(key);
      const note = notes.current.get(key);
      if (!mark || !note) continue;
      const top = Math.max(mark.getBoundingClientRect().top - origin, floor);
      next[key] = top;
      floor = top + note.offsetHeight + NOTE_GAP;
    }
    setLayout({ tops: next, notesHeight: floor });
  }, [drawn, wide]);

  useLayoutEffect(() => {
    layout();
  }, [layout]);

  useEffect(() => {
    if (!pageRef.current) return undefined;
    const observer = new ResizeObserver(() => layout());
    observer.observe(pageRef.current);
    return () => observer.disconnect();
  }, [layout, documentQuery.data]);

  // Arriving from "Show in the document": scroll there and sweep the marker once.
  useEffect(() => {
    if (!focusKey || !documentQuery.data) return;
    const mark = marks.current.get(focusKey);
    if (mark) {
      mark.scrollIntoView({ behavior: "smooth", block: "center" });
      setActive(focusKey);
      setSweep(focusKey);
    }
    onFocusHandled?.();
  }, [focusKey, documentQuery.data, onFocusHandled]);

  if (documentQuery.isPending) {
    return <div className="h-96 animate-pulse rounded-md bg-sheet" aria-label="Loading the document" />;
  }
  if (documentQuery.isError) {
    return <ErrorState error={documentQuery.error} onRetry={() => documentQuery.refetch()} />;
  }

  const activeFinding = drawn.find((f) => findingKey(f) === active);

  return (
    <div>
      {documentQuery.data.source === "ocr" && (
        <Notice tone="warning" className="mb-6" title="This is our reading of your scan">
          The text below was read from an image, so it can differ from your paper copy. Each note shows the part of
          the page it was read from.
        </Notice>
      )}
      <p className="mb-4 text-xs text-graphite">
        {drawn.length === 0
          ? "No passages are highlighted: no red flags matched this document."
          : `${drawn.length} highlighted ${drawn.length === 1 ? "passage" : "passages"}. Select one to read its note.`}
      </p>

      <div className={cn(wide && "grid grid-cols-[minmax(0,1fr)_21rem] gap-10")}>
        <div
          ref={pageRef}
          className="rounded-md border border-rule bg-sheet px-6 py-8 sm:px-10 sm:py-12"
          style={wide ? { minHeight: notesHeight + 48 } : undefined}
        >
          <div className="mx-auto max-w-[68ch] font-serif text-lg break-words whitespace-pre-wrap text-ink">
            {segments.map((segment, i) => {
              if (!segment.finding) return <span key={i}>{segment.text}</span>;
              const key = findingKey(segment.finding);
              const isActive = active === key;
              return (
                <mark
                  key={key}
                  ref={(node) => (node ? marks.current.set(key, node) : marks.current.delete(key))}
                  role="button"
                  tabIndex={0}
                  aria-pressed={isActive}
                  aria-label={`${segment.finding.title}: ${segment.text}`}
                  onClick={() => setActive(isActive ? null : key)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" || event.key === " ") {
                      event.preventDefault();
                      setActive(isActive ? null : key);
                    }
                  }}
                  onAnimationEnd={() => setSweep(null)}
                  className={cn(
                    "cursor-pointer rounded-[2px] text-ink underline decoration-2 underline-offset-[5px] transition-colors",
                    MARK_STYLE[segment.finding.severity] || MARK_STYLE.INFO,
                    isActive ? "bg-marker" : "bg-marker-soft hover:bg-marker",
                    sweep === key && "marker-sweep",
                  )}
                >
                  {segment.text}
                </mark>
              );
            })}
          </div>
        </div>

        {wide && (
          <aside aria-label="Notes on highlighted passages" className="relative">
            {drawn.map((finding) => {
              const key = findingKey(finding);
              return (
                <div
                  key={key}
                  ref={(node) => (node ? notes.current.set(key, node) : notes.current.delete(key))}
                  className={cn(
                    "absolute inset-x-0 border-l-2 py-1 pl-4 transition-[top,border-color] duration-200",
                    active === key ? "border-seal" : "border-rule",
                  )}
                  style={{ top: tops[key] ?? 0, visibility: key in tops ? "visible" : "hidden" }}
                >
                  <FindingNote finding={finding} review={review} compact showQuote={false} />
                </div>
              );
            })}
          </aside>
        )}
      </div>

      {!wide && activeFinding && (
        <div
          role="dialog"
          aria-label="Note on the selected passage"
          className="fixed inset-x-0 bottom-0 z-40 max-h-[60vh] overflow-y-auto border-t border-rule bg-sheet px-4 pt-4 pb-[max(1rem,env(safe-area-inset-bottom))] shadow-[0_-8px_24px_rgb(18_20_26/0.08)] sm:px-6"
        >
          <div className="mx-auto flex max-w-3xl gap-3">
            <div className="min-w-0 flex-1">
              <FindingNote finding={activeFinding} review={review} compact showQuote={false} />
            </div>
            <Button variant="ghost" size="icon" aria-label="Close the note" onClick={() => setActive(null)}>
              <X aria-hidden />
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}

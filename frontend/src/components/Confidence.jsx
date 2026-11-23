import { confidenceWord, explainCap, humanize, percent } from "@/lib/legal";

/** How sure the analysis is, and exactly why, in words before numbers. */
export function ConfidenceBreakdown({ score, basis, labels }) {
  const components = Object.entries(basis?.components || {});
  const caps = basis?.caps_applied || [];
  const notes = basis?.notes || [];

  return (
    <div className="space-y-6">
      <p className="text-xl">
        <span className="font-medium">{confidenceWord(score)} confidence</span>{" "}
        <span className="tabular text-graphite">({percent(score)})</span>
      </p>
      <p className="max-w-measure text-graphite">
        This is an estimate of how far the result can be relied on, built from the measured parts below. It is not
        a probability that you are right or wrong.
      </p>

      {components.length > 0 && (
        <dl className="max-w-2xl space-y-3">
          {components.map(([key, value]) => (
            <div key={key} className="grid grid-cols-[1fr_auto] items-center gap-x-4 gap-y-1.5">
              <dt className="text-[0.9375rem]">{labels[key] || humanize(key)}</dt>
              <dd className="tabular text-xs text-graphite">{percent(value)}</dd>
              <div aria-hidden className="col-span-2 h-1 rounded-full bg-rule">
                <div className="h-full rounded-full bg-seal" style={{ width: percent(value) }} />
              </div>
            </div>
          ))}
        </dl>
      )}

      {caps.length > 0 && (
        <div>
          <h4 className="font-medium">Why it is capped</h4>
          <ul className="mt-2 max-w-measure list-disc space-y-1 pl-5 text-graphite">
            {caps.map((cap) => (
              <li key={cap}>{explainCap(cap)}</li>
            ))}
          </ul>
        </div>
      )}

      {notes.length > 0 && (
        <div>
          <h4 className="font-medium">Notes</h4>
          <ul className="mt-2 max-w-measure list-disc space-y-1 pl-5 text-graphite">
            {notes.map((note) => (
              <li key={note}>{note}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

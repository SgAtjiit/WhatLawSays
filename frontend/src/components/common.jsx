import { AlertTriangle, CircleAlert, Info, RotateCcw } from "lucide-react";
import { useEffect, useState } from "react";
import { cn } from "cn";

import { Button } from "@/components/ui/button";
import { SEVERITY_LABEL } from "@/lib/legal";

const SEVERITY_STYLE = {
  CRITICAL: "text-critical bg-critical-tint",
  HIGH: "text-high bg-high-tint",
  MEDIUM: "text-medium bg-medium-tint",
  LOW: "text-low bg-low-tint",
  INFO: "text-info bg-info-tint",
};

const SEVERITY_BAR = {
  CRITICAL: "bg-critical",
  HIGH: "bg-high",
  MEDIUM: "bg-medium",
  LOW: "bg-low",
  INFO: "bg-info",
};

/** Severity is always spelled out, never carried by colour alone. */
export function SeverityTag({ severity, className }) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-sm px-2 py-0.5 text-xs font-medium",
        SEVERITY_STYLE[severity] || SEVERITY_STYLE.INFO,
        className,
      )}
    >
      <span aria-hidden className={cn("size-1.5 rounded-full", SEVERITY_BAR[severity] || SEVERITY_BAR.INFO)} />
      {SEVERITY_LABEL[severity] || severity}
    </span>
  );
}

export function severityBar(severity) {
  return SEVERITY_BAR[severity] || SEVERITY_BAR.INFO;
}

/** Words from the source: a contract, a statute, the facts as told. */
export function SourceQuote({ children, className, cite }) {
  return (
    <figure className={cn("border-l-2 border-marker pl-4", className)}>
      <blockquote className="font-serif text-lg text-ink">{children}</blockquote>
      {cite && <figcaption className="mt-1.5 text-xs text-graphite">{cite}</figcaption>}
    </figure>
  );
}

const NOTICE_STYLE = {
  info: { box: "border-rule bg-sheet", icon: Info, iconClass: "text-seal" },
  warning: { box: "border-medium/30 bg-medium-tint", icon: AlertTriangle, iconClass: "text-medium" },
  danger: { box: "border-critical/30 bg-critical-tint", icon: CircleAlert, iconClass: "text-critical" },
};

export function Notice({ tone = "info", title, children, action, className }) {
  const style = NOTICE_STYLE[tone];
  const Icon = style.icon;
  return (
    <div
      role={tone === "danger" ? "alert" : "status"}
      className={cn("flex gap-3 rounded-md border px-4 py-3", style.box, className)}
    >
      <Icon aria-hidden className={cn("mt-0.5 size-5 shrink-0", style.iconClass)} />
      <div className="min-w-0 flex-1">
        {title && <p className="font-medium text-ink">{title}</p>}
        {children && <div className={cn("text-graphite", title && "mt-0.5")}>{children}</div>}
        {action && <div className="mt-3">{action}</div>}
      </div>
    </div>
  );
}

export function ErrorState({ error, onRetry, className }) {
  const message = error?.message || "Something went wrong.";
  return (
    <Notice
      tone="danger"
      className={className}
      title={error?.kind === "offline" ? "Can't reach the server" : "That didn't work"}
      action={
        onRetry && (
          <Button variant="outline" size="sm" onClick={onRetry}>
            <RotateCcw aria-hidden /> Try again
          </Button>
        )
      }
    >
      {message}
    </Notice>
  );
}

export function EmptyState({ title, children, action, className }) {
  return (
    <div className={cn("rounded-md border border-dashed border-rule-strong px-6 py-10 text-center", className)}>
      <p className="text-xl font-medium text-ink">{title}</p>
      {children && <div className="mx-auto mt-2 max-w-measure text-graphite">{children}</div>}
      {action && <div className="mt-5 flex justify-center">{action}</div>}
    </div>
  );
}

/** Seconds since the calling component appeared. */
function useElapsed() {
  const [started] = useState(() => Date.now());
  const [now, setNow] = useState(started);
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, []);
  return Math.floor((now - started) / 1000);
}

export function formatElapsed(seconds) {
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return m ? `${m} min ${String(s).padStart(2, "0")} s` : `${s} s`;
}

/**
 * A long wait, said honestly: how long it has been and what is happening,
 * with no invented progress percentage.
 */
export function Working({ title, steps, onCancel, note }) {
  const seconds = useElapsed();
  return (
    <section aria-live="polite" aria-busy="true" className="rounded-md border border-rule bg-sheet p-6 sm:p-8">
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <h2 className="text-xl font-medium">{title}</h2>
        <p className="tabular text-xs text-graphite">{formatElapsed(seconds)}</p>
      </div>
      <div className="relative mt-5 h-0.5 overflow-hidden rounded-full bg-rule">
        <div className="absolute inset-y-0 w-1/3 animate-[working_1.6s_var(--ease-out)_infinite] rounded-full bg-seal" />
      </div>
      {steps && (
        <ol className="mt-6 space-y-2 text-graphite">
          {steps.map((step) => (
            <li key={step} className="flex gap-3">
              <span aria-hidden className="mt-2.5 size-1 shrink-0 rounded-full bg-rule-strong" />
              {step}
            </li>
          ))}
        </ol>
      )}
      {note && <p className="mt-5 text-xs text-graphite">{note}</p>}
      {onCancel && (
        <Button variant="outline" className="mt-6" onClick={onCancel}>
          Cancel
        </Button>
      )}
    </section>
  );
}

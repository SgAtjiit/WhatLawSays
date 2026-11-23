import { ArrowRight } from "lucide-react";
import { Fragment } from "react";
import { Link, useLocation } from "react-router";

import { useAuth } from "@/auth/AuthProvider";
import { DEMO_ACCOUNTS, DEMO_ENABLED, demoAccountFor, demoHref } from "@/auth/demo";

function Initial({ name }) {
  return (
    <span aria-hidden className="grid size-9 shrink-0 place-items-center rounded-full bg-seal-tint text-sm font-semibold text-seal">
      {name.charAt(0)}
    </span>
  );
}

/** One-click sign-in rows for the sign-in screen. */
export function DemoAccountList({ next }) {
  if (!DEMO_ENABLED) return null;
  return (
    <section aria-labelledby="demo-accounts" className="mb-8">
      <h2 id="demo-accounts" className="font-medium">
        Demo accounts
      </h2>
      <p className="mt-1 text-xs text-graphite">One click, no password. They exist only on this computer.</p>
      <ul className="mt-3 divide-y divide-rule overflow-hidden rounded-md border border-rule bg-sheet">
        {DEMO_ACCOUNTS.map((account) => (
          <li key={account.id}>
            <Link
              to={demoHref(account, next)}
              className="group flex items-center gap-3 px-4 py-3 transition-colors hover:bg-sheet-sunk focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-seal"
            >
              <Initial name={account.name} />
              <span className="min-w-0 flex-1">
                <span className="block font-medium text-ink">Sign in as {account.name}</span>
                <span className="block text-xs text-graphite">{account.blurb}</span>
              </span>
              <ArrowRight aria-hidden className="size-4 shrink-0 text-graphite transition-transform group-hover:translate-x-0.5 group-hover:text-seal" />
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}

/** A slim strip above the header: says this is the demo, and switches account in one click. */
export function DemoBar() {
  const { user, status } = useAuth();
  const location = useLocation();
  if (!DEMO_ENABLED || status === "loading") return null;

  const current = demoAccountFor(user);
  const others = DEMO_ACCOUNTS.filter((account) => account !== current);
  // Switching keeps you on the same page, so a review link shows what the other account is allowed to see.
  const here = location.pathname.startsWith("/demo/") ? undefined : `${location.pathname}${location.search}`;
  const lead = current ? `Signed in as ${current.name}.` : "Local test accounts.";
  const verb = user ? "Switch to" : "Sign in as";

  return (
    <div className="border-b border-seal/20 bg-seal-tint text-seal">
      <p className="mx-auto flex max-w-7xl flex-wrap items-center justify-center gap-x-1.5 gap-y-0.5 px-4 py-1.5 text-center text-xs sm:px-6">
        <span className="font-semibold">Demo mode.</span>
        <span>{lead}</span>
        <span>
          {verb}{" "}
          {others.map((account, index) => (
            <Fragment key={account.id}>
              {index > 0 && " or "}
              <Link
                to={demoHref(account, user ? here : undefined)}
                className="font-medium underline underline-offset-2 hover:decoration-2"
              >
                {account.name}
              </Link>
            </Fragment>
          ))}
        </span>
      </p>
    </div>
  );
}

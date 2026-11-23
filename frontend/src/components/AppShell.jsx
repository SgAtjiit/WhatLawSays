import { useQuery } from "@tanstack/react-query";
import { ChevronDown, LogOut, Files } from "lucide-react";
import { Link, NavLink, Outlet, useNavigate } from "react-router";
import { cn } from "cn";

import { checkHealth } from "@/api/health";
import { needsVerification, useAuth } from "@/auth/AuthProvider";
import { DemoBar } from "@/components/Demo";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

const NAV = [
  { to: "/talk", label: "Talk it through" },
  { to: "/scenario", label: "Something happened" },
  { to: "/contracts", label: "Review a contract", end: true },
  { to: "/reviews", label: "My reviews" },
];

export function Wordmark({ className }) {
  return (
    <Link to="/" className={cn("group inline-flex items-center gap-2.5 font-semibold tracking-tight", className)}>
      <svg aria-hidden viewBox="0 0 32 32" className="size-7">
        <rect width="32" height="32" rx="6" className="fill-seal" />
        <path d="M9 10h14M9 16h14M9 22h8" className="stroke-marker" strokeWidth="2.5" strokeLinecap="round" />
      </svg>
      <span className="text-[1.0625rem]">WhatLawSays</span>
    </Link>
  );
}

function ServerStatus() {
  const { data: online, isPending } = useQuery({
    queryKey: ["health"],
    queryFn: checkHealth,
    refetchInterval: 30_000,
    retry: false,
  });
  if (isPending || online) return null;
  return (
    <p role="status" className="border-b border-critical/30 bg-critical-tint px-4 py-2 text-center text-xs text-critical">
      The WhatLawSays server isn't responding. Reviews and analyses won't work until it's back.
    </p>
  );
}

function AccountMenu() {
  const { user, signOut } = useAuth();
  const navigate = useNavigate();
  const name = user.displayName || user.email || "Your account";
  const initial = (user.displayName || user.email || "?").charAt(0).toUpperCase();

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" className="gap-2 px-2" aria-label={`Account: ${name}`}>
          {user.photoURL ? (
            <img src={user.photoURL} alt="" referrerPolicy="no-referrer" className="size-7 rounded-full" />
          ) : (
            <span aria-hidden className="grid size-7 place-items-center rounded-full bg-seal-tint text-xs font-semibold text-seal">
              {initial}
            </span>
          )}
          <ChevronDown aria-hidden className="size-4" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-64">
        <DropdownMenuLabel className="font-normal">
          {user.displayName && <p className="font-medium text-ink">{user.displayName}</p>}
          <p className="truncate text-xs text-graphite">{user.email}</p>
        </DropdownMenuLabel>
        <DropdownMenuSeparator />
        <DropdownMenuItem onSelect={() => navigate("/reviews")}>
          <Files aria-hidden /> My reviews
        </DropdownMenuItem>
        <DropdownMenuItem
          onSelect={async () => {
            // Leave the protected page first, or its guard sends you to sign-in.
            navigate("/", { replace: true });
            await signOut();
          }}
        >
          <LogOut aria-hidden /> Sign out
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

export function AppShell() {
  const { user: account, status } = useAuth();
  // An unconfirmed account can't use the tools yet, so it gets no navigation to them.
  const user = account && !needsVerification(account) ? account : null;

  return (
    <div className="flex min-h-dvh flex-col">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:fixed focus:top-2 focus:left-2 focus:z-50 focus:rounded-md focus:bg-sheet focus:px-3 focus:py-2"
      >
        Skip to content
      </a>
      <DemoBar />
      <header className="sticky top-0 z-30 border-b border-rule bg-paper">
        <div className="mx-auto flex h-[var(--header-h)] max-w-7xl items-center gap-6 px-4 sm:px-6">
          <Wordmark />
          {user && (
            <nav aria-label="Main" className="hidden items-center gap-1 lg:flex">
              {NAV.map((item) => (
                <NavLink
                  key={item.to}
                  to={item.to}
                  end={item.end}
                  className={({ isActive }) =>
                    cn(
                      "rounded-md px-3 py-2 text-[0.9375rem] whitespace-nowrap text-graphite transition-colors hover:text-ink",
                      isActive && "text-ink underline decoration-marker decoration-[3px] underline-offset-[10px]",
                    )
                  }
                >
                  {item.label}
                </NavLink>
              ))}
            </nav>
          )}
          <div className="ml-auto flex items-center gap-2">
            {status === "signedIn" && <AccountMenu />}
            {status === "signedOut" && (
              <Button asChild variant="outline" size="sm">
                <Link to="/sign-in">Sign in</Link>
              </Button>
            )}
          </div>
        </div>
        {user && (
          <nav aria-label="Main" className="flex gap-1 overflow-x-auto border-t border-rule px-2 lg:hidden">
            {NAV.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.end}
                className={({ isActive }) =>
                  cn(
                    "shrink-0 px-3 py-2.5 text-xs whitespace-nowrap text-graphite",
                    isActive && "font-medium text-ink shadow-[inset_0_-3px_0_var(--marker)]",
                  )
                }
              >
                {item.label}
              </NavLink>
            ))}
          </nav>
        )}
      </header>
      <ServerStatus />
      <main id="main" className="flex-1">
        <Outlet />
      </main>
      <footer className="border-t border-rule">
        <div className="mx-auto flex max-w-7xl flex-col gap-2 px-4 py-6 text-xs text-graphite sm:flex-row sm:justify-between sm:px-6">
          <p>Legal information grounded in Indian statute. Not legal advice.</p>
          <p>Have a lawyer review anything you are about to be bound by.</p>
        </div>
      </footer>
    </div>
  );
}

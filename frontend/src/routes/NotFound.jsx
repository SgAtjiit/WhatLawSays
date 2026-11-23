import { Link } from "react-router";

import { Button } from "@/components/ui/button";

export function NotFound({ title = "This page doesn't exist", children }) {
  return (
    <div className="mx-auto max-w-xl px-4 py-20 sm:px-6">
      <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
      <div className="mt-3 text-graphite">
        {children || "The link may be mistyped, or the page may have moved."}
      </div>
      <Button asChild className="mt-8">
        <Link to="/">Go to the start</Link>
      </Button>
    </div>
  );
}

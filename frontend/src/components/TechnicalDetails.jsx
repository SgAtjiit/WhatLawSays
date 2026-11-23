import { Check, Copy, Download } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";

/** The raw response, for anyone who wants to check the working. */
export function TechnicalDetails({ data, filename }) {
  const [copied, setCopied] = useState(false);
  const json = JSON.stringify(data, null, 2);

  return (
    <div>
      <p className="max-w-measure text-graphite">
        The full response from the analysis, exactly as the server returned it.
      </p>
      <div className="mt-4 flex flex-wrap gap-2">
        <Button
          variant="outline"
          size="sm"
          onClick={async () => {
            await navigator.clipboard.writeText(json);
            setCopied(true);
            setTimeout(() => setCopied(false), 1800);
          }}
        >
          {copied ? <Check aria-hidden /> : <Copy aria-hidden />}
          {copied ? "Copied" : "Copy JSON"}
        </Button>
        <Button
          variant="outline"
          size="sm"
          onClick={() => {
            const url = URL.createObjectURL(new Blob([json], { type: "application/json" }));
            const link = document.createElement("a");
            link.href = url;
            link.download = filename;
            link.click();
            setTimeout(() => URL.revokeObjectURL(url), 5000);
          }}
        >
          <Download aria-hidden /> Download
        </Button>
      </div>
      <pre className="mt-4 max-h-[32rem] overflow-auto rounded-md border border-rule bg-sheet-sunk p-4 font-mono text-xs leading-relaxed">
        {json}
      </pre>
    </div>
  );
}

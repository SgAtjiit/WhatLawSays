import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FileText, Upload, X } from "lucide-react";
import { useId, useRef, useState } from "react";
import { useNavigate } from "react-router";
import { cn } from "cn";

import { getSupportedOptions, reviewContract } from "@/api/endpoints";
import { ErrorState, Notice, Working } from "@/components/common";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { CONTRACT_TYPE_LABEL, formatBytes, sideOption, sidesFor } from "@/lib/legal";

const ACCEPT = ".pdf,.docx,.txt,.md,.png,.jpg,.jpeg,.tif,.tiff,.bmp,.webp";
const IMAGE = /\.(png|jpe?g|tiff?|bmp|webp)$/i;
const NOT_SURE = "__not_sure__";

const STEPS = [
  "Reading the document and splitting it into its clauses",
  "Checking every clause against known risky patterns",
  "Finding the statute sections that govern each risky clause",
  "Explaining the clauses in plain words, and listing protections that are missing",
];

function Dropzone({ file, onFile, maxBytes, ocrAvailable, error }) {
  const inputId = useId();
  const [dragging, setDragging] = useState(false);

  if (file) {
    return (
      <div className="flex items-center gap-4 rounded-md border border-rule-strong bg-sheet px-4 py-4">
        <FileText aria-hidden className="size-8 shrink-0 text-seal" strokeWidth={1.5} />
        <div className="min-w-0 flex-1">
          <p className="truncate font-medium">{file.name}</p>
          <p className="text-xs text-graphite">{formatBytes(file.size)}</p>
        </div>
        <Button variant="ghost" size="icon" aria-label="Remove this file" onClick={() => onFile(null)}>
          <X aria-hidden />
        </Button>
      </div>
    );
  }

  return (
    <div>
      <label
        htmlFor={inputId}
        onDragOver={(event) => {
          event.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(event) => {
          event.preventDefault();
          setDragging(false);
          onFile(event.dataTransfer.files?.[0] || null);
        }}
        className={cn(
          "flex cursor-pointer flex-col items-center justify-center gap-3 rounded-md border-2 border-dashed px-6 py-12 text-center transition-colors",
          dragging ? "border-seal bg-seal-tint" : "border-rule-strong bg-sheet hover:border-seal",
          error && "border-critical",
        )}
      >
        <Upload aria-hidden className="size-7 text-seal" strokeWidth={1.5} />
        <span className="font-medium">
          Drop your contract here, or <span className="text-seal underline underline-offset-4">choose a file</span>
        </span>
        <span className="text-xs text-graphite">
          PDF, Word or text{ocrAvailable ? ", or a scan or photo" : ""}. Up to {formatBytes(maxBytes)}.
        </span>
      </label>
      <input
        id={inputId}
        type="file"
        accept={ACCEPT}
        className="sr-only"
        onChange={(event) => onFile(event.target.files?.[0] || null)}
      />
    </div>
  );
}

export default function ContractUpload() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const controller = useRef(null);
  const [file, setFile] = useState(null);
  const [fileError, setFileError] = useState(null);
  const [contractType, setContractType] = useState(NOT_SURE);
  const [position, setPosition] = useState("");

  const options = useQuery({ queryKey: ["supported"], queryFn: getSupportedOptions, staleTime: Infinity });
  const maxBytes = options.data?.max_file_bytes ?? 20 * 1_048_576;
  const ocrAvailable = options.data?.ocr_available ?? false;
  const types = (options.data?.contract_types || Object.keys(CONTRACT_TYPE_LABEL)).filter(
    (type) => type !== "UNKNOWN" && type !== "OTHER",
  );
  const sides = contractType === NOT_SURE ? [] : sidesFor(contractType, options.data?.positions_by_type);

  const review = useMutation({
    mutationFn: reviewContract,
    onSuccess: (result) => {
      queryClient.setQueryData(["contract", result.contract_id], result);
      queryClient.invalidateQueries({ queryKey: ["contracts"] });
      navigate(`/contracts/${result.contract_id}`);
    },
  });

  function chooseFile(next) {
    setFileError(null);
    if (next && next.size > maxBytes) {
      setFileError(`That file is ${formatBytes(next.size)}. The limit is ${formatBytes(maxBytes)}.`);
      return;
    }
    if (next && IMAGE.test(next.name) && options.data && !ocrAvailable) {
      setFileError("Scans and photos can't be read on this server because OCR isn't installed. Upload a PDF, Word or text file.");
      return;
    }
    setFile(next);
  }

  function chooseType(next) {
    setContractType(next);
    // The side always follows the type: a side from another kind of contract
    // is a mistake the server would reject.
    setPosition(next === NOT_SURE ? "" : sidesFor(next, options.data?.positions_by_type)[0] || "");
  }

  function submit(event) {
    event.preventDefault();
    if (!file) {
      setFileError("Choose a contract to review.");
      return;
    }
    controller.current = new AbortController();
    review.mutate({
      file,
      contractType: contractType === NOT_SURE ? null : contractType,
      position: position || null,
      signal: controller.current.signal,
    });
  }

  if (review.isPending) {
    return (
      <div className="mx-auto max-w-3xl px-4 py-10 sm:px-6 sm:py-14">
        <Working
          title={`Reviewing ${file.name}`}
          steps={STEPS}
          note="A long contract can take a couple of minutes. You can leave this tab open and come back."
          onCancel={() => controller.current?.abort()}
        />
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-3xl px-4 py-10 sm:px-6 sm:py-14">
      <h1 className="text-3xl font-semibold tracking-tight">Review a contract before you sign</h1>
      <p className="mt-3 max-w-measure text-xl text-graphite">
        Every risky term is quoted from your document, with the section of Indian law that governs it and what to
        ask for instead.
      </p>

      <form onSubmit={submit} className="mt-10 space-y-8" noValidate>
        <div>
          <Dropzone file={file} onFile={chooseFile} maxBytes={maxBytes} ocrAvailable={ocrAvailable} error={fileError} />
          {fileError && (
            <p role="alert" className="mt-2 text-xs text-critical">
              {fileError}
            </p>
          )}
          {file && IMAGE.test(file.name) && (
            <Notice className="mt-4" title="This will be read from an image">
              Characters can be misread, especially digits in amounts. Every finding will show the part of the page
              it was read from, so you can check it against your copy.
            </Notice>
          )}
        </div>

        <div className="grid gap-6 sm:grid-cols-2">
          <div className="space-y-2">
            <Label htmlFor="contract-type" className="text-[0.9375rem] font-medium">
              What kind of contract is it?
            </Label>
            <Select value={contractType} onValueChange={chooseType}>
              <SelectTrigger id="contract-type" className="h-11 w-full bg-sheet text-base">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={NOT_SURE}>I'm not sure</SelectItem>
                {types.map((type) => (
                  <SelectItem key={type} value={type}>
                    {CONTRACT_TYPE_LABEL[type] || type}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {sides.length > 0 && (
            <div className="space-y-2">
              <Label htmlFor="position" className="text-[0.9375rem] font-medium">
                Which side are you on?
              </Label>
              <Select value={position} onValueChange={setPosition}>
                <SelectTrigger id="position" className="h-11 w-full bg-sheet text-base">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {sides.map((side) => (
                    <SelectItem key={side} value={side}>
                      {sideOption(side)}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          )}
        </div>
        <p className="-mt-4 max-w-measure text-xs text-graphite">
          {sides.length > 0
            ? "This changes the result. An uncapped indemnity is serious for the side giving it and routine for the side receiving it."
            : "Choosing the type and your side gives a sharper review. Without them, severities aren't weighted for you."}
        </p>

        {review.isError && review.error.kind !== "aborted" && <ErrorState error={review.error} />}

        <div className="flex flex-wrap items-center gap-4">
          <Button type="submit" size="lg">
            Review contract
          </Button>
          <p className="text-xs text-graphite">Only you can open the review. You can delete it at any time.</p>
        </div>
      </form>
    </div>
  );
}

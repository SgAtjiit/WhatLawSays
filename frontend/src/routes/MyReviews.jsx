import { useInfiniteQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Download, Loader2, Trash2 } from "lucide-react";
import { Link } from "react-router";
import { toast } from "sonner";

import { deleteContract, downloadReport, listContracts } from "@/api/endpoints";
import { EmptyState, ErrorState, SeverityTag } from "@/components/common";
import { Splash } from "@/components/Splash";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import { CONTRACT_TYPE_LABEL, POSITION_LABEL, formatDate } from "@/lib/legal";

const PAGE = 20;
const FINISHED = new Set(["SUCCESS", "PARTIAL_SUCCESS", "NEEDS_CLARIFICATION"]);

function StatusText({ item }) {
  if (item.status === "FAILED") return <span className="text-xs text-critical">Couldn't be reviewed</span>;
  if (!FINISHED.has(item.status)) return <span className="text-xs text-graphite">Still reviewing</span>;
  if (item.overall_risk && item.overall_risk !== "UNKNOWN") return <SeverityTag severity={item.overall_risk} />;
  return <span className="text-xs text-graphite">No risk rating</span>;
}

function Row({ item }) {
  const queryClient = useQueryClient();
  const download = useMutation({
    mutationFn: () => downloadReport(item.contract_id),
    onError: (error) => toast.error(error.message),
  });
  const remove = useMutation({
    mutationFn: () => deleteContract(item.contract_id),
    onSuccess: () => {
      queryClient.removeQueries({ queryKey: ["contract", item.contract_id] });
      queryClient.invalidateQueries({ queryKey: ["contracts"] });
      toast.success(`Deleted ${item.filename}.`);
    },
    onError: (error) => toast.error(error.message),
  });
  const finished = FINISHED.has(item.status);
  const side = item.position && item.position !== "UNKNOWN" ? `as ${POSITION_LABEL[item.position]}` : null;

  return (
    <li className="grid gap-3 py-5 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-center sm:gap-6">
      <div className="min-w-0">
        <Link
          to={`/contracts/${item.contract_id}`}
          className="block truncate text-xl font-medium hover:text-seal-strong hover:underline hover:underline-offset-4"
        >
          {item.filename}
        </Link>
        <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-graphite">
          <StatusText item={item} />
          <span>
            {CONTRACT_TYPE_LABEL[item.contract_type] || "Contract"}
            {side && `, ${side}`}
          </span>
          {item.created_at && <time dateTime={item.created_at}>{formatDate(item.created_at)}</time>}
        </div>
      </div>
      <div className="flex gap-1 sm:justify-end">
        {finished && (
          <Button variant="ghost" size="sm" onClick={() => download.mutate()} disabled={download.isPending}>
            {download.isPending ? <Loader2 aria-hidden className="animate-spin" /> : <Download aria-hidden />}
            PDF
          </Button>
        )}
        <AlertDialog>
          <AlertDialogTrigger asChild>
            <Button variant="ghost" size="sm" aria-label={`Delete ${item.filename}`} disabled={remove.isPending}>
              <Trash2 aria-hidden /> Delete
            </Button>
          </AlertDialogTrigger>
          <AlertDialogContent>
            <AlertDialogHeader>
              <AlertDialogTitle>Delete {item.filename}?</AlertDialogTitle>
              <AlertDialogDescription>
                The uploaded text and its review are removed for good. This can't be undone.
              </AlertDialogDescription>
            </AlertDialogHeader>
            <AlertDialogFooter>
              <AlertDialogCancel>Keep it</AlertDialogCancel>
              <AlertDialogAction className="bg-critical hover:bg-critical/90" onClick={() => remove.mutate()}>
                Delete
              </AlertDialogAction>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialog>
      </div>
    </li>
  );
}

export default function MyReviews() {
  const query = useInfiniteQuery({
    queryKey: ["contracts"],
    queryFn: ({ pageParam, signal }) => listContracts({ limit: PAGE, offset: pageParam, signal }),
    initialPageParam: 0,
    getNextPageParam: (last, pages) => (last.has_more ? pages.length * PAGE : undefined),
  });

  const items = query.data?.pages.flatMap((page) => page.items) ?? [];

  return (
    <div className="mx-auto max-w-4xl px-4 py-10 sm:px-6 sm:py-14">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-3xl font-semibold tracking-tight">My reviews</h1>
          <p className="mt-2 text-graphite">Only you can see these. Delete any of them whenever you like.</p>
        </div>
        <Button asChild>
          <Link to="/contracts">Review a contract</Link>
        </Button>
      </div>

      <div className="mt-10">
        {query.isPending && <Splash />}
        {query.isError && <ErrorState error={query.error} onRetry={() => query.refetch()} />}
        {query.isSuccess && items.length === 0 && (
          <EmptyState
            title="No reviews yet"
            action={
              <Button asChild>
                <Link to="/contracts">Review your first contract</Link>
              </Button>
            }
          >
            Upload a contract and its review will be kept here, private to your account.
          </EmptyState>
        )}
        {items.length > 0 && (
          <ul className="divide-y divide-rule border-y border-rule">
            {items.map((item) => (
              <Row key={item.contract_id} item={item} />
            ))}
          </ul>
        )}
        {query.hasNextPage && (
          <Button variant="outline" className="mt-6" onClick={() => query.fetchNextPage()} disabled={query.isFetchingNextPage}>
            {query.isFetchingNextPage && <Loader2 aria-hidden className="animate-spin" />}
            Show more
          </Button>
        )}
      </div>
    </div>
  );
}

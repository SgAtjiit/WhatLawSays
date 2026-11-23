import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { MoreHorizontal, Pencil, Plus, Trash2 } from "lucide-react";
import { cn } from "cn";
import { useState } from "react";
import { Link, useNavigate } from "react-router";
import { toast } from "sonner";

import { deleteConversation, listConversations, renameConversation } from "@/api/endpoints";
import { Button } from "@/components/ui/button";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { formatDate } from "@/lib/legal";

export const UNTITLED = "New conversation";

function RenameDialog({ target, onClose }) {
  const queryClient = useQueryClient();
  const rename = useMutation({
    mutationFn: (title) => renameConversation(target.conversation_id, title),
    onSuccess: (updated) => {
      queryClient.invalidateQueries({ queryKey: ["conversations"] });
      queryClient.setQueryData(["conversation", updated.conversation_id], (old) => old && { ...old, title: updated.title });
      onClose();
    },
  });
  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Rename conversation</DialogTitle>
          <DialogDescription>Only you can see this name.</DialogDescription>
        </DialogHeader>
        <form
          onSubmit={(event) => {
            event.preventDefault();
            const title = String(new FormData(event.currentTarget).get("title")).trim();
            if (title) rename.mutate(title);
          }}
        >
          <label htmlFor="conversation-title" className="sr-only">
            Name
          </label>
          <Input
            id="conversation-title"
            name="title"
            defaultValue={target.title || ""}
            maxLength={200}
            autoFocus
            required
            className="h-11 bg-sheet text-base"
          />
          {rename.isError && <p className="mt-2 text-xs text-critical">{rename.error.message}</p>}
          <DialogFooter className="mt-5">
            <Button type="button" variant="outline" onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit" disabled={rename.isPending}>
              Save
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function DeleteDialog({ target, activeId, onClose }) {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const remove = useMutation({
    mutationFn: () => deleteConversation(target.conversation_id),
    onSuccess: () => {
      queryClient.removeQueries({ queryKey: ["conversation", target.conversation_id] });
      queryClient.invalidateQueries({ queryKey: ["conversations"] });
      if (activeId === target.conversation_id) navigate("/talk", { replace: true });
      toast.success("Conversation deleted.");
      onClose();
    },
  });
  return (
    <AlertDialog open onOpenChange={(open) => !open && onClose()}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>Delete this conversation?</AlertDialogTitle>
          <AlertDialogDescription>
            “{target.title || UNTITLED}” and everything in it will be removed for good.
          </AlertDialogDescription>
        </AlertDialogHeader>
        {remove.isError && <p className="text-xs text-critical">{remove.error.message}</p>}
        <AlertDialogFooter>
          <AlertDialogCancel>Keep it</AlertDialogCancel>
          <AlertDialogAction
            className="bg-critical text-white hover:bg-critical/90"
            onClick={(event) => {
              event.preventDefault();
              remove.mutate();
            }}
            disabled={remove.isPending}
          >
            Delete
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}

/** The person's saved conversations, most recently active first. */
export function ConversationList({ activeId, onNavigate }) {
  const [renaming, setRenaming] = useState(null);
  const [deleting, setDeleting] = useState(null);
  const list = useQuery({ queryKey: ["conversations"], queryFn: ({ signal }) => listConversations({ limit: 50, signal }) });
  const items = list.data?.items ?? [];

  return (
    <nav aria-label="Your conversations" className="flex flex-col gap-4">
      <Button asChild variant="outline" className="justify-start">
        <Link to="/talk" onClick={onNavigate}>
          <Plus aria-hidden /> New conversation
        </Link>
      </Button>

      {list.isPending && <p className="px-2 text-xs text-graphite">Loading…</p>}
      {list.isError && <p className="px-2 text-xs text-critical">Couldn't load your conversations. {list.error.message}</p>}
      {list.isSuccess && items.length === 0 && (
        <p className="px-2 text-xs text-graphite">Your conversations are saved here, and only you can see them.</p>
      )}

      {items.length > 0 && (
        <ul className="space-y-0.5">
          {items.map((item) => {
            const active = item.conversation_id === activeId;
            return (
              <li key={item.conversation_id} className="group relative">
                <Link
                  to={`/talk/${item.conversation_id}`}
                  onClick={onNavigate}
                  aria-current={active ? "page" : undefined}
                  className={cn(
                    "block rounded-md py-2 pr-9 pl-2.5 transition-colors hover:bg-seal-tint",
                    active && "bg-seal-tint",
                  )}
                >
                  <span className={cn("block truncate text-[0.9375rem]", active ? "font-medium text-ink" : "text-ink")}>
                    {item.title || UNTITLED}
                  </span>
                  <span className="block text-xs text-graphite">{formatDate(item.updated_at)}</span>
                </Link>
                <DropdownMenu>
                  <DropdownMenuTrigger asChild>
                    <Button
                      variant="ghost"
                      size="icon"
                      aria-label={`Options for ${item.title || UNTITLED}`}
                      className="absolute top-1.5 right-1 size-8"
                    >
                      <MoreHorizontal aria-hidden />
                    </Button>
                  </DropdownMenuTrigger>
                  <DropdownMenuContent align="end">
                    <DropdownMenuItem onSelect={() => setRenaming(item)}>
                      <Pencil aria-hidden /> Rename
                    </DropdownMenuItem>
                    <DropdownMenuItem onSelect={() => setDeleting(item)} className="text-critical focus:text-critical">
                      <Trash2 aria-hidden className="text-critical" /> Delete
                    </DropdownMenuItem>
                  </DropdownMenuContent>
                </DropdownMenu>
              </li>
            );
          })}
        </ul>
      )}

      {renaming && <RenameDialog target={renaming} onClose={() => setRenaming(null)} />}
      {deleting && <DeleteDialog target={deleting} activeId={activeId} onClose={() => setDeleting(null)} />}
    </nav>
  );
}

import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { KeyRound, Loader2 } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { apiPost } from "@/lib/api";
import { errorText } from "@/hooks/useAuth";

/** Self-service password change for the signed-in account. */
export default function ChangePasswordDialog({ compact = false }: { compact?: boolean }) {
  const [open, setOpen] = useState(false);
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");

  const change = useMutation({
    mutationFn: (body: { current_password: string; new_password: string }) =>
      apiPost<{ message: string }>("/auth/password", body),
    onSuccess: (res) => {
      toast.success(res.message);
      setOpen(false);
      setCurrent("");
      setNext("");
      setConfirm("");
    },
    onError: (e) => toast.error(errorText(e, "Could not update the password.")),
  });

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    if (next !== confirm) {
      toast.error("The two new passwords do not match.");
      return;
    }
    change.mutate({ current_password: current, new_password: next });
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <Button
        variant="outline"
        size="sm"
        onClick={() => setOpen(true)}
        data-testid="change-password-open-button"
        className="border-slate-700 text-slate-300 transition-colors duration-150 hover:text-amber-300"
      >
        <KeyRound className="size-3.5" />
        {compact ? null : "Password"}
      </Button>
      <DialogContent
        className="border-slate-800 bg-[#111827] text-slate-100 sm:max-w-md"
        data-testid="change-password-dialog"
      >
        <DialogHeader>
          <DialogTitle className="text-sm">Update your password</DialogTitle>
          <DialogDescription className="text-[11px] text-slate-500">
            Your other devices are signed out once the password changes. This device stays signed in.
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={submit} className="space-y-3" data-testid="change-password-form">
          <div>
            <Label className="text-[11px] text-slate-300">Current password</Label>
            <Input
              type="password"
              required
              autoComplete="current-password"
              value={current}
              onChange={(e) => setCurrent(e.target.value)}
              data-testid="current-password-input"
              className="mt-1 border-slate-700 bg-slate-950 text-slate-100"
            />
          </div>
          <div>
            <Label className="text-[11px] text-slate-300">New password</Label>
            <Input
              type="password"
              required
              minLength={8}
              autoComplete="new-password"
              value={next}
              onChange={(e) => setNext(e.target.value)}
              placeholder="At least 8 characters"
              data-testid="new-password-input"
              className="mt-1 border-slate-700 bg-slate-950 text-slate-100"
            />
          </div>
          <div>
            <Label className="text-[11px] text-slate-300">Confirm new password</Label>
            <Input
              type="password"
              required
              minLength={8}
              autoComplete="new-password"
              value={confirm}
              onChange={(e) => setConfirm(e.target.value)}
              data-testid="confirm-password-input"
              className="mt-1 border-slate-700 bg-slate-950 text-slate-100"
            />
          </div>
          <DialogFooter>
            <Button type="submit" size="sm" disabled={change.isPending} data-testid="change-password-submit-button">
              {change.isPending ? <Loader2 className="size-3.5 animate-spin" /> : null}
              Save password
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

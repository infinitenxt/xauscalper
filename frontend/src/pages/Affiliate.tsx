import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Check, Copy, Landmark, Loader2, WalletCards } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Toaster } from "@/components/ui/sonner";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { apiGet, apiPost, apiPut } from "@/lib/api";
import { errorText, useMe } from "@/hooks/useAuth";
import { rupees } from "@/lib/types";
import type { AffiliateEarning, AffiliateSummary, BankDetailsPublic, WithdrawalRow } from "@/lib/types";
import { cn } from "@/lib/utils";

export default function Affiliate() {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const { data: me } = useMe();
  const summary = useQuery({ queryKey: ["affiliate", "summary"], queryFn: () => apiGet<AffiliateSummary>("/affiliate/summary") });
  const earnings = useQuery({ queryKey: ["affiliate", "earnings"], queryFn: () => apiGet<AffiliateEarning[]>("/affiliate/earnings") });
  const withdrawals = useQuery({ queryKey: ["affiliate", "withdrawals"], queryFn: () => apiGet<WithdrawalRow[]>("/affiliate/withdrawals") });
  const [bank, setBank] = useState({ account_holder: "", bank_name: "", account_number: "", ifsc_code: "" });
  const [amount, setAmount] = useState("");

  useEffect(() => {
    if (!summary.data?.bank.configured) return;
    setBank((value) => ({
      ...value,
      account_holder: summary.data?.bank.account_holder ?? "",
      bank_name: summary.data?.bank.bank_name ?? "",
      ifsc_code: summary.data?.bank.ifsc_code ?? "",
    }));
  }, [summary.data]);

  const refresh = () => void qc.invalidateQueries({ queryKey: ["affiliate"] });
  const saveBank = useMutation({
    mutationFn: () => apiPut<BankDetailsPublic>("/affiliate/bank", {
      account_holder: bank.account_holder,
      bank_name: bank.bank_name,
      ifsc_code: bank.ifsc_code,
      ...(bank.account_number ? { account_number: bank.account_number } : {}),
    }),
    onSuccess: () => { toast.success("Bank details saved"); setBank((v) => ({ ...v, account_number: "" })); refresh(); },
    onError: (err) => toast.error(errorText(err)),
  });
  const requestWithdrawal = useMutation({
    mutationFn: () => apiPost<WithdrawalRow>("/affiliate/withdrawals", { amount_inr: Number(amount) }),
    onSuccess: () => { toast.success("Withdrawal request submitted"); setAmount(""); refresh(); },
    onError: (err) => toast.error(errorText(err)),
  });

  const data = summary.data;
  const referralUrl = data ? `${window.location.origin}${data.referral_path}` : "";

  return (
    <div className="min-h-screen bg-[#0b0e14] p-4">
      <Toaster position="bottom-right" richColors />
      <div className="mx-auto max-w-6xl space-y-4">
        <header className="flex flex-wrap items-center justify-between gap-3 rounded-md border border-slate-800 bg-[#111827] p-4">
          <div>
            <h1 className="text-lg font-semibold text-slate-100" data-testid="affiliate-page-title">Affiliate wallet</h1>
            <p className="text-[11px] text-slate-500" data-testid="affiliate-user-email">
              {me?.email} · earn {data?.commission_pct ?? 20}% on every referred purchase and renewal
            </p>
          </div>
          <Button variant="outline" size="sm" onClick={() => navigate(me?.subscribed ? "/" : "/subscribe")} data-testid="affiliate-back-button" className="border-slate-700 text-slate-300">
            <ArrowLeft className="size-3.5" /> Back
          </Button>
        </header>

        <section className="rounded-md border border-emerald-900/50 bg-emerald-950/15 p-4" data-testid="referral-link-panel">
          <p className="text-[10px] uppercase tracking-wider text-emerald-400">Your permanent referral link</p>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <code className="min-w-0 flex-1 truncate rounded bg-slate-950 px-3 py-2 text-[12px] text-slate-200" data-testid="referral-link">{referralUrl || "Loading…"}</code>
            <Button size="sm" disabled={!referralUrl} onClick={() => { void navigator.clipboard.writeText(referralUrl); toast.success("Referral link copied"); }} data-testid="copy-referral-link-button">
              <Copy className="size-3.5" /> Copy
            </Button>
          </div>
          <p className="mt-2 text-[11px] text-slate-500">Code <span className="font-semibold text-emerald-300" data-testid="referral-code">{data?.referral_code ?? "—"}</span> is linked permanently when a new user registers.</p>
        </section>

        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-6" data-testid="affiliate-stats">
          {[
            ["Referred users", String(data?.referred_users ?? 0)],
            ["Paying referrals", String(data?.paid_referrals ?? 0)],
            ["Total earned", rupees(data?.earned_total)],
            ["Available", rupees(data?.available_balance)],
            ["Pending", rupees(data?.pending_withdrawal)],
            ["Paid out", rupees(data?.withdrawn_total)],
          ].map(([label, value]) => (
            <div key={label} className="rounded border border-slate-800 bg-[#111827] p-3">
              <p className="text-[10px] uppercase tracking-wider text-slate-500">{label}</p>
              <p className="mt-1 text-lg font-semibold tabular-nums text-amber-300" data-testid={`affiliate-stat-${label.toLowerCase().replace(/\s+/g, "-")}`}>{value}</p>
            </div>
          ))}
        </div>

        <div className="grid gap-4 lg:grid-cols-2">
          <section className="rounded-md border border-slate-800 bg-[#111827] p-4" data-testid="bank-details-panel">
            <h2 className="flex items-center gap-2 text-sm font-semibold text-slate-100"><Landmark className="size-4 text-amber-400" /> Withdrawal bank details</h2>
            <div className="mt-3 grid gap-3 sm:grid-cols-2">
              {([
                ["account_holder", "Account holder", "Name on account"],
                ["bank_name", "Bank name", "Your bank"],
                ["account_number", "Account number", data?.bank.configured ? `Saved ••••${data.bank.account_last4}; leave blank to keep` : "Account number"],
                ["ifsc_code", "IFSC code", "ABCD0123456"],
              ] as const).map(([key, label, placeholder]) => (
                <div key={key}>
                  <Label htmlFor={`bank-${key}`} className="text-[11px] text-slate-300">{label}</Label>
                  <Input id={`bank-${key}`} value={bank[key]} onChange={(e) => setBank((v) => ({ ...v, [key]: e.target.value }))} placeholder={placeholder} data-testid={`bank-${key.replace(/_/g, "-")}-input`} className="mt-1 border-slate-700 bg-slate-950 text-slate-100" />
                </div>
              ))}
            </div>
            <Button className="mt-3" size="sm" onClick={() => saveBank.mutate()} disabled={saveBank.isPending} data-testid="save-bank-details-button">
              {saveBank.isPending ? <Loader2 className="size-3.5 animate-spin" /> : <Check className="size-3.5" />} Save bank details
            </Button>
          </section>

          <section className="rounded-md border border-slate-800 bg-[#111827] p-4" data-testid="withdrawal-request-panel">
            <h2 className="flex items-center gap-2 text-sm font-semibold text-slate-100"><WalletCards className="size-4 text-emerald-400" /> Request withdrawal</h2>
            <p className="mt-1 text-[11px] text-slate-500">Available now: {rupees(data?.available_balance)}. Admin approval is required before payment.</p>
            <div className="mt-3 flex items-end gap-2">
              <div className="flex-1">
                <Label htmlFor="withdrawal-amount" className="text-[11px] text-slate-300">Amount (INR)</Label>
                <Input id="withdrawal-amount" type="number" min="1" max={data?.available_balance ?? 0} value={amount} onChange={(e) => setAmount(e.target.value)} data-testid="withdrawal-amount-input" className="mt-1 border-slate-700 bg-slate-950 text-slate-100" />
              </div>
              <Button size="sm" disabled={!amount || Number(amount) <= 0 || requestWithdrawal.isPending} onClick={() => requestWithdrawal.mutate()} data-testid="request-withdrawal-button">Request</Button>
            </div>
            {!data?.bank.configured ? <p className="mt-2 text-[10px] text-amber-300" data-testid="bank-required-message">Save complete bank details before requesting a withdrawal.</p> : null}
          </section>
        </div>

        <section className="rounded-md border border-slate-800 bg-[#111827] p-4" data-testid="affiliate-earnings-panel">
          <h2 className="mb-3 text-sm font-semibold text-slate-100">Commission history</h2>
          {(earnings.data ?? []).length ? (
            <Table><TableHeader><TableRow className="border-slate-800 hover:bg-transparent">{["Referred user", "Plan", "Purchase", "Rate", "Commission", "Date"].map((h) => <TableHead key={h} className="h-8 text-[10px] uppercase tracking-wider text-slate-500">{h}</TableHead>)}</TableRow></TableHeader>
              <TableBody>{(earnings.data ?? []).map((row) => <TableRow key={row.id} className="border-slate-800 text-[11px]" data-testid="affiliate-earning-row"><TableCell>{row.referred_user_email}</TableCell><TableCell>{row.plan_name}</TableCell><TableCell>{rupees(row.purchase_amount_inr)}</TableCell><TableCell>{row.commission_pct}%</TableCell><TableCell className="text-emerald-300">{rupees(row.commission_inr)}</TableCell><TableCell>{row.created_at ? new Date(row.created_at).toLocaleDateString() : "—"}</TableCell></TableRow>)}</TableBody>
            </Table>
          ) : <p className="text-[11px] text-slate-500" data-testid="affiliate-earnings-empty">No paid referrals yet. Share your link to start earning.</p>}
        </section>

        <section className="rounded-md border border-slate-800 bg-[#111827] p-4" data-testid="affiliate-withdrawals-panel">
          <h2 className="mb-3 text-sm font-semibold text-slate-100">Withdrawal history</h2>
          {(withdrawals.data ?? []).length ? <div className="space-y-2">{(withdrawals.data ?? []).map((row) => <div key={row.id} className="flex items-center justify-between rounded border border-slate-800 bg-slate-950/40 p-2 text-[11px]" data-testid="withdrawal-row"><span>{rupees(row.amount_inr)} · {row.created_at ? new Date(row.created_at).toLocaleDateString() : "—"}</span><span className={cn("rounded px-2 py-0.5 font-semibold", row.status === "paid" ? "bg-emerald-950 text-emerald-300" : row.status === "rejected" ? "bg-rose-950 text-rose-300" : "bg-amber-950 text-amber-300")}>{row.status}</span></div>)}</div> : <p className="text-[11px] text-slate-500" data-testid="withdrawals-empty">No withdrawal requests yet.</p>}
        </section>
      </div>
    </div>
  );
}
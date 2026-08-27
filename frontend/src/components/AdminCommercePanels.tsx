import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BadgePercent, HandCoins, Loader2, Plus, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { apiDelete, apiGet, apiPatch, apiPost, apiPut } from "@/lib/api";
import { errorText } from "@/hooks/useAuth";
import { rupees } from "@/lib/types";
import type { AffiliateEarning, Coupon, Plan, SiteSettings, WithdrawalRow } from "@/lib/types";
import { cn } from "@/lib/utils";

function futureDate(days: number): string {
  const date = new Date();
  date.setDate(date.getDate() + days);
  return date.toISOString().slice(0, 10);
}

export function CouponsPanel({ plans }: { plans: Plan[] }) {
  const qc = useQueryClient();
  const coupons = useQuery({ queryKey: ["admin", "coupons"], queryFn: () => apiGet<Coupon[]>("/admin/coupons") });
  const [form, setForm] = useState({ code: "", discount_pct: 20, claim_limit: 100, expires_at: futureDate(30), eligible_plan_ids: [] as string[] });
  const refresh = () => void qc.invalidateQueries({ queryKey: ["admin", "coupons"] });
  const create = useMutation({
    mutationFn: () => apiPost<Coupon>("/admin/coupons", { ...form, code: form.code.trim().toUpperCase(), expires_at: new Date(`${form.expires_at}T23:59:59`).toISOString(), active: true }),
    onSuccess: () => { toast.success("Coupon created"); setForm((v) => ({ ...v, code: "" })); refresh(); },
    onError: (err) => toast.error(errorText(err)),
  });
  const patch = useMutation({
    mutationFn: ({ id, body }: { id: string; body: Partial<Coupon> }) => apiPatch<Coupon>(`/admin/coupons/${id}`, body),
    onSuccess: () => { toast.success("Coupon updated"); refresh(); },
    onError: (err) => toast.error(errorText(err)),
  });
  const remove = useMutation({
    mutationFn: (id: string) => apiDelete<{ message: string }>(`/admin/coupons/${id}`),
    onSuccess: (res) => { toast.success(res.message); refresh(); },
    onError: (err) => toast.error(errorText(err)),
  });
  const togglePlan = (planId: string) => setForm((value) => ({
    ...value,
    eligible_plan_ids: value.eligible_plan_ids.includes(planId)
      ? value.eligible_plan_ids.filter((id) => id !== planId)
      : [...value.eligible_plan_ids, planId],
  }));

  return (
    <div className="space-y-4" data-testid="coupons-panel">
      <form className="rounded border border-slate-800 bg-slate-950/40 p-3" onSubmit={(e) => { e.preventDefault(); create.mutate(); }} data-testid="coupon-create-form">
        <div className="grid gap-3 md:grid-cols-4">
          <div><Label htmlFor="admin-coupon-code" className="text-[11px] text-slate-300">Code</Label><Input id="admin-coupon-code" required value={form.code} onChange={(e) => setForm((v) => ({ ...v, code: e.target.value.toUpperCase() }))} placeholder="SAVE20" data-testid="admin-coupon-code-input" className="mt-1 border-slate-700 bg-slate-950 text-slate-100 uppercase" /></div>
          <div><Label htmlFor="admin-coupon-discount" className="text-[11px] text-slate-300">Discount %</Label><Input id="admin-coupon-discount" type="number" min="1" max="99" required value={form.discount_pct} onChange={(e) => setForm((v) => ({ ...v, discount_pct: Number(e.target.value) }))} data-testid="admin-coupon-discount-input" className="mt-1 border-slate-700 bg-slate-950 text-slate-100" /></div>
          <div><Label htmlFor="admin-coupon-limit" className="text-[11px] text-slate-300">Total claim limit</Label><Input id="admin-coupon-limit" type="number" min="1" required value={form.claim_limit} onChange={(e) => setForm((v) => ({ ...v, claim_limit: Number(e.target.value) }))} data-testid="admin-coupon-limit-input" className="mt-1 border-slate-700 bg-slate-950 text-slate-100" /></div>
          <div><Label htmlFor="admin-coupon-expiry" className="text-[11px] text-slate-300">Expires</Label><Input id="admin-coupon-expiry" type="date" required value={form.expires_at} onChange={(e) => setForm((v) => ({ ...v, expires_at: e.target.value }))} data-testid="admin-coupon-expiry-input" className="mt-1 border-slate-700 bg-slate-950 text-slate-100" /></div>
        </div>
        <div className="mt-3 flex flex-wrap items-center gap-4">
          <span className="text-[11px] text-slate-400">Eligible plans (none selected = all):</span>
          {plans.map((plan) => <label key={plan.id} className="flex items-center gap-1.5 text-[11px] text-slate-300"><Checkbox checked={form.eligible_plan_ids.includes(plan.id)} onCheckedChange={() => togglePlan(plan.id)} data-testid={`coupon-plan-${plan.id}-checkbox`} />{plan.name}</label>)}
          <Button type="submit" size="sm" disabled={create.isPending} data-testid="create-coupon-button"><Plus className="size-3.5" /> Create coupon</Button>
        </div>
      </form>

      {(coupons.data ?? []).length ? <div className="grid gap-3 lg:grid-cols-2">{(coupons.data ?? []).map((coupon) => (
        <div key={coupon.id} className="rounded border border-slate-800 bg-slate-950/30 p-3" data-testid="coupon-row">
          <div className="flex items-start justify-between gap-2"><div><p className="flex items-center gap-1.5 font-semibold text-amber-300"><BadgePercent className="size-4" />{coupon.code}</p><p className="text-[10px] text-slate-500">{coupon.claims_used} used · {coupon.claims_reserved} reserved · limit {coupon.claim_limit}</p></div><label className="flex items-center gap-1.5 text-[11px] text-slate-300"><Checkbox checked={coupon.active} onCheckedChange={(value) => patch.mutate({ id: coupon.id, body: { active: Boolean(value) } })} data-testid="coupon-active-checkbox" />Active</label></div>
          <div className="mt-3 grid grid-cols-3 gap-2">
            <div><Label className="text-[10px] text-slate-500">Discount %</Label><Input type="number" defaultValue={coupon.discount_pct} min="1" max="99" onBlur={(e) => { const value = Number(e.target.value); if (value !== coupon.discount_pct) patch.mutate({ id: coupon.id, body: { discount_pct: value } }); }} data-testid="coupon-edit-discount-input" className="mt-1 h-8 border-slate-700 bg-slate-950 text-slate-100" /></div>
            <div><Label className="text-[10px] text-slate-500">Claim limit</Label><Input type="number" defaultValue={coupon.claim_limit} min={coupon.claims_used + coupon.claims_reserved} onBlur={(e) => { const value = Number(e.target.value); if (value !== coupon.claim_limit) patch.mutate({ id: coupon.id, body: { claim_limit: value } }); }} data-testid="coupon-edit-limit-input" className="mt-1 h-8 border-slate-700 bg-slate-950 text-slate-100" /></div>
            <div><Label className="text-[10px] text-slate-500">Expires</Label><Input type="date" defaultValue={coupon.expires_at.slice(0, 10)} onBlur={(e) => patch.mutate({ id: coupon.id, body: { expires_at: new Date(`${e.target.value}T23:59:59`).toISOString() as unknown as string } })} data-testid="coupon-edit-expiry-input" className="mt-1 h-8 border-slate-700 bg-slate-950 text-slate-100" /></div>
          </div>
          <div className="mt-2 flex flex-wrap items-center gap-3">{plans.map((plan) => <label key={plan.id} className="flex items-center gap-1 text-[10px] text-slate-400"><Checkbox checked={!coupon.eligible_plan_ids.length || coupon.eligible_plan_ids.includes(plan.id)} onCheckedChange={() => { const current = coupon.eligible_plan_ids.length ? coupon.eligible_plan_ids : plans.map((p) => p.id); const next = current.includes(plan.id) ? current.filter((id) => id !== plan.id) : [...current, plan.id]; patch.mutate({ id: coupon.id, body: { eligible_plan_ids: next } }); }} data-testid={`coupon-${coupon.code}-${plan.id}-checkbox`} />{plan.name}</label>)}<Button type="button" size="sm" variant="outline" onClick={() => remove.mutate(coupon.id)} data-testid="delete-coupon-button" className="ml-auto h-7 border-slate-700 text-rose-300"><Trash2 className="size-3" /> Remove</Button></div>
        </div>
      ))}</div> : <p className="text-[11px] text-slate-500" data-testid="coupons-empty">No coupons created yet.</p>}
    </div>
  );
}

export function AffiliateAdminPanel() {
  const qc = useQueryClient();
  const site = useQuery({ queryKey: ["admin", "site"], queryFn: () => apiGet<SiteSettings>("/admin/site-settings") });
  const earnings = useQuery({ queryKey: ["admin", "affiliate", "earnings"], queryFn: () => apiGet<AffiliateEarning[]>("/admin/affiliate/earnings") });
  const withdrawals = useQuery({ queryKey: ["admin", "affiliate", "withdrawals"], queryFn: () => apiGet<WithdrawalRow[]>("/admin/affiliate/withdrawals") });
  const [commission, setCommission] = useState(20);
  useEffect(() => { if (site.data) setCommission(site.data.affiliate_commission_pct); }, [site.data]);
  const refresh = () => void qc.invalidateQueries({ queryKey: ["admin"] });
  const saveCommission = useMutation({
    mutationFn: () => apiPut<SiteSettings>("/admin/site-settings", { affiliate_commission_pct: commission }),
    onSuccess: () => { toast.success("Affiliate commission updated"); refresh(); },
    onError: (err) => toast.error(errorText(err)),
  });
  const action = useMutation({
    mutationFn: ({ id, value }: { id: string; value: "approve" | "reject" | "paid" }) => apiPatch<WithdrawalRow>(`/admin/affiliate/withdrawals/${id}`, { action: value, note: "" }),
    onSuccess: () => { toast.success("Withdrawal updated"); refresh(); },
    onError: (err) => toast.error(errorText(err)),
  });
  const totalCommission = (earnings.data ?? []).reduce((sum, row) => sum + row.commission_inr, 0);

  return (
    <div className="space-y-4" data-testid="admin-affiliate-panel">
      <div className="flex flex-wrap items-end gap-3 rounded border border-emerald-900/40 bg-emerald-950/15 p-3">
        <div><Label htmlFor="affiliate-commission" className="text-[11px] text-slate-300">Commission on every paid purchase and renewal (%)</Label><Input id="affiliate-commission" type="number" min="0" max="100" value={commission} onChange={(e) => setCommission(Number(e.target.value))} data-testid="affiliate-commission-input" className="mt-1 w-40 border-slate-700 bg-slate-950 text-slate-100" /></div>
        <Button size="sm" onClick={() => saveCommission.mutate()} disabled={saveCommission.isPending} data-testid="save-affiliate-commission-button">{saveCommission.isPending ? <Loader2 className="size-3.5 animate-spin" /> : <HandCoins className="size-3.5" />} Save rate</Button>
        <p className="text-[11px] text-slate-500">Manual subscription grants never generate commission.</p>
      </div>

      <div className="rounded border border-slate-800 bg-slate-950/30 p-3"><p className="text-[10px] uppercase tracking-wider text-slate-500">Total commission credited</p><p className="text-xl font-semibold text-emerald-300" data-testid="admin-affiliate-total">{rupees(totalCommission)}</p></div>

      <section><h3 className="mb-2 text-sm font-semibold text-slate-100">Withdrawal requests</h3>{(withdrawals.data ?? []).length ? <Table data-testid="admin-withdrawals-table"><TableHeader><TableRow className="border-slate-800 hover:bg-transparent">{["User", "Amount", "Bank", "Status", "Actions"].map((h) => <TableHead key={h} className="h-8 text-[10px] uppercase tracking-wider text-slate-500">{h}</TableHead>)}</TableRow></TableHeader><TableBody>{(withdrawals.data ?? []).map((row) => <TableRow key={row.id} className="border-slate-800 text-[11px]" data-testid="admin-withdrawal-row"><TableCell>{row.user_email}</TableCell><TableCell className="text-amber-300">{rupees(row.amount_inr)}</TableCell><TableCell><div>{row.bank.account_holder || "—"}</div><div className="text-[10px] text-slate-500">{row.bank.bank_name} · {row.bank.account_number} · {row.bank.ifsc_code}</div></TableCell><TableCell><span className={cn("rounded px-1.5 py-0.5", row.status === "paid" ? "bg-emerald-950 text-emerald-300" : row.status === "rejected" ? "bg-rose-950 text-rose-300" : "bg-amber-950 text-amber-300")}>{row.status}</span></TableCell><TableCell><div className="flex gap-1">{row.status === "pending" ? <><Button size="sm" className="h-7" onClick={() => action.mutate({ id: row.id, value: "approve" })} data-testid="approve-withdrawal-button">Approve</Button><Button size="sm" variant="outline" className="h-7 border-slate-700 text-rose-300" onClick={() => action.mutate({ id: row.id, value: "reject" })} data-testid="reject-withdrawal-button">Reject</Button></> : null}{row.status === "approved" ? <><Button size="sm" className="h-7" onClick={() => action.mutate({ id: row.id, value: "paid" })} data-testid="mark-withdrawal-paid-button">Mark paid</Button><Button size="sm" variant="outline" className="h-7 border-slate-700 text-rose-300" onClick={() => action.mutate({ id: row.id, value: "reject" })} data-testid="reject-withdrawal-button">Reject</Button></> : null}</div></TableCell></TableRow>)}</TableBody></Table> : <p className="text-[11px] text-slate-500" data-testid="admin-withdrawals-empty">No withdrawal requests.</p>}</section>

      <section><h3 className="mb-2 text-sm font-semibold text-slate-100">Commission ledger</h3>{(earnings.data ?? []).length ? <Table data-testid="admin-affiliate-earnings-table"><TableHeader><TableRow className="border-slate-800 hover:bg-transparent">{["Referred user", "Plan", "Purchase", "Rate", "Commission", "Date"].map((h) => <TableHead key={h} className="h-8 text-[10px] uppercase tracking-wider text-slate-500">{h}</TableHead>)}</TableRow></TableHeader><TableBody>{(earnings.data ?? []).map((row) => <TableRow key={row.id} className="border-slate-800 text-[11px]"><TableCell>{row.referred_user_email}</TableCell><TableCell>{row.plan_name}</TableCell><TableCell>{rupees(row.purchase_amount_inr)}</TableCell><TableCell>{row.commission_pct}%</TableCell><TableCell className="text-emerald-300">{rupees(row.commission_inr)}</TableCell><TableCell>{row.created_at ? new Date(row.created_at).toLocaleDateString() : "—"}</TableCell></TableRow>)}</TableBody></Table> : <p className="text-[11px] text-slate-500" data-testid="admin-affiliate-earnings-empty">No commissions credited yet.</p>}</section>
    </div>
  );
}
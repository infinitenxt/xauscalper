import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { apiGet, apiPatch, apiPost } from "@/lib/api";
import { errorText } from "@/hooks/useAuth";
import { rupees } from "@/lib/types";
import type { Mt5Account, Plan } from "@/lib/types";
import { cn } from "@/lib/utils";

export default function Mt5AdminPanel() {
  const qc = useQueryClient();
  const plans = useQuery({ queryKey: ["admin", "plans"], queryFn: () => apiGet<Plan[]>("/admin/plans") });
  const accounts = useQuery({ queryKey: ["admin", "mt5", "accounts"], queryFn: () => apiGet<Mt5Account[]>("/admin/mt5/accounts"), refetchInterval: 10000 });
  const plan = (plans.data ?? []).find((item) => item.product_type === "mt5_live");
  const patchPlan = useMutation({ mutationFn: (body: Partial<Plan>) => apiPatch<Plan>(`/admin/plans/${plan?.id}`, body), onSuccess: () => { toast.success("Live MT5 plan updated"); void qc.invalidateQueries({ queryKey: ["admin", "plans"] }); }, onError: (err) => toast.error(errorText(err)) });
  const disable = useMutation({ mutationFn: (id: string) => apiPost<Mt5Account>(`/admin/mt5/accounts/${id}/disable`), onSuccess: () => { toast.success("MT5 autotrading disabled"); void qc.invalidateQueries({ queryKey: ["admin", "mt5"] }); }, onError: (err) => toast.error(errorText(err)) });
  return <div className="space-y-4" data-testid="admin-mt5-panel">
    <section className="rounded border border-amber-900/40 bg-amber-950/15 p-3"><h3 className="text-sm font-semibold text-slate-100">Live MT5 add-on</h3>{plan ? <div className="mt-3 flex flex-wrap items-end gap-3"><div><Label className="text-[11px] text-slate-300">Price (INR)</Label><Input type="number" defaultValue={plan.price_inr} onBlur={(e) => patchPlan.mutate({ price_inr: Number(e.target.value) })} data-testid="mt5-plan-price-input" className="mt-1 w-36 border-slate-700 bg-slate-950" /></div><div><Label className="text-[11px] text-slate-300">Days</Label><Input type="number" defaultValue={plan.days} onBlur={(e) => patchPlan.mutate({ days: Number(e.target.value) })} data-testid="mt5-plan-days-input" className="mt-1 w-28 border-slate-700 bg-slate-950" /></div><label className="flex items-center gap-2 pb-2 text-[11px] text-slate-300"><Checkbox checked={plan.is_active} onCheckedChange={(value) => patchPlan.mutate({ is_active: Boolean(value) })} data-testid="mt5-plan-active-checkbox" />Available for purchase</label><p className="pb-2 text-[11px] text-slate-500">Current price {rupees(plan.price_inr)} / {plan.days} days</p></div> : <p className="mt-2 text-[11px] text-rose-300">Live MT5 plan is missing from seed data.</p>}</section>
    <section><h3 className="mb-2 text-sm font-semibold text-slate-100">Connected MT5 accounts</h3>{(accounts.data ?? []).length ? <Table data-testid="admin-mt5-accounts-table"><TableHeader><TableRow className="border-slate-800 hover:bg-transparent">{["User", "Account", "Mode", "Symbol", "Lot", "State", "Equity", "Action"].map((heading) => <TableHead key={heading} className="h-8 text-[10px] uppercase text-slate-500">{heading}</TableHead>)}</TableRow></TableHeader><TableBody>{(accounts.data ?? []).map((account) => <TableRow key={account.id} className="border-slate-800 text-[11px]" data-testid="admin-mt5-account-row"><TableCell>{account.user_email}</TableCell><TableCell>{account.account_login}<div className="text-[9px] text-slate-500">{account.broker_server}</div></TableCell><TableCell>{account.mode}</TableCell><TableCell>{account.resolved_symbol || "—"}</TableCell><TableCell>{account.lot_size}</TableCell><TableCell><span className={cn("rounded px-1.5 py-0.5", account.connected ? "bg-emerald-950 text-emerald-300" : "bg-amber-950 text-amber-300")}>{account.status} · auto {account.auto_trade_enabled ? "on" : "off"}</span></TableCell><TableCell>{rupees(account.equity)}</TableCell><TableCell><Button size="sm" variant="outline" className="h-7 border-slate-700 text-rose-300" disabled={!account.auto_trade_enabled} onClick={() => disable.mutate(account.id)} data-testid="admin-disable-mt5-button">Disable auto</Button></TableCell></TableRow>)}</TableBody></Table> : <p className="text-[11px] text-slate-500" data-testid="admin-mt5-empty">No subscriber has connected an MT5 account yet.</p>}</section>
  </div>;
}
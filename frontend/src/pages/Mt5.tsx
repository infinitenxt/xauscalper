import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Activity, ArrowLeft, CheckCircle2, Copy, Download, Loader2, Power, ServerCog, ShieldAlert } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Toaster } from "@/components/ui/sonner";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { apiDelete, apiGet, apiPatch, apiPost } from "@/lib/api";
import { errorText, useMe } from "@/hooks/useAuth";
import { loadRazorpayCheckout } from "@/lib/razorpay";
import { rupees } from "@/lib/types";
import type { BillingStatus, Mt5Account, Mt5Command, Mt5ConnectResponse, OrderResponse, SubscriptionInfo } from "@/lib/types";
import { cn } from "@/lib/utils";

export default function Mt5() {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const { data: me } = useMe();
  const account = useQuery({ queryKey: ["mt5", "account"], queryFn: () => apiGet<Mt5Account | null>("/mt5/account"), refetchInterval: 5000 });
  const commands = useQuery({ queryKey: ["mt5", "commands"], queryFn: () => apiGet<Mt5Command[]>("/mt5/commands"), refetchInterval: 5000 });
  const billing = useQuery({ queryKey: ["billing", "status"], queryFn: () => apiGet<BillingStatus>("/billing/status") });
  const [form, setForm] = useState({ mode: "demo", account_login: "", broker_server: "", lot_size: 0.01 });
  const [token, setToken] = useState<{ value: string; url: string; steps: string[] } | null>(null);
  const [lot, setLot] = useState("0.01");
  useEffect(() => { if (account.data) setLot(String(account.data.lot_size)); }, [account.data]);

  useEffect(() => {
    const ping = () => { if (document.visibilityState === "visible") void apiPost("/presence").catch(() => undefined); };
    ping();
    const timer = window.setInterval(ping, 10_000);
    document.addEventListener("visibilitychange", ping);
    return () => { window.clearInterval(timer); document.removeEventListener("visibilitychange", ping); };
  }, []);

  const refresh = () => { void qc.invalidateQueries({ queryKey: ["mt5"] }); void qc.invalidateQueries({ queryKey: ["billing"] }); };
  const connect = useMutation({
    mutationFn: () => apiPost<Mt5ConnectResponse>("/mt5/account", { ...form, lot_size: Number(form.lot_size) }),
    onSuccess: (result) => { setToken({ value: result.bridge_token, url: result.bridge_url, steps: result.setup_steps }); toast.success("MT5 connection created — finish setup in the EA"); refresh(); },
    onError: (err) => toast.error(errorText(err)),
  });
  const patchAccount = useMutation({
    mutationFn: (body: { lot_size?: number; auto_trade_enabled?: boolean }) => apiPatch<Mt5Account>("/mt5/account", body),
    onSuccess: () => { toast.success("MT5 settings updated"); refresh(); },
    onError: (err) => toast.error(errorText(err)),
  });
  const disconnect = useMutation({
    mutationFn: () => apiDelete<{ message: string }>("/mt5/account"),
    onSuccess: (result) => { toast.success(result.message); setToken(null); refresh(); },
    onError: (err) => toast.error(errorText(err)),
  });
  const verify = useMutation({
    mutationFn: (body: { plan_id: string; razorpay_order_id: string; razorpay_payment_id: string; razorpay_signature: string }) => apiPost<SubscriptionInfo>("/billing/verify", body),
    onSuccess: () => { toast.success("Live MT5 add-on activated"); refresh(); },
    onError: (err) => toast.error(errorText(err, "Could not verify the add-on payment.")),
  });
  const buyLive = useMutation({
    mutationFn: async () => {
      const plan = billing.data?.mt5_live_plan;
      if (!plan) throw new Error("Live MT5 plan is unavailable");
      return apiPost<OrderResponse>("/billing/order", { plan_id: plan.id });
    },
    onSuccess: async (order) => {
      const ready = await loadRazorpayCheckout();
      if (!ready || !window.Razorpay) { toast.error("Could not load Razorpay checkout."); return; }
      new window.Razorpay({
        key: order.key_id, amount: order.amount, currency: order.currency,
        name: "Gold Paper Terminal", description: `${order.plan.name} · ${order.plan.days} days`,
        order_id: order.order_id, prefill: { email: me?.email ?? "", name: me?.username ?? "" },
        theme: { color: "#eab308" },
        handler: (response) => verify.mutate({ plan_id: order.plan.id, ...response }),
        modal: { ondismiss: () => toast.message("Payment window closed.") },
      }).open();
    },
    onError: (err) => toast.error(errorText(err, "Could not start Live MT5 checkout.")),
  });

  const current = account.data;
  const live = billing.data?.mt5_live_entitlement;
  const plan = billing.data?.mt5_live_plan;
  return (
    <div className="min-h-screen bg-[#0b0e14] p-4">
      <Toaster position="bottom-right" richColors />
      <div className="mx-auto max-w-6xl space-y-4">
        <header className="flex flex-wrap items-center justify-between gap-3 rounded-md border border-slate-800 bg-[#111827] p-4">
          <div><h1 className="flex items-center gap-2 text-lg font-semibold text-slate-100" data-testid="mt5-page-title"><ServerCog className="size-5 text-amber-400" /> MT5 execution bridge</h1><p className="text-[11px] text-slate-500">Private XAU/USD-only execution · one bot position · new entries require dashboard presence</p></div>
          <Button variant="outline" size="sm" onClick={() => navigate("/")} data-testid="mt5-back-button" className="border-slate-700 text-slate-300"><ArrowLeft className="size-3.5" /> Terminal</Button>
        </header>

        <section className="rounded-md border border-rose-900/40 bg-rose-950/15 p-3 text-[11px] text-rose-200" data-testid="mt5-risk-warning"><ShieldAlert className="mr-1 inline size-4" />Live MT5 orders use real money. Broker SL/TP are placed with every entry. The EA continues break-even, partial close, trailing stop and autocut when this dashboard closes, but a VPS/terminal outage can delay non-broker exits.</section>

        {!current ? <div className="grid gap-4 lg:grid-cols-[1.5fr_1fr]">
          <form className="rounded-md border border-slate-800 bg-[#111827] p-4" onSubmit={(e) => { e.preventDefault(); connect.mutate(); }} data-testid="mt5-connect-form">
            <h2 className="text-sm font-semibold text-slate-100">Connect your private MT5 account</h2>
            <div className="mt-3 grid gap-3 sm:grid-cols-2">
              <div><Label className="text-[11px] text-slate-300">Account mode</Label><Select value={form.mode} onValueChange={(value) => setForm((v) => ({ ...v, mode: value }))}><SelectTrigger className="mt-1" data-testid="mt5-mode-select"><SelectValue>{(value) => value === "live" ? "Live account" : "Demo account"}</SelectValue></SelectTrigger><SelectContent><SelectItem value="demo">Demo account</SelectItem><SelectItem value="live">Live account</SelectItem></SelectContent></Select></div>
              <div><Label htmlFor="mt5-login" className="text-[11px] text-slate-300">MT5 account login</Label><Input id="mt5-login" required value={form.account_login} onChange={(e) => setForm((v) => ({ ...v, account_login: e.target.value }))} data-testid="mt5-login-input" className="mt-1 border-slate-700 bg-slate-950 text-slate-100" /></div>
              <div><Label htmlFor="mt5-server" className="text-[11px] text-slate-300">Exact broker server</Label><Input id="mt5-server" required value={form.broker_server} onChange={(e) => setForm((v) => ({ ...v, broker_server: e.target.value }))} placeholder="Broker-Demo" data-testid="mt5-server-input" className="mt-1 border-slate-700 bg-slate-950 text-slate-100" /></div>
              <div><Label htmlFor="mt5-lot" className="text-[11px] text-slate-300">Fixed lot size</Label><Input id="mt5-lot" type="number" min="0.001" step="0.001" required value={form.lot_size} onChange={(e) => setForm((v) => ({ ...v, lot_size: Number(e.target.value) }))} data-testid="mt5-lot-input" className="mt-1 border-slate-700 bg-slate-950 text-slate-100" /></div>
            </div>
            {form.mode === "live" && !live?.active ? <p className="mt-3 text-[11px] text-amber-300" data-testid="mt5-live-required">A separate Live MT5 add-on is required before connecting this live account.</p> : null}
            <Button className="mt-4" type="submit" disabled={connect.isPending || (form.mode === "live" && !live?.active)} data-testid="connect-mt5-button">{connect.isPending ? <Loader2 className="size-4 animate-spin" /> : <Power className="size-4" />} Create secure bridge</Button>
          </form>
          <section className="rounded-md border border-amber-900/40 bg-amber-950/15 p-4" data-testid="mt5-live-plan-card"><p className="text-[10px] uppercase tracking-wider text-amber-400">Live execution entitlement</p><h2 className="mt-1 text-lg font-semibold text-slate-100">{plan?.name ?? "Live MT5 Add-on"}</h2><p className="mt-1 text-2xl font-bold text-amber-300">{plan ? rupees(plan.price_inr) : "Unavailable"}<span className="text-[11px] font-normal text-slate-500"> / {plan?.days ?? 0} days</span></p><p className="mt-3 text-[11px] text-slate-400">{live?.active ? `Active · ${live.days_left} day(s) left` : "Demo MT5 is included in your normal subscription. Live execution requires this add-on."}</p>{!live?.active ? <Button className="mt-3 w-full" disabled={!plan || !billing.data?.razorpay_enabled || buyLive.isPending} onClick={() => buyLive.mutate()} data-testid="buy-mt5-live-button">Buy live add-on</Button> : <div className="mt-3 flex items-center gap-2 text-[11px] text-emerald-300"><CheckCircle2 className="size-4" /> Live account enabled</div>}</section>
        </div> : (
          <>
            <section className="rounded-md border border-slate-800 bg-[#111827] p-4" data-testid="mt5-account-panel">
              <div className="flex flex-wrap items-start justify-between gap-3"><div><p className="text-[10px] uppercase tracking-wider text-slate-500">Connected account</p><h2 className="mt-1 text-lg font-semibold text-slate-100">{current.account_login} · {current.broker_server}</h2><p className="text-[11px] text-slate-500">{current.mode.toUpperCase()} · {current.resolved_symbol || "waiting for symbol discovery"}</p></div><span className={cn("rounded px-2 py-1 text-[11px] font-semibold", current.connected ? "bg-emerald-950 text-emerald-300" : "bg-amber-950 text-amber-300")} data-testid="mt5-connection-state">{current.connected ? "EA CONNECTED" : current.status.toUpperCase()}</span></div>
              <div className="mt-4 grid gap-2 sm:grid-cols-3 lg:grid-cols-6">{[["Balance", rupees(current.balance)],["Equity", rupees(current.equity)],["Free margin", rupees(current.free_margin)],["Today", rupees(current.daily_profit)],["Broker min", current.volume_min || "—"],["Broker max", current.volume_max || "—"]].map(([label, value]) => <div key={String(label)} className="rounded border border-slate-800 bg-slate-950/40 p-2"><p className="text-[9px] uppercase text-slate-500">{label}</p><p className="text-sm font-semibold text-slate-200">{value}</p></div>)}</div>
              {current.last_error ? <p className="mt-3 text-[11px] text-amber-300" data-testid="mt5-account-error">{current.last_error}</p> : null}
              <div className="mt-4 flex flex-wrap items-end gap-3"><div><Label htmlFor="mt5-current-lot" className="text-[11px] text-slate-300">Fixed lot size</Label><Input id="mt5-current-lot" type="number" value={lot} onChange={(e) => setLot(e.target.value)} data-testid="mt5-current-lot-input" className="mt-1 w-36 border-slate-700 bg-slate-950 text-slate-100" /></div><Button size="sm" variant="outline" onClick={() => patchAccount.mutate({ lot_size: Number(lot) })} data-testid="save-mt5-lot-button" className="border-slate-700">Save lot</Button><label className="flex items-center gap-2 pb-1 text-[11px] text-slate-300"><Checkbox checked={current.auto_trade_enabled} onCheckedChange={(value) => patchAccount.mutate({ auto_trade_enabled: Boolean(value) })} data-testid="mt5-auto-trade-switch" />Auto-trade {current.auto_trade_enabled ? "ON" : "OFF"}</label><Button size="sm" variant="outline" onClick={() => disconnect.mutate()} data-testid="disconnect-mt5-button" className="ml-auto border-slate-700 text-rose-300">Disconnect</Button></div>
            </section>
            {current.position ? <section className="rounded-md border border-emerald-900/40 bg-emerald-950/10 p-4" data-testid="mt5-open-position"><h2 className="text-sm font-semibold text-slate-100">Live MT5 position</h2><div className="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-6">{[["Side", current.position.direction],["Lots", current.position.volume],["Entry", current.position.entry_price],["SL", current.position.sl],["TP", current.position.tp],["P&L", rupees(current.position.profit)]].map(([label, value]) => <div key={String(label)}><p className="text-[9px] uppercase text-slate-500">{label}</p><p className="text-sm text-slate-200">{value}</p></div>)}</div><p className="mt-3 text-[10px] text-slate-500">The EA continues SL/TP, break-even, partial close, trailing stop and hard autocut even if the dashboard closes.</p></section> : null}
          </>
        )}

        {token ? <section className="rounded-md border border-sky-900/50 bg-sky-950/15 p-4" data-testid="mt5-one-time-token"><h2 className="text-sm font-semibold text-sky-200">One-time EA setup credentials</h2><p className="mt-1 text-[11px] text-slate-400">Copy these now. The token is stored only as a hash and cannot be shown again.</p>{[["Bridge URL", token.url],["Bridge token", token.value]].map(([label, value]) => <div key={label} className="mt-2"><p className="text-[9px] uppercase text-slate-500">{label}</p><div className="flex gap-2"><code className="min-w-0 flex-1 truncate rounded bg-slate-950 px-2 py-1.5 text-[11px] text-slate-200" data-testid={`mt5-${label.toLowerCase().replace(" ", "-")}`}>{value}</code><Button size="sm" variant="outline" onClick={() => void navigator.clipboard.writeText(value)} className="border-slate-700"><Copy className="size-3.5" /></Button></div></div>)}<ol className="mt-3 list-decimal space-y-1 pl-4 text-[11px] text-slate-400">{token.steps.map((step) => <li key={step}>{step}</li>)}</ol><a href="/GoldTerminalBridge.mq5" download className="mt-3 inline-flex items-center gap-2 rounded bg-amber-500 px-3 py-2 text-[11px] font-semibold text-slate-950" data-testid="download-mt5-ea-link"><Download className="size-4" /> Download MT5 EA</a></section> : null}

        <section className="rounded-md border border-slate-800 bg-[#111827] p-4" data-testid="mt5-command-history"><h2 className="mb-3 flex items-center gap-2 text-sm font-semibold text-slate-100"><Activity className="size-4 text-amber-400" /> Execution history</h2>{(commands.data ?? []).length ? <Table><TableHeader><TableRow className="border-slate-800 hover:bg-transparent">{["Action", "Side", "Lots", "Status", "Reason", "Broker"].map((heading) => <TableHead key={heading} className="h-8 text-[10px] uppercase text-slate-500">{heading}</TableHead>)}</TableRow></TableHeader><TableBody>{(commands.data ?? []).map((command) => <TableRow key={command.id} className="border-slate-800 text-[11px]" data-testid="mt5-command-row"><TableCell>{command.action}</TableCell><TableCell>{command.direction || "—"}</TableCell><TableCell>{command.lots || "—"}</TableCell><TableCell>{command.status}</TableCell><TableCell className="max-w-xs truncate">{command.reason || "—"}</TableCell><TableCell>{command.broker_ticket || command.broker_message || "—"}</TableCell></TableRow>)}</TableBody></Table> : <p className="text-[11px] text-slate-500" data-testid="mt5-commands-empty">No MT5 execution commands yet.</p>}</section>
      </div>
    </div>
  );
}
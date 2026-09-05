import { useEffect, useState } from "react";
import { Bot, ShieldAlert } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { fmt } from "@/lib/types";
import type { Mt5Account, SurvivalStatus } from "@/lib/types";
import { cn } from "@/lib/utils";

interface Props {
  account: Mt5Account;
  status: SurvivalStatus | undefined;
  saving: boolean;
  onSave: (value: { enabled: boolean; daily_profit_target_usd: number; daily_drawdown_limit_pct: number; max_drawdown_limit_pct: number }) => void;
}

export default function SurvivalModePanel({ account, status, saving, onSave }: Props) {
  const [enabled, setEnabled] = useState(false);
  const [target, setTarget] = useState(25);
  const [dailyDd, setDailyDd] = useState(3);
  const [maxDd, setMaxDd] = useState(10);

  useEffect(() => {
    if (!status) return;
    setEnabled(status.enabled || status.activation_requested);
    setTarget(status.daily_profit_target_usd);
    setDailyDd(status.daily_drawdown_limit_pct);
    setMaxDd(status.max_drawdown_limit_pct);
  }, [status]);

  const state = status?.status ?? "idle";
  const halted = state.includes("halt") || state === "target_reached";
  return (
    <section className="overflow-hidden rounded-md border border-slate-800 bg-[#0e131f] shadow-xl" data-testid="survival-mode-panel">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-800 bg-slate-950/40 p-4">
        <div>
          <p className="text-[10px] font-semibold uppercase tracking-[0.2em] text-sky-400">Dual-agent risk mission</p>
          <h2 className="mt-1 text-lg font-bold text-slate-100">Survival Mode</h2>
          <p className="text-[10px] text-slate-500">GPT-5.4 + Claude Sonnet 4.6 · unanimous entries only</p>
        </div>
        <div className="flex items-center gap-3">
          <span className={cn("rounded px-2 py-1 text-[10px] font-semibold uppercase", status?.enabled ? "bg-emerald-950 text-emerald-300" : halted ? "bg-rose-950 text-rose-300" : "bg-slate-800 text-slate-400")} data-testid="survival-session-status">{state.replaceAll("_", " ")}</span>
          <Switch checked={enabled} onCheckedChange={setEnabled} data-testid="survival-mode-master-toggle" />
        </div>
      </div>

      {!status?.broker_feed_ready ? (
        <div className="m-3 flex items-start gap-2 rounded border border-amber-900/50 bg-amber-950/20 p-2.5 text-[11px] text-amber-200" data-testid="broker-feed-readiness-indicator">
          <ShieldAlert className="mt-0.5 size-3.5 shrink-0" /> Broker data is syncing or stale. Recompile and restart Universal EA v4.4; Survival Mode stays locked until the first broker history sync completes.
        </div>
      ) : null}

      <div className="grid gap-3 p-3 lg:grid-cols-12">
        <div className="space-y-3 rounded border border-slate-800 bg-slate-950/35 p-3 lg:col-span-5">
          <div className="grid grid-cols-2 gap-2">
            <Metric label="MT5 balance" value={`${account.account_currency || "USD"} ${fmt(status?.balance ?? account.balance, 2)}`} testid="survival-mt5-balance-display" />
            <Metric label="Equity" value={`${account.account_currency || "USD"} ${fmt(status?.equity ?? account.equity, 2)}`} testid="survival-equity-display" />
          </div>
          <Field label="Daily profit target (USD)" value={target} onChange={setTarget} testid="survival-profit-target-input" />
          <div className="grid grid-cols-2 gap-2">
            <Field label="Daily drawdown %" value={dailyDd} onChange={setDailyDd} testid="survival-daily-drawdown-input" />
            <Field label="Max drawdown %" value={maxDd} onChange={setMaxDd} testid="survival-max-drawdown-input" />
          </div>
          <Button className="w-full bg-sky-600 text-white hover:bg-sky-500" disabled={saving} onClick={() => onSave({ enabled, daily_profit_target_usd: target, daily_drawdown_limit_pct: dailyDd, max_drawdown_limit_pct: maxDd })} data-testid="survival-save-settings-button">
            {saving ? "Saving…" : enabled && !status?.broker_feed_ready ? "Save and start after broker sync" : enabled ? "Start / update Survival Mode" : "Disable Survival Mode"}
          </Button>
        </div>

        <div className="space-y-3 lg:col-span-7">
          <div className="grid grid-cols-2 gap-2">
            <AgentCard name="ChatGPT" tone="emerald" value={status?.gpt} testid="agent-gpt-status-card" />
            <AgentCard name="Claude" tone="purple" value={status?.claude} testid="agent-claude-status-card" />
          </div>
          <div className="rounded border border-indigo-900/50 bg-indigo-950/20 p-2.5" data-testid="agent-consensus-agreement-badge">
            <p className="text-[9px] uppercase tracking-[0.18em] text-indigo-300">Consensus</p>
            <p className="mt-1 text-sm font-semibold text-slate-100">{status?.consensus ?? "IDLE"}</p>
            {status?.last_error ? <p className="mt-1 text-[10px] text-amber-300">{status.last_error}</p> : null}
          </div>
          <Gauge label="Daily target" value={status?.target_progress_pct ?? 0} limit={100} tone="bg-emerald-500" testid="survival-target-progress-bar" suffix={`${fmt(status?.daily_profit_usd ?? 0, 2)} USD`} />
          <Gauge label="Daily drawdown" value={status?.daily_drawdown_pct ?? 0} limit={status?.daily_drawdown_limit_pct ?? dailyDd} tone="bg-amber-500" testid="survival-daily-drawdown-bar" />
          <Gauge label="Peak drawdown" value={status?.max_drawdown_pct ?? 0} limit={status?.max_drawdown_limit_pct ?? maxDd} tone="bg-rose-500" testid="survival-max-drawdown-bar" />
        </div>
      </div>
      {halted ? <div className="border-t border-rose-900/50 bg-rose-950/25 px-4 py-2 text-[11px] text-rose-200" data-testid="hard-risk-shutdown-alert-banner">Survival Mode halted deterministically. Auto-trading is off and AI calls have stopped.</div> : null}
    </section>
  );
}

function Metric({ label, value, testid }: { label: string; value: string; testid: string }) {
  return <div className="rounded border border-slate-800 bg-[#141c2e] p-2"><p className="text-[9px] uppercase tracking-wider text-slate-500">{label}</p><p className="mt-1 font-mono text-sm font-semibold text-slate-100" data-testid={testid}>{value}</p></div>;
}

function Field({ label, value, onChange, testid }: { label: string; value: number; onChange: (value: number) => void; testid: string }) {
  return <div><Label className="text-[10px] text-slate-400">{label}</Label><Input type="number" min="0.1" step="0.1" value={value} onChange={(event) => onChange(Number(event.target.value))} className="mt-1 border-slate-700 bg-slate-950 font-mono text-slate-100" data-testid={testid} /></div>;
}

function AgentCard({ name, tone, value, testid }: { name: string; tone: "emerald" | "purple"; value: Record<string, unknown> | undefined; testid: string }) {
  const action = String(value?.action ?? "WAITING");
  const direction = String(value?.direction ?? "WAIT");
  return <div className={cn("rounded border p-2.5", tone === "emerald" ? "border-emerald-900/60 bg-emerald-950/15" : "border-purple-900/60 bg-purple-950/15")} data-testid={testid}><p className="flex items-center gap-1 text-[9px] uppercase tracking-[0.18em] text-slate-500"><Bot className="size-3" /> {name}</p><p className="mt-1 text-sm font-semibold text-slate-100">{action} · {direction}</p><p className="mt-1 line-clamp-2 text-[9px] text-slate-500">{String(value?.reason ?? "Awaiting the next closed broker candle")}</p></div>;
}

function Gauge({ label, value, limit, tone, testid, suffix }: { label: string; value: number; limit: number; tone: string; testid: string; suffix?: string }) {
  const percentage = limit > 0 ? Math.min(100, Math.max(0, value / limit * 100)) : 0;
  return <div><div className="mb-1 flex justify-between text-[9px] uppercase tracking-wider text-slate-500"><span>{label}</span><span className="font-mono">{suffix ?? `${fmt(value, 2)} / ${fmt(limit, 2)}%`}</span></div><div className="h-1.5 overflow-hidden rounded bg-slate-800"><div className={cn("h-full rounded transition-[width] duration-500", tone)} style={{ width: `${label === "Daily target" ? Math.min(100, value) : percentage}%` }} data-testid={testid} /></div></div>;
}
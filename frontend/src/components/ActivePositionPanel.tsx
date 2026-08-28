import { Activity, Clock, Crosshair, ServerCog, Timer, TrendingDown, TrendingUp } from "lucide-react";
import { Button } from "@/components/ui/button";
import { duration, fmt, money, signed } from "@/lib/types";
import type { EngineConfig, Mt5Account, Mt5Position, Trade } from "@/lib/types";
import { cn } from "@/lib/utils";

interface Props {
  trade: Trade | null | undefined;
  mt5Account: Mt5Account | null | undefined;
  config: EngineConfig | undefined;
  onClose: (id: string) => void;
  closing: boolean;
}

/** Live position, shown beside the signal banner at the top of the terminal. */
export default function ActivePositionPanel({ trade, mt5Account, config, onClose, closing }: Props) {
  const pnl = trade?.unrealized_pnl ?? 0;
  const long = trade?.direction === "BUY";

  return (
    <section
      className="col-span-12 rounded-md border border-slate-800 bg-[#111827] p-3 shadow-xl lg:col-span-5"
      data-testid="active-position-panel"
    >
      <div className="mb-2.5 flex items-center justify-between border-b border-slate-800/80 pb-2">
        <h3 className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wider text-slate-400">
          <Crosshair className="size-3.5 text-amber-400" /> Active positions
        </h3>
        <span className="text-[9px] uppercase tracking-widest text-slate-600" data-testid="execution-policy-label">
          MT5 trigger · confidence ≥ {fmt(config?.confidence_threshold ?? 80, 0)}%
        </span>
      </div>

      <div className="grid grid-cols-1 gap-2.5 md:grid-cols-2">
        <section className="flex flex-col rounded-md border border-slate-800/90 bg-[#0b0f19]/90 p-2.5" data-testid="paper-position-section">
          <div className="mb-2 flex items-center justify-between">
            <span className="text-[9px] font-semibold uppercase tracking-widest text-slate-500" data-testid="paper-engine-label">Paper engine</span>
            <span className="rounded bg-slate-800 px-1.5 py-0.5 text-[9px] text-slate-400" data-testid="paper-position-status">
              {trade ? `${trade.timeframe} · ${fmt(trade.confidence, 1)}%` : "FLAT"}
            </span>
          </div>
          {!trade ? (
            <div className="flex flex-1 flex-col justify-center rounded border border-dashed border-slate-800 p-3" data-testid="no-active-trade">
              <p className="text-[11px] text-slate-400" data-testid="paper-flat-label">No paper position</p>
              <p className="mt-1 text-[9px] leading-relaxed text-slate-600" data-testid="paper-flat-detail">
                Paper entries still require confidence and every paper-account risk gate.
              </p>
            </div>
          ) : (
            <div className="space-y-2.5 animate-rise-in" data-testid="active-trade-card">
          <div className="flex items-center justify-between">
            <span
              className={cn(
                "flex items-center gap-1.5 rounded border px-2 py-0.5 text-[11px] font-semibold",
                long
                  ? "border-emerald-700/60 bg-emerald-950/70 text-emerald-300"
                  : "border-rose-800/60 bg-rose-950/70 text-rose-300",
              )}
              data-testid="active-trade-direction"
            >
              {long ? <TrendingUp className="size-3" /> : <TrendingDown className="size-3" />}
              {trade.direction} {trade.qty} oz
            </span>
            <span
              className={cn("tabular-nums text-base font-semibold", pnl >= 0 ? "text-emerald-400" : "text-rose-400")}
              data-testid="active-trade-pnl"
            >
              {money(pnl)}{" "}
              <span className="text-[11px] font-normal">({signed(trade.r_multiple ?? 0, 2)}R)</span>
            </span>
          </div>

          <div className="grid grid-cols-4 gap-1.5 text-[10px]">
            <MiniStat label="Entry" value={fmt(trade.entry)} testid="active-trade-entry" tone="text-sky-300" />
            <MiniStat label="SL" value={fmt(trade.sl)} testid="active-trade-sl" tone="text-rose-300" />
            <MiniStat label="TP" value={fmt(trade.tp)} testid="active-trade-tp" tone="text-emerald-300" />
            <MiniStat label="Now" value={fmt(trade.current_price)} testid="active-trade-price" />
          </div>

          <div>
            <div className="mb-1 flex justify-between text-[10px] text-slate-500">
              <span>Progress to target</span>
              <span className="tabular-nums">{fmt(trade.tp_progress_pct ?? 0, 1)}%</span>
            </div>
            <div className="h-1.5 overflow-hidden rounded-full bg-slate-800">
              <div
                className="h-full rounded-full bg-emerald-500 transition-[width] duration-500"
                style={{ width: `${Math.min(100, trade.tp_progress_pct ?? 0)}%` }}
                data-testid="active-trade-progress"
              />
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-2 text-[10px] text-slate-400">
            <span className="flex items-center gap-1">
              <Clock className="size-3" /> held {duration(trade.age_seconds)}
            </span>
            <span className="flex items-center gap-1">
              <Timer className="size-3" /> auto-cut in {duration(trade.seconds_to_timeout)}
            </span>
            <span
              className={cn(
                "rounded px-1.5 py-0.5",
                trade.breakeven_done ? "bg-sky-950 text-sky-300" : "bg-slate-800 text-slate-500",
              )}
              data-testid="active-trade-breakeven"
            >
              break-even {trade.breakeven_done ? "SET" : "pending"}
            </span>
            <span
              className={cn(
                "rounded px-1.5 py-0.5",
                trade.partial_done ? "bg-emerald-950 text-emerald-300" : "bg-slate-800 text-slate-500",
              )}
              data-testid="active-trade-partial"
            >
              partial {trade.partial_done ? `BANKED ${money(trade.partial_pnl)}` : "pending"}
            </span>
            <span
              className={cn(
                "rounded px-1.5 py-0.5",
                trade.trailing_active ? "bg-emerald-950 text-emerald-300" : "bg-slate-800 text-slate-500",
              )}
              data-testid="active-trade-trailing"
            >
              trailing {trade.trailing_active ? "ARMED" : "idle"}
            </span>
          </div>

          <details className="rounded border border-slate-800 bg-slate-950/50 p-2" data-testid="active-trade-reasons">
            <summary className="cursor-pointer text-[10px] uppercase tracking-wider text-slate-500">
              Why this trade is open
            </summary>
            {trade.ai_status === "ai" && trade.ai_explanation ? (
              <p
                className="mt-1.5 rounded border border-amber-900/40 bg-amber-950/20 p-2 text-[11px] leading-relaxed text-amber-100/90"
                data-testid="active-trade-ai-explanation"
              >
                <span className="mr-1 rounded bg-amber-900/60 px-1 py-0.5 text-[9px] font-semibold text-amber-200">
                  AI
                </span>
                {trade.ai_explanation}
              </p>
            ) : (
              <p className="mt-1.5 text-[10px] italic text-slate-500" data-testid="active-trade-ai-pending">
                {trade.ai_status === "pending"
                  ? "AI is writing the trade rationale…"
                  : "AI rationale unavailable — using the engine's own reasons below."}
              </p>
            )}
            <ul className="mt-1.5 space-y-1">
              {[...trade.entry_reasons, ...trade.risk_reasons].map((r) => (
                <li key={r} className="text-[10px] leading-relaxed text-slate-400">
                  · {r}
                </li>
              ))}
            </ul>
          </details>

          <Button
            variant="destructive"
            size="sm"
            className="w-full"
            disabled={closing}
            onClick={() => onClose(trade.id)}
            data-testid="close-trade-button"
          >
            {closing ? "Closing…" : "Close position manually"}
          </Button>
            </div>
          )}
        </section>

        <Mt5PositionSection account={mt5Account} threshold={config?.confidence_threshold ?? 80} />
      </div>
    </section>
  );
}

function Mt5PositionSection({ account, threshold }: { account: Mt5Account | null | undefined; threshold: number }) {
  if (!account) {
    return (
      <section className="flex min-h-40 flex-col rounded-md border border-indigo-950/60 bg-[#0c1021]/90 p-2.5" data-testid="mt5-position-section">
        <div className="flex items-center justify-between">
          <span className="flex items-center gap-1 text-[9px] font-semibold uppercase tracking-widest text-indigo-300"><ServerCog className="size-3" /> MT5 terminal</span>
          <span className="rounded bg-slate-800 px-1.5 py-0.5 text-[9px] text-slate-400" data-testid="mt5-connection-status-badge">NOT LINKED</span>
        </div>
        <div className="flex flex-1 flex-col justify-center">
          <p className="text-[11px] text-slate-400" data-testid="mt5-disconnected-label">No MT5 account connected</p>
          <p className="mt-1 text-[9px] text-slate-600" data-testid="mt5-disconnected-detail">Open MT5 setup from the top navigation to link a terminal.</p>
        </div>
      </section>
    );
  }

  const amount = (value: number) => account.account_currency ? `${account.account_currency} ${fmt(value, 2)}` : fmt(value, 2);
  return (
    <section className="relative flex flex-col overflow-hidden rounded-md border border-indigo-950/60 bg-[#0c1021]/90 p-2.5" data-testid="mt5-position-section">
      <div className="mb-2 flex items-center justify-between gap-2">
        <span className="flex items-center gap-1 text-[9px] font-semibold uppercase tracking-widest text-indigo-300" data-testid="mt5-terminal-label"><ServerCog className="size-3" /> MT5 live terminal</span>
        <span className={cn("rounded px-1.5 py-0.5 text-[9px] font-semibold", account.connected ? "bg-emerald-950 text-emerald-300" : "bg-slate-800 text-slate-400")} data-testid="mt5-connection-status-badge">
          {account.connected ? `${account.mode.toUpperCase()} · CONNECTED` : account.status.toUpperCase()}
        </span>
      </div>

      <div className="grid grid-cols-2 gap-1" data-testid="mt5-account-telemetry">
        <MiniStat label="Balance" value={amount(account.balance)} testid="mt5-telemetry-balance" />
        <MiniStat label="Equity" value={amount(account.equity)} testid="mt5-telemetry-equity" />
        <MiniStat label="Margin" value={amount(account.margin)} testid="mt5-telemetry-margin" />
        <MiniStat label="Free margin" value={amount(account.free_margin)} testid="mt5-telemetry-free-margin" />
      </div>
      <div className="mt-1 flex items-center justify-between text-[9px] text-slate-500">
        <span data-testid="mt5-symbol-label">{account.resolved_symbol || "symbol pending"} · {account.lot_size} lot{account.ea_version ? ` · EA v${account.ea_version}` : ""}</span>
        <span className="tabular-nums" data-testid="mt5-telemetry-margin-level">Margin level {account.margin_level ? `${fmt(account.margin_level, 1)}%` : "—"}</span>
      </div>

      {account.position ? <Mt5TradeCard position={account.position} /> : (
        <div className={cn("mt-2 rounded border p-2", account.entry_state === "blocked" ? "border-amber-900/60 bg-amber-950/30" : "border-slate-800 bg-slate-950/40")} data-testid="execution-blocked-reason-banner">
          <div className="flex items-center gap-1 text-[9px] font-semibold uppercase tracking-wider text-slate-400" data-testid="mt5-entry-state"><Activity className="size-3" /> {account.entry_state || "waiting"}</div>
          <p className="mt-1 text-[9px] leading-relaxed text-slate-500" data-testid="mt5-entry-reason">
            {account.entry_reason || `Waiting for ${fmt(threshold, 0)}% confidence`}
          </p>
        </div>
      )}
      {account.last_error ? <p className="mt-1.5 text-[9px] text-amber-300" data-testid="mt5-dashboard-error">{account.last_error}</p> : null}
    </section>
  );
}

function Mt5TradeCard({ position }: { position: Mt5Position }) {
  const long = position.direction === "BUY";
  const favorable = (position.current_price - position.entry_price) * (long ? 1 : -1);
  const risk = Math.abs(position.entry_price - position.sl);
  const target = Math.abs(position.tp - position.entry_price);
  const towardTarget = favorable >= 0;
  const progress = Math.min(100, Math.max(0, Math.abs(favorable) / (towardTarget ? target || 1 : risk || 1) * 100));
  const rMultiple = risk ? favorable / risk : 0;
  const ageSeconds = position.opened_at ? Math.max(0, (Date.now() - new Date(position.opened_at).getTime()) / 1000) : null;

  return (
    <div className="mt-2 space-y-2 rounded border border-indigo-900/50 bg-slate-950/50 p-2 animate-rise-in" data-testid="mt5-active-trade-card">
      <div className="flex items-center justify-between gap-2">
        <span className={cn("flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] font-semibold", long ? "bg-emerald-950 text-emerald-300" : "bg-rose-950 text-rose-300")} data-testid="mt5-trade-direction">
          {long ? <TrendingUp className="size-3" /> : <TrendingDown className="size-3" />} {position.direction} · {position.volume} lot
        </span>
        <span className={cn("tabular-nums text-[11px] font-semibold", position.profit >= 0 ? "text-emerald-400" : "text-rose-400")} data-testid="mt5-trade-pnl">{signed(position.profit, 2)} · {signed(rMultiple, 2)}R</span>
      </div>
      <div className="grid grid-cols-4 gap-1">
        <MiniStat label="Entry" value={fmt(position.entry_price)} testid="mt5-trade-entry" tone="text-sky-300" />
        <MiniStat label="SL" value={fmt(position.sl)} testid="mt5-trade-sl" tone="text-rose-300" />
        <MiniStat label="TP" value={fmt(position.tp)} testid="mt5-trade-tp" tone="text-emerald-300" />
        <MiniStat label="Now" value={fmt(position.current_price)} testid="mt5-trade-price" />
      </div>
      <div>
        <div className="mb-1 flex justify-between text-[9px] text-slate-500">
          <span data-testid="mt5-trade-progress-label">Toward {towardTarget ? "target" : "stop"}</span>
          <span className="tabular-nums" data-testid="mt5-trade-progress-value">{fmt(progress, 1)}%</span>
        </div>
        <div className="h-1.5 overflow-hidden rounded-full bg-slate-800">
          <div className={cn("h-full rounded-full transition-[width] duration-700", towardTarget ? "bg-emerald-500" : "bg-rose-500")} style={{ width: `${progress}%` }} data-testid="mt5-trade-progress" />
        </div>
      </div>
      <div className="flex items-center justify-between text-[9px] text-slate-500">
        <span data-testid="mt5-trade-ticket">#{position.ticket} · {position.symbol}</span>
        <span data-testid="mt5-trade-age">{ageSeconds === null ? "open time pending" : `held ${duration(ageSeconds)}`}</span>
      </div>
    </div>
  );
}

function MiniStat({
  label,
  value,
  testid,
  tone,
}: {
  label: string;
  value: string;
  testid: string;
  tone?: string;
}) {
  return (
    <div className="rounded border border-slate-800 bg-slate-950/50 p-1.5">
      <div className="text-[9px] uppercase tracking-wider text-slate-500">{label}</div>
      <div className={cn("tabular-nums text-slate-200", tone)} data-testid={testid}>
        {value}
      </div>
    </div>
  );
}

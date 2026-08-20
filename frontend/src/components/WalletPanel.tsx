import { Clock, Timer, TrendingDown, TrendingUp, Wallet as WalletIcon } from "lucide-react";
import { Button } from "@/components/ui/button";
import { duration, fmt, money, signed } from "@/lib/types";
import type { EngineConfig, Trade, Wallet } from "@/lib/types";
import { cn } from "@/lib/utils";

interface Props {
  wallet: Wallet | undefined;
  trade: Trade | null | undefined;
  config: EngineConfig | undefined;
  onClose: (id: string) => void;
  closing: boolean;
}

export default function WalletPanel({ wallet, trade, config, onClose, closing }: Props) {
  const pnl = trade?.unrealized_pnl ?? 0;
  const long = trade?.direction === "BUY";

  return (
    <section
      className="col-span-12 space-y-4 rounded-md border border-slate-800 bg-[#111827] p-4 lg:col-span-4"
      data-testid="wallet-panel"
    >
      <div className="flex items-center justify-between">
        <h2 className="flex items-center gap-1.5 text-sm font-semibold text-slate-100">
          <WalletIcon className="size-4 text-amber-400" /> Paper Wallet
        </h2>
        <span className="rounded bg-slate-800 px-1.5 py-0.5 text-[10px] text-slate-400">
          virtual · {money(config?.starting_balance ?? 10000)} start
        </span>
      </div>

      <div className="grid grid-cols-2 gap-2">
        <Stat label="Equity" value={money(wallet?.equity)} testid="wallet-equity" accent="text-amber-300" />
        <Stat label="Balance" value={money(wallet?.balance)} testid="wallet-balance" />
        <Stat
          label="Realized P&L"
          value={money(wallet?.realized_pnl)}
          testid="wallet-realized-pnl"
          accent={(wallet?.realized_pnl ?? 0) >= 0 ? "text-emerald-400" : "text-rose-400"}
        />
        <Stat
          label="Unrealized"
          value={money(wallet?.unrealized_pnl)}
          testid="wallet-unrealized-pnl"
          accent={(wallet?.unrealized_pnl ?? 0) >= 0 ? "text-emerald-400" : "text-rose-400"}
        />
        <Stat
          label="Win rate"
          value={`${fmt(wallet?.win_rate ?? 0, 1)}%`}
          testid="wallet-win-rate"
          sub={`${wallet?.wins ?? 0}W / ${wallet?.losses ?? 0}L`}
        />
        <Stat
          label="Return"
          value={`${signed(wallet?.return_pct ?? 0, 2)}%`}
          testid="wallet-return-pct"
          accent={(wallet?.return_pct ?? 0) >= 0 ? "text-emerald-400" : "text-rose-400"}
          sub={`${wallet?.trades_count ?? 0} closed trades`}
        />
        <Stat
          label="Today's P&L"
          value={money(wallet?.day_pnl)}
          testid="wallet-day-pnl"
          accent={(wallet?.day_pnl ?? 0) >= 0 ? "text-emerald-400" : "text-rose-400"}
          sub={`limit ${fmt(config?.daily_loss_limit_pct ?? 3, 2)}%`}
        />
        <Stat
          label="Max hold"
          value={`${config?.max_hold_minutes ?? 15} min`}
          testid="wallet-max-hold"
          sub="auto-cut for scalps"
        />
      </div>

      <div className="border-t border-slate-800 pt-3">
        <h3 className="mb-2 text-[10px] uppercase tracking-wider text-slate-500">Active position</h3>

        {!trade ? (
          <div
            className="rounded border border-dashed border-slate-800 p-3 text-center"
            data-testid="no-active-trade"
          >
            <p className="text-[12px] text-slate-400">Flat — no open position</p>
            <p className="mt-1 text-[10px] leading-relaxed text-slate-600">
              The engine opens one trade at a time, only when confluence reaches{" "}
              {fmt(config?.confidence_threshold ?? 80, 0)}% and every risk gate passes.
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

            <div className="flex flex-wrap items-center gap-3 text-[10px] text-slate-400">
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
              <span className="rounded bg-slate-800 px-1.5 py-0.5">conf {fmt(trade.confidence, 1)}%</span>
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
      </div>
    </section>
  );
}

function Stat({
  label,
  value,
  testid,
  accent,
  sub,
}: {
  label: string;
  value: string;
  testid: string;
  accent?: string;
  sub?: string;
}) {
  return (
    <div className="rounded border border-slate-800 bg-slate-950/50 p-2.5">
      <div className="text-[10px] uppercase tracking-wider text-slate-500">{label}</div>
      <div className={cn("tabular-nums text-sm font-semibold text-slate-100", accent)} data-testid={testid}>
        {value}
      </div>
      {sub ? <div className="text-[10px] text-slate-600">{sub}</div> : null}
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

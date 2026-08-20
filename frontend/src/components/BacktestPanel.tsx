import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Area, AreaChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { FlaskConical, Loader2, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { apiGet } from "@/lib/api";
import { TIMEFRAMES, fmt, money, signed } from "@/lib/types";
import type { BacktestResult } from "@/lib/types";
import { cn } from "@/lib/utils";

const RANGES: { label: string; days: number }[] = [
  { label: "12h", days: 0.5 },
  { label: "1d", days: 1 },
  { label: "3d", days: 3 },
  { label: "7d", days: 7 },
];

export default function BacktestPanel() {
  const [timeframe, setTimeframe] = useState("5m");
  const [days, setDays] = useState(3);
  const [nonce, setNonce] = useState(0);

  const bt = useQuery({
    queryKey: ["backtest", timeframe, days, nonce],
    queryFn: () =>
      apiGet<BacktestResult>(
        `/backtest?timeframe=${timeframe}&days=${days}${nonce ? "&refresh=true" : ""}`,
      ),
    retry: false,
    staleTime: 120_000,
  });

  const r = bt.data;
  const curve = (r?.equity_curve ?? []).map((p) => ({
    t: new Date(p.time).toLocaleString("en-GB", { day: "2-digit", hour: "2-digit", minute: "2-digit" }),
    equity: p.equity,
  }));
  const positive = (r?.net_pnl ?? 0) >= 0;

  return (
    <section
      className="col-span-12 space-y-3 rounded-md border border-slate-800 bg-[#111827] p-4"
      data-testid="backtest-panel"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h2 className="flex items-center gap-1.5 text-sm font-semibold text-slate-100">
            <FlaskConical className="size-4 text-amber-400" /> Strategy backtest
          </h2>
          <p className="text-[11px] text-slate-500">
            The live scalping rules replayed over real Binance gold candles
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-1">
          <div className="flex items-center gap-1" data-testid="backtest-timeframes">
            {TIMEFRAMES.map((tf) => (
              <button
                key={tf}
                type="button"
                onClick={() => setTimeframe(tf)}
                data-testid={`backtest-tf-${tf}`}
                className={cn(
                  "rounded px-2 py-1 text-[11px] transition-colors duration-150",
                  timeframe === tf ? "bg-amber-500 text-slate-900" : "text-slate-400 hover:bg-slate-800",
                )}
              >
                {tf}
              </button>
            ))}
          </div>
          <span className="mx-1 h-4 w-px bg-slate-800" />
          <div className="flex items-center gap-1" data-testid="backtest-ranges">
            {RANGES.map((range) => (
              <button
                key={range.label}
                type="button"
                onClick={() => setDays(range.days)}
                data-testid={`backtest-range-${range.label}`}
                className={cn(
                  "rounded px-2 py-1 text-[11px] transition-colors duration-150",
                  days === range.days ? "bg-slate-700 text-slate-100" : "text-slate-400 hover:bg-slate-800",
                )}
              >
                {range.label}
              </button>
            ))}
          </div>
          <Button
            variant="outline"
            size="sm"
            onClick={() => setNonce((n) => n + 1)}
            disabled={bt.isFetching}
            data-testid="backtest-refresh-button"
            className="border-slate-700 text-slate-300"
          >
            {bt.isFetching ? <Loader2 className="size-3.5 animate-spin" /> : <RefreshCw className="size-3.5" />}
            Run
          </Button>
        </div>
      </div>

      {bt.isLoading ? (
        <p className="flex items-center gap-2 text-[12px] text-slate-400" data-testid="backtest-loading">
          <Loader2 className="size-4 animate-spin" /> Replaying {days === 0.5 ? "12 hours" : `${days} days`} of{" "}
          {timeframe} candles…
        </p>
      ) : bt.isError ? (
        <p className="text-[12px] text-rose-300" data-testid="backtest-error">
          Not enough market history to backtest this window yet. Try a higher timeframe or a shorter range.
        </p>
      ) : (
        <>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 lg:grid-cols-8" data-testid="backtest-stats">
            {[
              ["Trades", `${r?.trades ?? 0}`, ""],
              ["Win rate", `${fmt(r?.win_rate ?? 0, 1)}%`, ""],
              ["Net P&L", money(r?.net_pnl), positive ? "text-emerald-400" : "text-rose-400"],
              ["Return", `${signed(r?.return_pct ?? 0, 2)}%`, positive ? "text-emerald-400" : "text-rose-400"],
              ["Profit factor", `${fmt(r?.profit_factor ?? 0, 2)}`, ""],
              ["Avg R", `${signed(r?.avg_r ?? 0, 2)}`, ""],
              ["Max drawdown", `${fmt(r?.max_drawdown_pct ?? 0, 2)}%`, "text-rose-300"],
              ["Avg hold", `${fmt(r?.avg_hold_minutes ?? 0, 0)} min`, ""],
            ].map(([label, value, tone]) => (
              <div key={label} className="rounded border border-slate-800 bg-slate-950/50 p-2">
                <div className="text-[10px] uppercase tracking-wider text-slate-500">{label}</div>
                <div className={cn("tabular-nums text-sm font-semibold text-slate-100", tone)}>{value}</div>
              </div>
            ))}
          </div>

          {curve.length > 1 ? (
            <div className="h-[190px]" data-testid="backtest-equity-curve">
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={curve} margin={{ top: 6, right: 8, left: 0, bottom: 0 }}>
                  <defs>
                    <linearGradient id="eq" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor={positive ? "#10b981" : "#f43f5e"} stopOpacity={0.45} />
                      <stop offset="100%" stopColor={positive ? "#10b981" : "#f43f5e"} stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <XAxis dataKey="t" tick={{ fill: "#64748b", fontSize: 9 }} stroke="#1e293b" minTickGap={50} />
                  <YAxis
                    domain={["dataMin - 20", "dataMax + 20"]}
                    tick={{ fill: "#94a3b8", fontSize: 9 }}
                    stroke="#1e293b"
                    width={64}
                    tickFormatter={(v: number) => v.toFixed(0)}
                  />
                  <Tooltip
                    contentStyle={{ background: "rgba(2,6,23,0.94)", border: "1px solid #1e293b", borderRadius: 6, fontSize: 11 }}
                    labelStyle={{ color: "#94a3b8" }}
                  />
                  <Area
                    type="monotone"
                    dataKey="equity"
                    stroke={positive ? "#10b981" : "#f43f5e"}
                    strokeWidth={1.6}
                    fill="url(#eq)"
                  />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          ) : null}

          {Object.keys(r?.exit_reasons ?? {}).length ? (
            <div className="flex flex-wrap gap-1.5" data-testid="backtest-exit-reasons">
              {Object.entries(r?.exit_reasons ?? {}).map(([reason, count]) => (
                <span key={reason} className="rounded border border-slate-800 bg-slate-950/50 px-2 py-0.5 text-[10px] text-slate-400">
                  {reason}: <span className="text-slate-200">{count}</span>
                </span>
              ))}
            </div>
          ) : null}

          {(r?.trade_list ?? []).length ? (
            <div className="max-h-[210px] overflow-y-auto rounded border border-slate-800" data-testid="backtest-trades">
              <table className="w-full text-[10px]">
                <thead className="sticky top-0 bg-slate-900/95">
                  <tr>
                    {["Time", "Side", "Entry", "Exit", "P&L", "R", "Conf", "Held", "Reason"].map((h) => (
                      <th key={h} className="px-2 py-1 text-left font-medium uppercase tracking-wider text-slate-500">{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {(r?.trade_list ?? []).map((t) => (
                    <tr key={`${t.time}-${t.entry}`} className="border-t border-slate-800/70" data-testid="backtest-trade-row">
                      <td className="px-2 py-1 text-slate-500">
                        {new Date(t.time).toLocaleString("en-GB", { day: "2-digit", hour: "2-digit", minute: "2-digit" })}
                      </td>
                      <td className={cn("px-2 py-1 font-semibold", t.direction === "BUY" ? "text-emerald-400" : "text-rose-400")}>{t.direction}</td>
                      <td className="px-2 py-1 tabular-nums text-slate-300">{fmt(t.entry)}</td>
                      <td className="px-2 py-1 tabular-nums text-slate-300">{fmt(t.exit)}</td>
                      <td className={cn("px-2 py-1 tabular-nums font-semibold", t.pnl >= 0 ? "text-emerald-400" : "text-rose-400")}>{money(t.pnl)}</td>
                      <td className="px-2 py-1 tabular-nums text-slate-400">{signed(t.r_multiple, 2)}</td>
                      <td className="px-2 py-1 tabular-nums text-slate-500">{fmt(t.confidence, 0)}%</td>
                      <td className="px-2 py-1 text-slate-500">{t.hold_minutes}m</td>
                      <td className="px-2 py-1 text-slate-400">{t.exit_reason}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}

          <p className="text-[10px] leading-relaxed text-slate-500" data-testid="backtest-note">
            {r?.note} Tested {r?.bars_tested ?? 0} bars on {r?.timeframe || timeframe} from a{" "}
            {money(r?.starting_equity ?? 10000)} start.
          </p>
        </>
      )}
    </section>
  );
}

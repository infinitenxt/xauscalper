import { useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import { Activity, Circle, Coins, RotateCcw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { TIMEFRAMES, fmt, money } from "@/lib/types";
import type { FeedStatus, Ticker } from "@/lib/types";
import { cn } from "@/lib/utils";

interface Props {
  ticker: Ticker | undefined;
  feed: FeedStatus | undefined;
  equity: number | undefined;
  dayPnl: number | undefined;
  timeframe: string;
  onTimeframe: (tf: string) => void;
  onReset: () => void;
  resetting: boolean;
  live: boolean;
  autoTradeOn: boolean;
  settingsSlot: ReactNode;
  userSlot: ReactNode;
}

export default function TickerBar({
  ticker,
  feed,
  equity,
  dayPnl,
  timeframe,
  onTimeframe,
  onReset,
  resetting,
  live,
  autoTradeOn,
  settingsSlot,
  userSlot,
}: Props) {
  const price = ticker?.price ?? null;
  const prev = useRef<number | null>(null);
  const [dir, setDir] = useState<"up" | "down" | null>(null);

  useEffect(() => {
    if (price === null) return;
    if (prev.current !== null && price !== prev.current) {
      setDir(price > prev.current ? "up" : "down");
      const t = setTimeout(() => setDir(null), 600);
      prev.current = price;
      return () => clearTimeout(t);
    }
    prev.current = price;
  }, [price]);

  const chg = ticker?.change_pct_24h ?? null;
  const up = (chg ?? 0) >= 0;

  return (
    <header
      className="col-span-12 rounded-md border border-slate-800 bg-[#111827]"
      data-testid="ticker-bar"
    >
      <div className="flex flex-wrap items-center gap-x-6 gap-y-3 px-4 py-3">
        <div className="flex items-center gap-3">
          <div className="flex size-9 items-center justify-center rounded border border-amber-500/30 bg-amber-500/10">
            <Coins className="size-5 text-amber-400" />
          </div>
          <div className="leading-tight">
            <div className="flex items-center gap-2">
              <span
                className="text-sm font-semibold tracking-tight text-slate-100"
                data-testid="ticker-symbol"
              >
                {feed?.display_symbol ?? ticker?.symbol ?? "BTCUSDT"}
              </span>
              <span className="rounded bg-amber-950 px-1.5 py-0.5 text-[10px] font-semibold text-amber-200">
                PAPER
              </span>
            </div>
            <span className="text-[11px] text-slate-500" data-testid="ticker-market-description">
              {feed?.is_proxy ? "Gold proxy / USDT · Binance" : "Gold / USDT · Binance"}
            </span>
          </div>
        </div>

        <div className="flex items-baseline gap-3">
          <span
            className={cn(
              "rounded px-1 text-2xl font-semibold tabular-nums transition-colors duration-150",
              dir === "up" && "text-emerald-400 animate-tick-flash",
              dir === "down" && "text-rose-400 animate-tick-flash",
              dir === null && "text-slate-100",
            )}
            data-testid="live-price-ticker"
          >
            {price === null ? "—" : fmt(price, 2)}
          </span>
          <span
            className={cn("text-sm tabular-nums", up ? "text-emerald-400" : "text-rose-400")}
            data-testid="price-change-24h"
          >
            {chg === null ? "—" : `${up ? "+" : ""}${fmt(chg, 2)}%`}
          </span>
        </div>

        <dl className="hidden gap-5 text-[11px] md:flex">
          {[
            ["24h High", fmt(ticker?.high_24h ?? null, 2)],
            ["24h Low", fmt(ticker?.low_24h ?? null, 2)],
            ["24h Vol", fmt(ticker?.volume_24h ?? null, 0)],
          ].map(([k, v]) => (
            <div key={k} className="leading-tight">
              <dt className="text-slate-500 uppercase tracking-wider">{k}</dt>
              <dd className="tabular-nums text-slate-300">{v}</dd>
            </div>
          ))}
        </dl>

        <div className="ml-auto flex items-center gap-4">
          <div className="text-right leading-tight">
            <div className="text-[10px] uppercase tracking-wider text-slate-500">Equity</div>
            <div className="tabular-nums text-sm font-semibold text-amber-300" data-testid="header-equity">
              {money(equity)}
            </div>
          </div>

          <div className="hidden text-right leading-tight sm:block">
            <div className="text-[10px] uppercase tracking-wider text-slate-500">Today</div>
            <div
              className={cn(
                "tabular-nums text-sm font-semibold",
                (dayPnl ?? 0) >= 0 ? "text-emerald-400" : "text-rose-400",
              )}
              data-testid="header-day-pnl"
            >
              {money(dayPnl)}
            </div>
          </div>

          <span
            className={cn(
              "rounded px-1.5 py-0.5 text-[10px] font-semibold",
              autoTradeOn ? "bg-emerald-950 text-emerald-300" : "bg-rose-950 text-rose-300",
            )}
            data-testid="header-auto-trade-state"
          >
            AUTO {autoTradeOn ? "ON" : "OFF"}
          </span>

          <div className="flex items-center gap-1.5 rounded border border-slate-800 bg-slate-950/60 px-2 py-1">
            <Circle
              className={cn(
                "size-2 fill-current",
                live ? "animate-pulse-dot text-emerald-400" : "text-rose-500",
              )}
            />
            <span className="text-[10px] text-slate-400" data-testid="feed-status">
              {feed?.provider_label ?? (live ? "live" : "offline")}
            </span>
            {feed ? (
              <span
                data-testid="feed-live-source"
                className={cn(
                  "rounded px-1 py-0.5 text-[9px] font-semibold uppercase",
                  feed.stale
                    ? "bg-rose-950 text-rose-300"
                    : feed.live_source === "websocket"
                      ? "bg-emerald-950 text-emerald-300"
                      : "bg-slate-800 text-slate-400",
                )}
                title={
                  feed.stale
                    ? "No fresh tick — price shown is not live"
                    : `${feed.live_source} feed · tick ${feed.tick_age_seconds ?? 0}s old`
                }
              >
                {feed.stale ? "stale" : feed.live_source === "websocket" ? "ws live" : "rest"}
              </span>
            ) : null}
            {feed?.is_proxy ? (
              <span
                className="rounded bg-amber-950 px-1 py-0.5 text-[9px] font-semibold uppercase text-amber-300"
                data-testid="feed-proxy-badge"
                title="Not BTC/USD — PAXGUSDT gold proxy data"
              >
                gold proxy
              </span>
            ) : null}
          </div>

          <div className="flex items-center gap-1" data-testid="timeframe-switcher">
            <Activity className="mr-1 size-3.5 text-slate-500" />
            {TIMEFRAMES.map((tf) => (
              <button
                key={tf}
                type="button"
                onClick={() => onTimeframe(tf)}
                data-testid={`timeframe-${tf}-button`}
                className={cn(
                  "rounded px-2 py-1 text-[11px] font-medium transition-colors duration-150 focus:ring-2 focus:ring-amber-500 focus:outline-none",
                  timeframe === tf
                    ? "bg-amber-500 text-slate-900"
                    : "text-slate-400 hover:bg-slate-800 hover:text-slate-100",
                )}
              >
                {tf}
              </button>
            ))}
          </div>

          <Button
            variant="outline"
            size="sm"
            onClick={onReset}
            disabled={resetting}
            data-testid="reset-account-button"
            className="border-slate-700 text-slate-300 transition-colors duration-150 hover:text-amber-300"
          >
            <RotateCcw className="size-3.5" />
            Reset
          </Button>

          {settingsSlot}
          {userSlot}
        </div>
      </div>

      {feed?.degraded && feed.note ? (
        <p
          className="border-t border-amber-900/50 bg-amber-950/30 px-4 py-1.5 text-[11px] text-amber-200/90"
          data-testid="feed-degraded-note"
        >
          {feed.note}
        </p>
      ) : null}
    </header>
  );
}

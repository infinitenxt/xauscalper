import { Activity, Ban, CircleAlert, Minus, Radio, ShieldCheck, TrendingDown, TrendingUp, Volume2, VolumeX } from "lucide-react";
import { Button } from "@/components/ui/button";
import { fmt } from "@/lib/types";
import type { Guards, Signal } from "@/lib/types";
import { cn } from "@/lib/utils";

interface Props {
  signal: Signal | undefined;
  guards: Guards | undefined;
  threshold: number;
  speechOn: boolean;
  onToggleSpeech: () => void;
  onReadAnalysis: () => void;
  lastComment: string;
}

const SKIN = {
  BUY: {
    Icon: TrendingUp,
    word: "BUY",
    frame: "border-emerald-500/60 bg-gradient-to-r from-emerald-950 via-emerald-900/40 to-[#111827]",
    text: "text-emerald-300",
    glow: "shadow-[0_0_40px_-12px_rgba(16,185,129,0.7)]",
    bar: "bg-emerald-500",
  },
  SELL: {
    Icon: TrendingDown,
    word: "SELL",
    frame: "border-rose-500/60 bg-gradient-to-r from-rose-950 via-rose-900/40 to-[#111827]",
    text: "text-rose-300",
    glow: "shadow-[0_0_40px_-12px_rgba(244,63,94,0.7)]",
    bar: "bg-rose-500",
  },
  WAIT: {
    Icon: Minus,
    word: "WAIT",
    frame: "border-slate-700 bg-gradient-to-r from-slate-900 via-slate-900/60 to-[#111827]",
    text: "text-slate-300",
    glow: "",
    bar: "bg-slate-600",
  },
} as const;

export default function SignalBanner({
  signal,
  guards,
  threshold,
  speechOn,
  onToggleSpeech,
  onReadAnalysis,
  lastComment,
}: Props) {
  const dir = (signal?.direction ?? "WAIT") as keyof typeof SKIN;
  const skin = SKIN[dir] ?? SKIN.WAIT;
  const conf = signal?.confidence ?? 0;
  const armed = (signal?.tradeable ?? false) && !(guards?.blocked ?? false);
  const blockedBy = guards?.blocked ? guards.block_reason : "";

  return (
    <section
      className={cn(
        "col-span-12 rounded-md border p-3 transition-colors duration-300 lg:col-span-7",
        skin.frame,
        armed && skin.glow,
      )}
      data-testid="signal-banner"
    >
      <div className="flex flex-wrap items-center gap-x-6 gap-y-2">
        <div className="flex items-center gap-2.5">
          <skin.Icon className={cn("size-7 shrink-0", skin.text)} strokeWidth={2.4} />
          <div className="leading-none">
            <div
              className={cn("text-3xl font-bold tracking-tight sm:text-4xl", skin.text)}
              data-testid="signal-banner-direction"
            >
              {skin.word}
            </div>
            <div className="mt-1 flex items-center gap-1.5 text-[10px] uppercase tracking-[0.18em] text-slate-400">
              <span>{signal?.broker_symbol || signal?.symbol || "BTCUSDT"} · {signal?.timeframe ?? "—"}</span>
              <span className={cn("rounded border px-1 py-0.5 text-[8px]", signal?.data_source === "broker" ? "border-sky-800 bg-sky-950/70 text-sky-300" : "border-slate-700 bg-slate-900 text-slate-400")} data-testid="signal-data-source">
                {signal?.data_source === "broker" ? "BROKER FEED" : "PUBLIC FEED"}
              </span>
            </div>
          </div>
        </div>

        <div className="min-w-[200px] flex-1">
          <div className="flex items-end justify-between">
            <span className="text-[10px] uppercase tracking-wider text-slate-400">Confidence</span>
            <span
              className={cn("text-2xl font-bold tabular-nums", skin.text)}
              data-testid="signal-banner-confidence"
            >
              {fmt(conf, 1)}%
            </span>
          </div>
          <div className="relative mt-1.5 h-2 overflow-hidden rounded-full bg-slate-800/80">
            <div
              className={cn("h-full rounded-full transition-[width] duration-500", skin.bar)}
              style={{ width: `${Math.min(100, Math.max(0, conf))}%` }}
            />
            <div
              className="absolute top-0 h-full w-0.5 bg-amber-400"
              style={{ left: `${threshold}%` }}
              title={`auto-trade threshold ${threshold}%`}
            />
          </div>
          <div className="mt-1 flex justify-between text-[10px] text-slate-500">
            <span>
              bull {fmt(signal?.bull_score ?? 0, 1)} / bear {fmt(signal?.bear_score ?? 0, 1)}
            </span>
            <span>auto-trade at {threshold}%</span>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <span
            className={cn(
              "flex items-center gap-1.5 rounded border px-2 py-1 text-[10px] font-semibold",
              armed
                ? "border-emerald-600 bg-emerald-950 text-emerald-300"
                : "border-slate-700 bg-slate-900 text-slate-400",
            )}
            data-testid="signal-banner-armed"
          >
            {armed ? <ShieldCheck className="size-3" /> : <Ban className="size-3" />}
            {armed ? "ARMED" : "HOLDING FIRE"}
          </span>
          <Button
            variant="outline"
            size="sm"
            onClick={onToggleSpeech}
            data-testid="speech-toggle-button"
            className={cn(
              "border-slate-700 transition-colors duration-150",
              speechOn ? "text-emerald-300" : "text-slate-400",
            )}
          >
            {speechOn ? <Volume2 className="size-3.5" /> : <VolumeX className="size-3.5" />}
            {speechOn ? "Voice on" : "Voice off"}
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={onReadAnalysis}
            data-testid="read-analysis-button"
            className="border-slate-700 text-slate-300 transition-colors duration-150 hover:text-amber-300"
          >
            Read analysis
          </Button>
        </div>
      </div>

      <p
        className="mt-2 border-t border-white/5 pt-2 text-[11px] leading-relaxed text-slate-300"
        data-testid="signal-banner-summary"
      >
        {signal?.summary ?? "Waiting for the first evaluation cycle…"}
        {blockedBy ? (
          <span className="ml-1 text-amber-300" data-testid="signal-banner-blocked">
            Account guard blocking new entries: {blockedBy}.
          </span>
        ) : null}
      </p>

      <OrderBookStrip signal={signal} />

      {lastComment ? (
        <p
          className="mt-1.5 flex items-center gap-1.5 text-[11px] italic text-slate-400"
          data-testid="live-commentary"
        >
          <Radio className="size-3 shrink-0 text-amber-400" />
          {lastComment}
        </p>
      ) : null}
    </section>
  );
}

function OrderBookStrip({ signal }: { signal: Signal | undefined }) {
  const book = signal?.order_book;
  const captured = book?.captured_at ? new Date(book.captured_at).getTime() : 0;
  const stale = !book || book.stale || !captured || Date.now() - captured > 5_000;
  if (stale) {
    return (
      <div className="mt-2 flex items-center justify-between rounded border border-slate-800/60 bg-slate-950/40 px-2.5 py-1.5 text-[11px] text-slate-500" data-testid="orderbook-depth-unavailable">
        <span className="flex items-center gap-1.5"><CircleAlert className="size-3" /> Depth unavailable</span>
        <span className="text-[9px] uppercase tracking-[0.18em]">Candle signal unchanged</span>
      </div>
    );
  }

  const imbalance = book.imbalance;
  const near = book.near_imbalance;
  const spread = book.spread_bps ?? 0;
  const pressureTone = imbalance > 0.05 ? "text-emerald-400" : imbalance < -0.05 ? "text-rose-400" : "text-slate-300";
  const spreadTone = spread < 1.5 ? "text-emerald-400" : spread > 3.5 ? "text-amber-400" : "text-slate-300";
  const nearLabel = near > 0.05 ? "BULLISH BIAS" : near < -0.05 ? "BEARISH BIAS" : "NEUTRAL";
  const nearTone = near > 0.05 ? "border-emerald-800/60 bg-emerald-950/80 text-emerald-300" : near < -0.05 ? "border-rose-800/60 bg-rose-950/80 text-rose-300" : "border-slate-800 bg-slate-900 text-slate-400";
  const pressureWidth = `${Math.min(50, Math.abs(imbalance) * 50)}%`;

  return (
    <div className="mt-2 grid grid-cols-3 gap-2 rounded border border-slate-800/80 bg-slate-950/70 p-2 text-[11px]" data-testid="orderbook-metric-strip">
      <div aria-label="Order book imbalance" data-testid="metric-ob-imbalance">
        <div className="text-[9px] uppercase tracking-[0.18em] text-slate-500">OB imbalance</div>
        <div className={cn("mt-0.5 font-semibold tabular-nums", pressureTone)}>{imbalance >= 0 ? "+" : ""}{fmt(imbalance * 100, 1)}%</div>
        <div className="relative mt-1 h-1 overflow-hidden rounded bg-slate-800">
          <span className="absolute left-1/2 top-0 h-full w-px bg-slate-500" />
          <span className={cn("absolute top-0 h-full transition-[width] duration-150", imbalance >= 0 ? "left-1/2 bg-emerald-500" : "right-1/2 bg-rose-500")} style={{ width: pressureWidth }} />
        </div>
      </div>
      <div aria-label="Spread in basis points" data-testid="metric-spread-bps">
        <div className="text-[9px] uppercase tracking-[0.18em] text-slate-500">Spread</div>
        <div className={cn("mt-0.5 font-semibold tabular-nums", spreadTone)}>{fmt(spread, 2)} bps</div>
        <div className="mt-1 text-[9px] text-slate-600">{spread < 1.5 ? "TIGHT" : spread > 3.5 ? "WIDE" : "NORMAL"}</div>
      </div>
      <div aria-label="Near-mid liquidity bias" data-testid="metric-liquidity-bias">
        <div className="text-[9px] uppercase tracking-[0.18em] text-slate-500">Near-mid bias</div>
        <div className={cn("mt-0.5 inline-flex items-center gap-1 rounded border px-1.5 py-0.5 text-[9px] font-semibold", nearTone)}>
          {near > 0.05 ? <TrendingUp className="size-3" /> : near < -0.05 ? <TrendingDown className="size-3" /> : <Activity className="size-3" />}
          {nearLabel}
        </div>
        <div className="mt-1 text-[9px] tabular-nums text-slate-600">{near >= 0 ? "+" : ""}{fmt(near * 100, 1)}%</div>
      </div>
    </div>
  );
}

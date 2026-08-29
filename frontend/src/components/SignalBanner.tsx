import { Ban, Minus, Radio, ShieldCheck, TrendingDown, TrendingUp, Volume2, VolumeX } from "lucide-react";
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
            <div className="mt-1 text-[10px] uppercase tracking-[0.18em] text-slate-400">
              BTCUSDT · {signal?.timeframe ?? "—"} scalp signal
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

import { Check, ChevronDown, Minus, ShieldAlert, TrendingDown, TrendingUp, X } from "lucide-react";
import { useState } from "react";
import { fmt } from "@/lib/types";
import type { Signal } from "@/lib/types";
import { cn } from "@/lib/utils";

const TONE: Record<string, { text: string; bg: string; ring: string; Icon: typeof TrendingUp }> = {
  BUY: { text: "text-emerald-300", bg: "bg-emerald-950/70", ring: "border-emerald-700/60", Icon: TrendingUp },
  SELL: { text: "text-rose-300", bg: "bg-rose-950/70", ring: "border-rose-800/60", Icon: TrendingDown },
  WAIT: { text: "text-slate-300", bg: "bg-slate-900", ring: "border-slate-700", Icon: Minus },
};

export default function SignalPanel({
  signal,
  threshold,
  stale,
}: {
  signal: Signal | undefined;
  threshold: number;
  stale: boolean;
}) {
  const [open, setOpen] = useState(true);
  const dir = signal?.direction ?? "WAIT";
  const tone = TONE[dir] ?? TONE.WAIT;
  const conf = signal?.confidence ?? 0;
  const barColor = dir === "BUY" ? "bg-emerald-500" : dir === "SELL" ? "bg-rose-500" : "bg-slate-600";

  return (
    <section
      className="col-span-12 space-y-4 rounded-md border border-slate-800 bg-[#111827] p-4 lg:col-span-4"
      data-testid="signal-panel"
    >
      <div className="flex items-start justify-between">
        <div>
          <h2 className="text-sm font-semibold text-slate-100">Signal Engine</h2>
          <p className="text-[11px] text-slate-500">
            12 weighted confirmations · {signal?.timeframe ?? "—"} timeframe
          </p>
        </div>
        <span
          className={cn(
            "flex items-center gap-1.5 rounded border px-2.5 py-1 text-xs font-semibold",
            tone.bg,
            tone.ring,
            tone.text,
          )}
          data-testid="signal-direction"
        >
          <tone.Icon className="size-3.5" />
          {dir}
        </span>
      </div>

      <div>
        <div className="mb-1.5 flex items-baseline justify-between">
          <span className="text-[10px] uppercase tracking-wider text-slate-500">Confidence</span>
          <span className={cn("tabular-nums text-lg font-semibold", tone.text)} data-testid="signal-confidence-score">
            {fmt(conf, 1)}%
          </span>
        </div>
        <div className="relative h-2 overflow-hidden rounded-full bg-slate-800">
          <div
            className={cn("h-full rounded-full transition-[width] duration-500", barColor)}
            style={{ width: `${Math.min(100, Math.max(0, conf))}%` }}
            data-testid="signal-confidence-bar"
          />
          <div
            className="absolute top-0 h-full w-px bg-amber-400"
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

      <div className="flex flex-wrap gap-1.5 text-[10px]" data-testid="market-read-chips">
        <span className="rounded border border-slate-800 bg-slate-950/60 px-1.5 py-0.5 text-slate-300" data-testid="read-structure">
          structure: <span className="text-slate-100">{signal?.structure?.label ?? "—"}</span>
        </span>
        <span
          className={cn(
            "rounded border px-1.5 py-0.5",
            signal?.breakout?.fake
              ? "border-rose-900/60 bg-rose-950/40 text-rose-300"
              : signal?.breakout?.chop
                ? "border-amber-900/50 bg-amber-950/30 text-amber-200"
                : "border-slate-800 bg-slate-950/60 text-slate-300",
          )}
          data-testid="read-breakout"
          title={signal?.breakout?.detail ?? ""}
        >
          range: <span className="text-slate-100">{signal?.breakout?.label ?? "—"}</span>
          {signal?.breakout?.quality ? ` · q ${((signal.breakout?.quality ?? 0) * 100).toFixed(0)}%` : ""}
        </span>
        <span className="rounded border border-slate-800 bg-slate-950/60 px-1.5 py-0.5 text-slate-300" data-testid="read-pattern">
          candle: <span className="text-slate-100">{signal?.pattern?.label ?? "—"}</span>
        </span>
      </div>

      <p className="rounded border border-slate-800 bg-slate-950/60 p-2.5 text-[11px] leading-relaxed text-slate-300" data-testid="signal-summary">
        {stale
          ? "Live signal feed unavailable — showing nothing rather than a stale read."
          : (signal?.summary ?? "Waiting for the first evaluation cycle…")}
      </p>

      <div className="grid grid-cols-3 gap-2 text-[11px]">
        {[
          ["SL", signal?.sl ?? null, "text-rose-300"],
          ["TP", signal?.tp ?? null, "text-emerald-300"],
          ["R:R", signal?.rr ?? null, "text-sky-300"],
        ].map(([label, value, color]) => (
          <div key={String(label)} className="rounded border border-slate-800 bg-slate-950/50 p-2">
            <div className="text-[10px] uppercase tracking-wider text-slate-500">{String(label)}</div>
            <div className={cn("tabular-nums", String(color))} data-testid={`signal-plan-${String(label).toLowerCase()}`}>
              {fmt(value as number | null, label === "R:R" ? 2 : 2)}
            </div>
          </div>
        ))}
      </div>

      <div className="space-y-1.5" data-testid="risk-checks">
        <h3 className="flex items-center gap-1.5 text-[10px] uppercase tracking-wider text-slate-500">
          <ShieldAlert className="size-3" /> Risk gates
        </h3>
        {(signal?.risk_checks ?? []).map((c) => (
          <div
            key={c.name}
            className="flex items-start gap-2 text-[11px]"
            data-testid={`risk-check-${c.name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "")}`}
          >
            {c.passed ? (
              <Check className="mt-0.5 size-3 shrink-0 text-emerald-400" />
            ) : (
              <X className="mt-0.5 size-3 shrink-0 text-rose-400" />
            )}
            <span className={c.passed ? "text-slate-300" : "text-slate-500"}>
              <span className="font-medium">{c.name}</span> — {c.detail}
            </span>
          </div>
        ))}
      </div>

      <div>
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          data-testid="confirmations-toggle"
          className="flex w-full items-center justify-between rounded border border-slate-800 bg-slate-950/50 px-2.5 py-1.5 text-[11px] text-slate-300 transition-colors duration-150 hover:border-slate-700 hover:text-amber-300 focus:ring-2 focus:ring-amber-500 focus:outline-none"
        >
          <span>Confirmation breakdown ({(signal?.confirmations ?? []).length})</span>
          <ChevronDown className={cn("size-3.5 transition-transform duration-150", open && "rotate-180")} />
        </button>
        {open ? (
          <ul className="mt-2 space-y-1.5" data-testid="confirmation-list">
            {(signal?.confirmations ?? []).map((c) => {
              const bull = c.direction === "BULLISH";
              const neutral = c.direction === "NEUTRAL";
              return (
                <li
                  key={c.name}
                  className="animate-rise-in rounded border border-slate-800 bg-slate-950/40 p-2"
                  data-testid={`confirmation-${c.name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "")}`}
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-[11px] font-medium text-slate-200">{c.name}</span>
                    <span
                      className={cn(
                        "rounded px-1.5 py-0.5 text-[9px] font-semibold",
                        neutral
                          ? "bg-slate-800 text-slate-400"
                          : bull
                            ? "bg-emerald-950 text-emerald-300"
                            : "bg-rose-950 text-rose-300",
                      )}
                    >
                      {c.direction} · w{c.weight}
                    </span>
                  </div>
                  <div className="mt-0.5 text-[10px] tabular-nums text-slate-400">{c.state}</div>
                  <p className="mt-1 text-[10px] leading-relaxed text-slate-500">{c.detail}</p>
                </li>
              );
            })}
          </ul>
        ) : null}
      </div>

      {(signal?.level_reasons ?? []).length > 0 ? (
        <div className="space-y-1" data-testid="sltp-rationale">
          <h3 className="text-[10px] uppercase tracking-wider text-slate-500">Why these SL / TP</h3>
          {signal?.level_reasons.map((r) => (
            <p key={r} className="text-[10px] leading-relaxed text-slate-400">
              · {r}
            </p>
          ))}
        </div>
      ) : null}
    </section>
  );
}

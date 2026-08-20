import { Clock, Globe2 } from "lucide-react";
import type { SessionSnapshot } from "@/lib/types";
import { cn } from "@/lib/utils";

const TONE: Record<string, { chip: string; text: string }> = {
  PEAK: { chip: "bg-emerald-950 border-emerald-700/60", text: "text-emerald-300" },
  HIGH: { chip: "bg-sky-950 border-sky-700/60", text: "text-sky-300" },
  MEDIUM: { chip: "bg-amber-950 border-amber-800/60", text: "text-amber-300" },
  LOW: { chip: "bg-rose-950 border-rose-800/60", text: "text-rose-300" },
};

function hm(minutes: number): string {
  if (minutes <= 0) return "now";
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  return h > 0 ? `${h}h ${m}m` : `${m}m`;
}

export default function SessionBar({
  sessions,
  filterOn,
}: {
  sessions: SessionSnapshot | undefined;
  filterOn: boolean;
}) {
  const liq = sessions?.liquidity ?? "LOW";
  const tone = TONE[liq] ?? TONE.LOW;

  return (
    <section
      className="col-span-12 rounded-md border border-slate-800 bg-[#111827] p-3"
      data-testid="session-bar"
    >
      <div className="flex flex-wrap items-center gap-x-5 gap-y-2">
        <div className="flex items-center gap-2">
          <Globe2 className="size-4 text-amber-400" />
          <h2 className="text-[12px] font-semibold text-slate-100">Trading sessions</h2>
          <span className="flex items-center gap-1 text-[10px] text-slate-500">
            <Clock className="size-3" />
            {sessions?.utc_time ?? "--:--"} UTC
          </span>
        </div>

        <div className="flex flex-wrap items-center gap-1.5" data-testid="session-chips">
          {(sessions?.sessions ?? []).map((s) => (
            <span
              key={s.name}
              data-testid={`session-chip-${s.name.toLowerCase().replace(/\s+/g, "-")}`}
              title={`${s.open_utc}–${s.close_utc} UTC`}
              className={cn(
                "rounded border px-2 py-1 text-[10px] transition-colors duration-200",
                s.active
                  ? "border-emerald-700/60 bg-emerald-950/70 text-emerald-300"
                  : "border-slate-800 bg-slate-950/60 text-slate-500",
              )}
            >
              <span className="font-semibold">{s.name}</span>{" "}
              {s.active ? `closes in ${hm(s.minutes_to_close)}` : `opens in ${hm(s.minutes_to_open)}`}
            </span>
          ))}
        </div>

        <div className="ml-auto flex items-center gap-2">
          {sessions?.overlap_active ? (
            <span className="rounded border border-emerald-700/60 bg-emerald-950/70 px-2 py-1 text-[10px] font-semibold text-emerald-300" data-testid="session-overlap">
              LONDON × NEW YORK OVERLAP
            </span>
          ) : sessions ? (
            <span className="text-[10px] text-slate-500" data-testid="session-next-overlap">
              overlap in {hm(sessions.minutes_to_overlap)}
            </span>
          ) : null}
          <span
            className={cn("rounded border px-2 py-1 text-[10px] font-semibold", tone.chip, tone.text)}
            data-testid="session-liquidity"
          >
            {liq} LIQUIDITY
          </span>
          <span
            className={cn(
              "rounded px-1.5 py-0.5 text-[10px]",
              filterOn ? "bg-slate-800 text-slate-300" : "bg-slate-900 text-slate-500",
            )}
            data-testid="session-filter-state"
          >
            filter {filterOn ? "ON" : "OFF"}
          </span>
        </div>
      </div>

      <p className="mt-2 text-[11px] leading-relaxed text-slate-400" data-testid="session-note">
        {sessions?.note ?? "Loading session clock…"}
        {filterOn && sessions && !sessions.tradeable
          ? " The engine is standing down until a major session opens."
          : ""}
      </p>
    </section>
  );
}

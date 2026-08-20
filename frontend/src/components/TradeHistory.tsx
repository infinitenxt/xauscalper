import { Fragment, useState } from "react";
import { ChevronDown, History } from "lucide-react";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { duration, fmt, money, signed } from "@/lib/types";
import type { Trade } from "@/lib/types";
import { cn } from "@/lib/utils";

export default function TradeHistory({ trades }: { trades: Trade[] | undefined }) {
  const [openId, setOpenId] = useState<string | null>(null);
  const rows = trades ?? [];

  return (
    <section
      className="col-span-12 space-y-3 rounded-md border border-slate-800 bg-[#111827] p-4"
      data-testid="trade-history-panel"
    >
      <div className="flex items-center justify-between">
        <h2 className="flex items-center gap-1.5 text-sm font-semibold text-slate-100">
          <History className="size-4 text-amber-400" /> Trade History
        </h2>
        <span className="text-[11px] text-slate-500" data-testid="trade-history-count">
          {rows.length} closed trade{rows.length === 1 ? "" : "s"}
        </span>
      </div>

      {rows.length === 0 ? (
        <div
          className="rounded border border-dashed border-slate-800 p-6 text-center"
          data-testid="trade-history-empty"
        >
          <p className="text-[12px] text-slate-400">No closed trades yet.</p>
          <p className="mx-auto mt-1 max-w-md text-[11px] leading-relaxed text-slate-600">
            The engine is deliberately selective — it waits for 80%+ confluence and a clean risk
            profile, so quiet periods produce no trades at all. Every closed trade will appear here
            with the full reasoning for entry, stop, target and exit.
          </p>
        </div>
      ) : (
        <Table data-testid="trade-history-table">
          <TableHeader>
            <TableRow className="border-slate-800 hover:bg-transparent">
              {["Side", "TF", "Entry", "Exit", "SL / TP", "P&L", "R", "Conf", "Held", "Exit reason", ""].map((h) => (
                <TableHead key={h} className="h-8 text-[10px] uppercase tracking-wider text-slate-500">
                  {h}
                </TableHead>
              ))}
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((t) => {
              const win = (t.pnl ?? 0) >= 0;
              const expanded = openId === t.id;
              return (
                <Fragment key={t.id}>
                  <TableRow
                    className="border-slate-800 text-[11px] transition-colors duration-150 hover:bg-slate-800/40"
                    data-testid="trade-history-row"
                  >
                    <TableCell>
                      <span
                        className={cn(
                          "rounded px-1.5 py-0.5 text-[10px] font-semibold",
                          t.direction === "BUY"
                            ? "bg-emerald-950 text-emerald-300"
                            : "bg-rose-950 text-rose-300",
                        )}
                      >
                        {t.direction}
                      </span>
                    </TableCell>
                    <TableCell className="text-slate-400">{t.timeframe}</TableCell>
                    <TableCell className="tabular-nums text-slate-200">{fmt(t.entry)}</TableCell>
                    <TableCell className="tabular-nums text-slate-200">{fmt(t.exit_price)}</TableCell>
                    <TableCell className="tabular-nums text-slate-500">
                      {fmt(t.initial_sl)} / {fmt(t.tp)}
                    </TableCell>
                    <TableCell
                      className={cn("tabular-nums font-semibold", win ? "text-emerald-400" : "text-rose-400")}
                      data-testid="trade-history-pnl"
                    >
                      {money(t.pnl)}
                    </TableCell>
                    <TableCell className={cn("tabular-nums", win ? "text-emerald-400" : "text-rose-400")}>
                      {signed(t.r_multiple ?? 0, 2)}
                    </TableCell>
                    <TableCell className="tabular-nums text-slate-400">{fmt(t.confidence, 1)}%</TableCell>
                    <TableCell className="text-slate-400">{duration(t.duration_seconds)}</TableCell>
                    <TableCell className="text-slate-300">{t.exit_reason ?? "—"}</TableCell>
                    <TableCell>
                      <button
                        type="button"
                        onClick={() => setOpenId(expanded ? null : t.id)}
                        data-testid="trade-explain-toggle"
                        className="flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] text-slate-400 transition-colors duration-150 hover:text-amber-300 focus:ring-2 focus:ring-amber-500 focus:outline-none"
                      >
                        Why
                        <ChevronDown className={cn("size-3 transition-transform duration-150", expanded && "rotate-180")} />
                      </button>
                    </TableCell>
                  </TableRow>
                  {expanded ? (
                    <TableRow className="border-slate-800 hover:bg-transparent">
                      <TableCell colSpan={11} className="bg-slate-950/60 p-4">
                        <div
                          className="grid animate-rise-in gap-4 md:grid-cols-3"
                          data-testid="trade-explanation"
                        >
                          <div className="space-y-2">
                            <h4 className="text-[10px] uppercase tracking-wider text-amber-400">
                              Why the trade was opened
                            </h4>
                            {t.ai_status === "ai" && t.ai_explanation ? (
                              <p
                                className="rounded border border-amber-900/40 bg-amber-950/20 p-2 text-[11px] leading-relaxed text-amber-100/90"
                                data-testid="trade-ai-explanation"
                              >
                                <span className="mr-1 rounded bg-amber-900/60 px-1 py-0.5 text-[9px] font-semibold text-amber-200">
                                  AI
                                </span>
                                {t.ai_explanation}
                              </p>
                            ) : null}
                            <ul className="space-y-1">
                              {t.entry_reasons.map((i) => (
                                <li key={i} className="text-[10px] leading-relaxed text-slate-400">
                                  · {i}
                                </li>
                              ))}
                            </ul>
                          </div>
                          <Block title="Why this SL & TP" items={t.risk_reasons} />
                          <div className="space-y-2">
                            <h4 className="text-[10px] uppercase tracking-wider text-amber-400">
                              Why it was closed
                            </h4>
                            <p className="text-[11px] leading-relaxed text-slate-300">
                              <span className="font-semibold text-slate-100">{t.exit_reason}</span> —{" "}
                              {t.exit_explanation}
                            </p>
                            <h4 className="pt-1 text-[10px] uppercase tracking-wider text-slate-500">
                              Management log
                            </h4>
                            <ul className="space-y-1">
                              {t.management_log.map((l) => (
                                <li key={l} className="text-[10px] leading-relaxed text-slate-500">
                                  {l}
                                </li>
                              ))}
                            </ul>
                          </div>
                        </div>
                      </TableCell>
                    </TableRow>
                  ) : null}
                </Fragment>
              );
            })}
          </TableBody>
        </Table>
      )}
    </section>
  );
}

function Block({ title, items }: { title: string; items: string[] }) {
  return (
    <div className="space-y-2">
      <h4 className="text-[10px] uppercase tracking-wider text-amber-400">{title}</h4>
      <ul className="space-y-1">
        {items.map((i) => (
          <li key={i} className="text-[10px] leading-relaxed text-slate-400">
            · {i}
          </li>
        ))}
      </ul>
    </div>
  );
}

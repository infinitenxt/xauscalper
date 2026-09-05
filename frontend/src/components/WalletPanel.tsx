import { Wallet as WalletIcon } from "lucide-react";
import { fmt, money, signed } from "@/lib/types";
import type { EngineConfig, Wallet } from "@/lib/types";
import { cn } from "@/lib/utils";

interface Props {
  wallet: Wallet | undefined;
  config: EngineConfig | undefined;
}

export default function WalletPanel({ wallet, config }: Props) {
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
          virtual · {money(wallet?.starting_balance ?? 10000)} start
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
          label="Profit factor"
          value={`${fmt(wallet?.profit_factor ?? 0, 2)}`}
          testid="wallet-profit-factor"
          sub="gross win / gross loss"
        />
        <Stat
          label="Max drawdown"
          value={`${fmt(wallet?.max_drawdown_pct ?? 0, 2)}%`}
          testid="wallet-max-drawdown"
          accent="text-rose-300"
          sub="peak-to-trough equity"
        />
        <Stat
          label="Max hold"
          value={`${config?.max_hold_minutes ?? 15} min`}
          testid="wallet-max-hold"
          sub="auto-cut for scalps"
        />
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

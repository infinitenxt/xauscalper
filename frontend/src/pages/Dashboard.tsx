import { useEffect, useRef, useState, useCallback } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Check, HandCoins, Info, LogOut, ServerCog, ShieldCheck, X } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { useLogout, useMe } from "@/hooks/useAuth";
import { ApiError } from "@/lib/api";
import { Toaster } from "@/components/ui/sonner";
import ActivePositionPanel from "@/components/ActivePositionPanel";
import BacktestPanel from "@/components/BacktestPanel";
import ChangePasswordDialog from "@/components/ChangePasswordDialog";
import PriceChart from "@/components/PriceChart";
import SettingsPanel from "@/components/SettingsPanel";
import SignalBanner from "@/components/SignalBanner";
import SignalPanel from "@/components/SignalPanel";
import TickerBar from "@/components/TickerBar";
import TradeHistory from "@/components/TradeHistory";
import WalletPanel from "@/components/WalletPanel";
import { apiGet, apiPost, apiPut } from "@/lib/api";
import { beepEntry, beepLoss, beepNeutral, beepProfit, unlockAudio } from "@/lib/sound";
import {
  cancelSpeech,
  isSpeaking,
  isSpeechOn,
  setSpeechOn,
  speak,
  speakNow,
  speechSupported,
} from "@/lib/speech";
import { nextComment, pickMood } from "@/lib/commentary";
import type { MoodInput } from "@/lib/commentary";
import { fmt, money } from "@/lib/types";
import type {
  CandlesResponse,
  Dashboard as DashboardData,
  EngineConfig,
  Mt5Account,
  SettingsPatch,
  Signal,
  Trade,
  Wallet,
} from "@/lib/types";
import { cn } from "@/lib/utils";

function analysisScript(signal: Signal): string[] {
  const lines = [
    `${signal.direction} signal on the ${signal.timeframe} timeframe with ${signal.confidence.toFixed(0)} percent confidence.`,
    signal.summary,
  ];
  signal.confirmations.forEach((c) => lines.push(`${c.name} is ${c.direction}. ${c.detail}`));
  signal.risk_checks.forEach((c) => lines.push(`${c.passed ? "Passed" : "Failed"}: ${c.name}. ${c.detail}`));
  signal.level_reasons.forEach((r) => lines.push(r));
  return lines;
}

export default function Dashboard() {
  const [timeframe, setTimeframe] = useState("1m");
  const [symbol, setSymbol] = useState("BTCUSDT");
  const [speechOn, setSpeech] = useState(false);
  const qc = useQueryClient();
  const navigate = useNavigate();
  const { data: me } = useMe();
  const logout = useLogout();

  useEffect(() => setSpeech(isSpeechOn()), []);

  // ✅ Dashboard query with symbol
  const dash = useQuery({
    queryKey: ["dashboard", timeframe, symbol],
    queryFn: () => apiGet<DashboardData>(`/dashboard?timeframe=${timeframe}&symbol=${symbol}`),
    refetchInterval: 3000,
    retry: false,
  });

  // ✅ Candles query with symbol
  const candles = useQuery({
    queryKey: ["candles", timeframe, symbol],
    queryFn: () => apiGet<CandlesResponse>(`/market/candles?symbol=${symbol}&timeframe=${timeframe}&limit=160`),
    refetchInterval: 5000,
    retry: false,
  });

  const mt5 = useQuery({
    queryKey: ["mt5", "account"],
    queryFn: () => apiGet<Mt5Account | null>("/mt5/account"),
    refetchInterval: 3000,
    retry: false,
  });

  const data = dash.isError ? undefined : dash.data;
  const present = data?.guards.present ?? false;

  // ✅ Load saved symbol from settings
  const { data: settings } = useQuery({
    queryKey: ["settings"],
    queryFn: () => apiGet("/settings"),
    enabled: !!me,
  });

  useEffect(() => {
    if (settings?.symbol) {
      setSymbol(settings.symbol);
    }
  }, [settings]);

  // Presence heartbeat
  useEffect(() => {
    const ping = () => {
      if (document.visibilityState === "visible") {
        void apiPost("/presence").catch(() => undefined);
      }
    };
    ping();
    const id = window.setInterval(ping, 10_000);
    document.addEventListener("visibilitychange", ping);
    return () => {
      window.clearInterval(id);
      document.removeEventListener("visibilitychange", ping);
    };
  }, []);

  // Subscription expiring mid-session, or the other device signing us out.
  useEffect(() => {
    const err = dash.error;
    if (!(err instanceof ApiError)) return;
    if (err.status === 402) navigate("/subscribe", { replace: true });
    if (err.status === 401) navigate("/login", { replace: true });
  }, [dash.error, navigate]);

  const closeTrade = useMutation({
    mutationFn: (id: string) => apiPost<Trade>(`/trades/${id}/close`),
    onSuccess: (t) => {
      toast.success(`Position closed at ${t.exit_price?.toFixed(2)} · P&L ${money(t.pnl)}`);
      void qc.invalidateQueries({ queryKey: ["dashboard"] });
    },
    onError: () => toast.error("Could not close the position — no live price available."),
  });

  const reset = useMutation({
    mutationFn: () => apiPost<Wallet>("/engine/reset"),
    onSuccess: () => {
      toast.success("Paper account reset to $10,000");
      void qc.invalidateQueries({ queryKey: ["dashboard"] });
    },
    onError: () => toast.error("Reset failed."),
  });

  const saveSettings = useMutation({
    mutationFn: (patch: SettingsPatch) => apiPut<EngineConfig>("/settings", patch),
    onSuccess: (cfg) => {
      toast.success(
        `Settings saved — ${cfg.primary_timeframe} entries, ${cfg.confidence_threshold}% threshold, ${cfg.max_hold_minutes} min max hold`,
      );
      void qc.invalidateQueries({ queryKey: ["dashboard"] });
    },
    onError: () => toast.error("Could not save settings."),
  });

  const restoreDefaults = useMutation({
    mutationFn: () => apiPost<EngineConfig>("/settings/reset"),
    onSuccess: () => {
      toast.success("Scalping defaults restored");
      void qc.invalidateQueries({ queryKey: ["dashboard"] });
    },
    onError: () => toast.error("Could not restore defaults."),
  });

  // ---- voice + sound event detection -------------------------------------
  const prevDir = useRef<string | null>(null);
  const prevOpenId = useRef<string | null>(null);
  const prevClosedId = useRef<string | null>(null);
  const prevAiId = useRef<string | null>(null);
  const signal = data?.signal;
  const openTrade = data?.open_trade ?? null;
  const lastClosed = data?.history?.[0] ?? null;

  useEffect(() => {
    if (!signal) return;
    if (prevDir.current === null) {
      prevDir.current = signal.direction;
      return;
    }
    if (signal.direction !== prevDir.current) {
      prevDir.current = signal.direction;
      speak(analysisScript(signal));
    }
  }, [signal]);

  useEffect(() => {
    if (openTrade && openTrade.id !== prevOpenId.current) {
      prevOpenId.current = openTrade.id;
      beepEntry();
      toast.success(`${openTrade.direction} opened at ${openTrade.entry.toFixed(2)}`);
      speak([
        `Trade opened. ${openTrade.direction} ${openTrade.qty} ounces at ${openTrade.entry.toFixed(2)}.`,
        `Stop loss ${openTrade.sl.toFixed(2)}, take profit ${openTrade.tp.toFixed(2)}.`,
        ...openTrade.entry_reasons,
        ...openTrade.risk_reasons,
      ]);
    }
    if (!openTrade) prevOpenId.current = null;
  }, [openTrade]);

  useEffect(() => {
    if (!lastClosed) return;
    if (prevClosedId.current === null) {
      prevClosedId.current = lastClosed.id;
      return;
    }
    if (lastClosed.id !== prevClosedId.current) {
      prevClosedId.current = lastClosed.id;
      const reason = lastClosed.exit_reason ?? "";
      const won = (lastClosed.pnl ?? 0) > 0;
      if (reason === "TAKE PROFIT" || won) beepProfit();
      else if (reason.includes("STOP")) beepLoss();
      else beepNeutral();
      toast[won ? "success" : "error"](`${reason} · ${money(lastClosed.pnl)}`);
      speak([
        `Trade closed. ${reason}. Profit and loss ${(lastClosed.pnl ?? 0).toFixed(2)} dollars.`,
        lastClosed.exit_explanation ?? "",
      ]);
    }
  }, [lastClosed]);

  useEffect(() => {
    if (!openTrade) {
      prevAiId.current = null;
      return;
    }
    if (openTrade.ai_status === "ai" && openTrade.ai_explanation && prevAiId.current !== openTrade.id) {
      prevAiId.current = openTrade.id;
      speak([`Why we took this trade. ${openTrade.ai_explanation}`]);
    }
  }, [openTrade]);

  // ---- rolling market commentary, spoken every 5 seconds ------------------
  const [lastComment, setLastComment] = useState("");
  const atrPct = signal?.atr && signal.price ? (signal.atr / signal.price) * 100 : undefined;
  const moodInput = useRef<MoodInput>({
    direction: undefined,
    confidence: 0,
    atrPct: undefined,
    blocked: false,
    inTrade: false,
    tradePnl: 0,
    tpProgress: 0,
  });
  moodInput.current = {
    direction: signal?.direction,
    confidence: signal?.confidence,
    atrPct,
    blocked: data?.guards.blocked ?? false,
    inTrade: !!openTrade,
    tradePnl: openTrade?.unrealized_pnl ?? 0,
    tpProgress: openTrade?.tp_progress_pct ?? 0,
  };

  useEffect(() => {
    const tick = () => {
      const comment = nextComment(pickMood(moodInput.current));
      if (!comment) return;
      setLastComment(comment);
      if (isSpeechOn() && !isSpeaking()) speak(comment);
    };
    tick();
    const id = setInterval(tick, 5000);
    return () => clearInterval(id);
  }, []);

  const toggleSpeech = useCallback(() => {
    if (!speechSupported()) {
      toast.error("This browser has no speech support — voice announcements are unavailable.");
      return;
    }
    const next = !isSpeechOn();
    setSpeechOn(next);
    setSpeech(next);
    if (next) speakNow("Voice announcements on. I will read every signal and trade explanation.");
    else cancelSpeech();
  }, []);

  const readAnalysis = useCallback(() => {
    if (!speechSupported()) {
      toast.error("This browser has no speech support.");
      return;
    }
    if (!signal) return;
    speakNow(analysisScript(signal));
  }, [signal]);

  const live = !dash.isError && !!data?.ticker.price;

  return (
    <div className="min-h-screen bg-[#0b0e14]" onPointerDown={unlockAudio}>
      <Toaster position="bottom-right" richColors />
      <div className="mx-auto grid max-w-[1700px] grid-cols-12 gap-3 p-3">
        <TickerBar
          ticker={data?.ticker}
          feed={data?.feed}
          equity={data?.wallet.equity}
          dayPnl={data?.wallet.day_pnl}
          timeframe={timeframe}
          onTimeframe={setTimeframe}
          onReset={() => reset.mutate()}
          resetting={reset.isPending}
          live={live}
          autoTradeOn={data?.config.auto_trade_enabled ?? true}
          symbol={symbol}
          onSymbolChange={setSymbol}
          settingsSlot={
            <SettingsPanel
              config={data?.config}
              onSave={(patch) => saveSettings.mutate(patch)}
              saving={saveSettings.isPending}
              onRestoreDefaults={() => restoreDefaults.mutate()}
            />
          }
          userSlot={
            <div className="flex items-center gap-2" data-testid="user-menu">
              <span
                data-testid="presence-indicator"
                title={
                  present
                    ? "Dashboard is open — the engine may open new trades on your account"
                    : "Dashboard idle — open trades are still managed, but no new trades will open"
                }
                className={cn(
                  "flex items-center gap-1.5 rounded border px-2 py-1 text-[10px] transition-colors duration-200",
                  present
                    ? "border-emerald-700/60 bg-emerald-500/10 text-emerald-300"
                    : "border-slate-700 bg-slate-900 text-slate-500",
                )}
              >
                <span
                  className={cn(
                    "size-1.5 rounded-full",
                    present ? "animate-pulse bg-emerald-400" : "bg-slate-600",
                  )}
                />
                {present ? "Live · entries armed" : "Idle · exits only"}
              </span>
              <div className="hidden text-right leading-tight sm:block">
                <div className="text-[10px] text-slate-400" data-testid="user-menu-name">
                  {me?.username ?? "—"}
                </div>
                <div className="text-[9px] text-slate-600" data-testid="user-menu-plan">
                  {me?.role === "admin"
                    ? "admin"
                    : `${me?.subscription.plan_name ?? "no plan"} · ${me?.subscription.days_left ?? 0}d`}
                </div>
              </div>
              <ChangePasswordDialog compact />
              <Button
                variant="outline"
                size="sm"
                onClick={() => navigate("/mt5")}
                data-testid="mt5-link-button"
                className="border-slate-700 text-slate-300 transition-colors duration-150 hover:text-amber-300"
              >
                <ServerCog className="size-3.5" />
                MT5
              </Button>
              <Button
                variant="outline"
                size="sm"
                onClick={() => navigate("/affiliate")}
                data-testid="affiliate-link-button"
                className="border-slate-700 text-slate-300 transition-colors duration-150 hover:text-emerald-300"
              >
                <HandCoins className="size-3.5" />
                Affiliate
              </Button>
              {me?.role === "admin" ? (
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => navigate("/admin")}
                  data-testid="admin-link-button"
                  className="border-slate-700 text-slate-300 transition-colors duration-150 hover:text-amber-300"
                >
                  <ShieldCheck className="size-3.5" />
                  Admin
                </Button>
              ) : null}
              <Button
                variant="outline"
                size="sm"
                onClick={() => logout.mutate()}
                data-testid="logout-button"
                className="border-slate-700 text-slate-300 transition-colors duration-150 hover:text-rose-300"
              >
                <LogOut className="size-3.5" />
              </Button>
            </div>
          }
        />

       

        <ActivePositionPanel
          trade={data?.open_trade}
          mt5Account={mt5.isError ? undefined : mt5.data}
          config={data?.config}
          onClose={(id) => closeTrade.mutate(id)}
          closing={closeTrade.isPending}
        />

        <SignalBanner
          signal={data?.signal}
          guards={data?.guards}
          threshold={data?.config.confidence_threshold ?? 80}
          speechOn={speechOn}
          onToggleSpeech={toggleSpeech}
          onReadAnalysis={readAnalysis}
          lastComment={lastComment}
        />

        <PriceChart
          candles={candles.isError ? undefined : candles.data?.candles}
          timeframe={timeframe}
          signal={data?.signal}
          openTrade={data?.open_trade}
          livePrice={data?.ticker.price}
          loading={candles.isLoading}
          symbol={symbol}
        />

        <SignalPanel
          signal={data?.signal}
          threshold={data?.config.confidence_threshold ?? 80}
          stale={dash.isError}
        />

        <WalletPanel wallet={data?.wallet} config={data?.config} />

        <section
          className="col-span-12 space-y-3 rounded-md border border-slate-800 bg-[#111827] p-4 lg:col-span-8"
          data-testid="engine-rules-panel"
        >
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h2 className="text-sm font-semibold text-slate-100">Scalping rules &amp; account guards</h2>
            <span
              className={cn(
                "rounded px-2 py-0.5 text-[10px] font-semibold",
                data?.config.auto_trade_enabled
                  ? "bg-emerald-950 text-emerald-300"
                  : "bg-rose-950 text-rose-300",
              )}
              data-testid="auto-trade-state"
            >
              AUTO-TRADE {data?.config.auto_trade_enabled ? "ARMED" : "OFF"}
            </span>
          </div>

          <dl className="grid grid-cols-2 gap-2 text-[11px] sm:grid-cols-3 lg:grid-cols-4">
            {[
              ["Auto-trade threshold", `${fmt(data?.config.confidence_threshold ?? 80, 0)}% confluence`],
              ["Entry timeframe", data?.config.primary_timeframe ?? "5m"],
              ["Risk per trade", `${fmt(data?.config.risk_per_trade_pct ?? 1, 2)}% of balance`],
              ["Stop / target", `${fmt(data?.config.atr_sl_mult ?? 0.9, 2)}x ATR · R:R ${fmt(data?.config.base_rr ?? 1.4, 2)}`],
              ["Break-even", `at +${fmt(data?.config.breakeven_at_r ?? 0.5, 2)}R`],
              [
                "Partial TP",
                `${fmt((data?.config.partial_tp_fraction ?? 0.5) * 100, 0)}% at +${fmt(data?.config.partial_tp_at_r ?? 1, 2)}R`,
              ],
              ["Trailing stop", `${fmt(data?.config.trail_atr_mult ?? 0.8, 2)}x ATR from +${fmt(data?.config.trail_start_r ?? 1, 2)}R`],
              ["Auto-cut", `${data?.config.max_hold_minutes ?? 15} min max hold`],
              ["Cooldown", `${data?.config.cooldown_seconds ?? 60}s after a close`],
              ["Daily loss limit", `${fmt(data?.config.daily_loss_limit_pct ?? 3, 2)}%`],
              ["Max trades / hour", `${data?.config.max_trades_per_hour ?? 6}`],
              ["Chase guard", `skip past ${fmt(data?.config.stale_entry_max_pct ?? 25, 0)}% to target`],
            ].map(([k, v]) => (
              <div key={k} className="rounded border border-slate-800 bg-slate-950/50 p-2">
                <dt className="text-[10px] uppercase tracking-wider text-slate-500">{k}</dt>
                <dd className="text-slate-200">{v}</dd>
              </div>
            ))}
          </dl>

          <div className="space-y-1.5" data-testid="guard-checks">
            <h3 className="text-[10px] uppercase tracking-wider text-slate-500">Account guards right now</h3>
            {(data?.guards.checks ?? []).map((c) => (
              <div key={c.name} className="flex items-start gap-2 text-[11px]">
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
            {!data ? <p className="text-[11px] text-slate-500">Waiting for the engine…</p> : null}
          </div>

          <p className="flex gap-2 rounded border border-amber-900/40 bg-amber-950/20 p-2.5 text-[11px] leading-relaxed text-amber-200/80">
            <Info className="mt-0.5 size-3.5 shrink-0" />
            <span data-testid="disclaimer">
              {data?.config.disclaimer ??
                "Educational paper trading only. No real orders are placed and no signal is a guarantee — price can move against any confirmed setup."}
            </span>
          </p>
        </section>

        <BacktestPanel />

        <TradeHistory trades={data?.history} />
      </div>
    </div>
  );
}
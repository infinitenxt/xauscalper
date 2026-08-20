import { useEffect, useState } from "react";
import { Settings2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { TIMEFRAMES } from "@/lib/types";
import type { EngineConfig, SettingsPatch } from "@/lib/types";

interface Field {
  key: keyof SettingsPatch;
  label: string;
  hint: string;
  step?: string;
}

const GROUPS: { title: string; fields: Field[] }[] = [
  {
    title: "Entry quality",
    fields: [
      { key: "confidence_threshold", label: "Confidence threshold %", hint: "auto-trade only at or above this confluence score", step: "1" },
      { key: "min_adx", label: "Minimum ADX", hint: "reject flat, choppy markets", step: "1" },
      { key: "min_rr", label: "Minimum R:R", hint: "reject setups whose target is too close", step: "0.1" },
      { key: "stale_entry_max_pct", label: "Stale entry max %", hint: "skip if price already ran this far toward target", step: "5" },
    ],
  },
  {
    title: "Sizing & levels",
    fields: [
      { key: "risk_per_trade_pct", label: "Risk per trade %", hint: "% of balance risked between entry and stop", step: "0.1" },
      { key: "atr_sl_mult", label: "Stop = ATR ×", hint: "tighter = more trades, more stop-outs", step: "0.1" },
      { key: "base_rr", label: "Base reward:risk", hint: "target distance as a multiple of the stop", step: "0.1" },
    ],
  },
  {
    title: "Trade management",
    fields: [
      { key: "breakeven_at_r", label: "Break-even at R", hint: "move stop to entry once this much profit is banked", step: "0.1" },
      { key: "partial_tp_at_r", label: "Partial TP at R", hint: "bank part of the position here", step: "0.1" },
      { key: "partial_tp_fraction", label: "Partial TP fraction", hint: "0.5 = close half the position", step: "0.05" },
      { key: "trail_start_r", label: "Trail starts at R", hint: "profit level where the trailing stop arms", step: "0.1" },
      { key: "trail_atr_mult", label: "Trail = ATR ×", hint: "how far the trailing stop sits behind price", step: "0.1" },
      { key: "max_hold_minutes", label: "Max hold (minutes)", hint: "hard time cap — the scalper's auto-cut", step: "1" },
      { key: "cooldown_seconds", label: "Cooldown (seconds)", hint: "forced pause after each close", step: "10" },
    ],
  },
  {
    title: "Circuit breakers",
    fields: [
      { key: "daily_loss_limit_pct", label: "Daily loss limit %", hint: "stop trading for the day past this loss", step: "0.5" },
      { key: "max_trades_per_hour", label: "Max trades / hour", hint: "prevents over-trading in chop", step: "1" },
      { key: "consecutive_loss_pause", label: "Loss streak to pause", hint: "cool off after this many losses in a row", step: "1" },
      { key: "pause_minutes_after_losses", label: "Cool-off minutes", hint: "how long that pause lasts", step: "5" },
    ],
  },
];

interface Props {
  config: EngineConfig | undefined;
  onSave: (patch: SettingsPatch) => void;
  saving: boolean;
  onRestoreDefaults: () => void;
}

export default function SettingsPanel({ config, onSave, saving, onRestoreDefaults }: Props) {
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [autoTrade, setAutoTrade] = useState(true);
  const [tf, setTf] = useState("1m");

  useEffect(() => {
    if (!config || !open) return;
    const next: Record<string, string> = {};
    GROUPS.flatMap((g) => g.fields).forEach((f) => {
      next[f.key] = String(config[f.key as keyof EngineConfig] ?? "");
    });
    setDraft(next);
    setAutoTrade(config.auto_trade_enabled);
    setTf(config.primary_timeframe);
  }, [config, open]);

  const save = () => {
    const patch: Record<string, unknown> = { auto_trade_enabled: autoTrade, primary_timeframe: tf };
    Object.entries(draft).forEach(([k, v]) => {
      const num = Number(v);
      if (v !== "" && Number.isFinite(num)) patch[k] = num;
    });
    onSave(patch as SettingsPatch);
    setOpen(false);
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger
        render={
          <Button
            variant="outline"
            size="sm"
            data-testid="open-settings-button"
            className="border-slate-700 text-slate-300 transition-colors duration-150 hover:text-amber-300"
          >
            <Settings2 className="size-3.5" />
            Settings
          </Button>
        }
      />
      <DialogContent className="max-h-[88vh] overflow-y-auto border-slate-800 bg-[#111827] sm:max-w-3xl">
        <DialogHeader>
          <DialogTitle className="text-slate-100">Engine settings</DialogTitle>
          <DialogDescription className="text-slate-400">
            Live strategy and risk controls. Values are clamped to safe bounds on the server, and
            take effect on the next engine cycle.
          </DialogDescription>
        </DialogHeader>

        <div className="grid gap-4 sm:grid-cols-2">
          <div className="flex items-start gap-3 rounded border border-slate-800 bg-slate-950/50 p-3 sm:col-span-2">
            <Checkbox
              checked={autoTrade}
              onCheckedChange={(v) => setAutoTrade(Boolean(v))}
              data-testid="auto-trade-toggle"
            />
            <div>
              <Label className="text-slate-200">Auto-trading armed</Label>
              <p className="text-[11px] text-slate-500">
                Master kill switch. Off = signals keep updating but no paper trade is ever opened.
              </p>
            </div>
          </div>

          <div className="sm:col-span-2">
            <Label className="text-[11px] text-slate-300">Trading timeframe (entries)</Label>
            <Select value={tf} onValueChange={(v: string) => setTf(v)}>
              <SelectTrigger className="mt-1 border-slate-700 bg-slate-950" data-testid="primary-timeframe-select">
                <SelectValue>{(v) => String(v ?? tf)}</SelectValue>
              </SelectTrigger>
              <SelectContent>
                {TIMEFRAMES.map((t) => (
                  <SelectItem key={t} value={t}>
                    {t}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <p className="mt-1 text-[11px] text-slate-500">
              1m is the scalping default. Higher timeframes mean fewer, slower trades.
            </p>
          </div>

          {GROUPS.map((group) => (
            <div key={group.title} className="space-y-3 rounded border border-slate-800 bg-slate-950/40 p-3">
              <h3 className="text-[10px] uppercase tracking-wider text-amber-400">{group.title}</h3>
              {group.fields.map((f) => (
                <div key={String(f.key)}>
                  <Label className="text-[11px] text-slate-300">{f.label}</Label>
                  <Input
                    type="number"
                    step={f.step ?? "0.1"}
                    value={draft[f.key] ?? ""}
                    onChange={(e) => setDraft((d) => ({ ...d, [f.key]: e.target.value }))}
                    data-testid={`setting-${String(f.key).replace(/_/g, "-")}`}
                    className="mt-1 border-slate-700 bg-slate-950 text-slate-100"
                  />
                  <p className="mt-0.5 text-[10px] text-slate-600">{f.hint}</p>
                </div>
              ))}
            </div>
          ))}
        </div>

        <DialogFooter className="gap-2">
          <Button
            variant="ghost"
            size="sm"
            onClick={onRestoreDefaults}
            data-testid="restore-defaults-button"
            className="text-slate-400 hover:text-amber-300"
          >
            Restore scalping defaults
          </Button>
          <Button size="sm" onClick={save} disabled={saving} data-testid="save-settings-button">
            {saving ? "Saving…" : "Save settings"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

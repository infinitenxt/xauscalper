import { useState, useEffect } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Settings, Save, RotateCcw, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { apiPatch } from "@/lib/api";
import TelegramSettings from "./TelegramSettings";
import type { EngineConfig, SettingsPatch } from "@/lib/types";

interface Props {
  config?: EngineConfig;
  onSave: (patch: SettingsPatch) => void;
  saving: boolean;
  onRestoreDefaults: () => void;
}

export default function SettingsPanel({ config, onSave, saving, onRestoreDefaults }: Props) {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [symbol, setSymbol] = useState(config?.symbol || "BTCUSDT");
  const [settings, setSettings] = useState<SettingsPatch>({});

  // ✅ Load settings from config
  useEffect(() => {
    if (config) {
      setSettings({
        confidence_threshold: config.confidence_threshold,
        min_adx: config.min_adx,
        min_rr: config.min_rr,
        risk_per_trade_pct: config.risk_per_trade_pct,
        atr_sl_mult: config.atr_sl_mult,
        base_rr: config.base_rr,
        trail_start_r: config.trail_start_r,
        trail_atr_mult: config.trail_atr_mult,
        breakeven_at_r: config.breakeven_at_r,
        max_hold_minutes: config.max_hold_minutes,
        cooldown_seconds: config.cooldown_seconds,
        daily_loss_limit_pct: config.daily_loss_limit_pct,
        max_trades_per_hour: config.max_trades_per_hour,
        consecutive_loss_pause: config.consecutive_loss_pause,
        pause_minutes_after_losses: config.pause_minutes_after_losses,
        stale_entry_max_pct: config.stale_entry_max_pct,
        auto_trade_enabled: config.auto_trade_enabled,
        session_filter_enabled: config.session_filter_enabled,
        primary_timeframe: config.primary_timeframe,
        partial_tp_at_r: config.partial_tp_at_r,
        partial_tp_fraction: config.partial_tp_fraction,
      });
      setSymbol(config.symbol || "BTCUSDT");
    }
  }, [config]);

  // ✅ Save symbol mutation
  const saveSymbol = useMutation({
    mutationFn: () => apiPatch("/settings/symbol", { symbol }),
    onSuccess: () => {
      toast.success("Symbol updated!");
      qc.invalidateQueries({ queryKey: ["settings"] });
      qc.invalidateQueries({ queryKey: ["dashboard"] });
    },
    onError: () => toast.error("Failed to update symbol"),
  });

  const handleSave = () => {
    onSave(settings);
    // ✅ Also save symbol if changed
    if (symbol !== config?.symbol) {
      saveSymbol.mutate();
    }
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button variant="outline" size="sm" className="border-slate-700 text-slate-300 hover:text-amber-300">
          <Settings className="size-3.5" />
          Settings
        </Button>
      </DialogTrigger>
      <DialogContent className="max-h-[90vh] max-w-2xl overflow-y-auto border-slate-800 bg-[#111827] text-slate-100">
        <DialogHeader>
          <DialogTitle className="text-slate-100">Scalping Settings</DialogTitle>
        </DialogHeader>

        <div className="space-y-4 py-4">
          {/* ✅ Symbol Selector */}
          <div className="rounded-md border border-slate-800 bg-slate-950/50 p-4">
            <h3 className="text-sm font-semibold text-slate-100">Trading Symbol</h3>
            <div className="mt-3 flex items-end gap-3">
              <div className="flex-1">
                <Label className="text-[11px] text-slate-300">Select Symbol</Label>
                <Select value={symbol} onValueChange={setSymbol}>
                  <SelectTrigger className="mt-1 w-full border-slate-700 bg-slate-950 text-slate-100">
                    <SelectValue placeholder="Select symbol" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="BTCUSDT">BTC/USD</SelectItem>
                    <SelectItem value="XAUUSD">XAU/USD</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <Button
                size="sm"
                onClick={() => saveSymbol.mutate()}
                disabled={saveSymbol.isPending || symbol === config?.symbol}
                className="bg-emerald-600 hover:bg-emerald-700"
              >
                {saveSymbol.isPending ? <Loader2 className="size-4 animate-spin" /> : "Save Symbol"}
              </Button>
            </div>
          </div>

          {/* ENTRY QUALITY */}
          <div className="rounded-md border border-slate-800 bg-slate-950/50 p-4">
            <h3 className="text-sm font-semibold text-slate-100">Entry Quality</h3>
            <div className="mt-3 grid grid-cols-2 gap-3">
              <div>
                <Label className="text-[11px] text-slate-300">Confidence threshold %</Label>
                <Input
                  type="number"
                  value={settings.confidence_threshold ?? 70}
                  onChange={(e) => setSettings({ ...settings, confidence_threshold: Number(e.target.value) })}
                  className="mt-1 border-slate-700 bg-slate-950 text-slate-100"
                />
              </div>
              <div>
                <Label className="text-[11px] text-slate-300">Minimum ADX</Label>
                <Input
                  type="number"
                  value={settings.min_adx ?? 18}
                  onChange={(e) => setSettings({ ...settings, min_adx: Number(e.target.value) })}
                  className="mt-1 border-slate-700 bg-slate-950 text-slate-100"
                />
              </div>
              <div>
                <Label className="text-[11px] text-slate-300">Minimum R:R</Label>
                <Input
                  type="number"
                  step="0.1"
                  value={settings.min_rr ?? 1.5}
                  onChange={(e) => setSettings({ ...settings, min_rr: Number(e.target.value) })}
                  className="mt-1 border-slate-700 bg-slate-950 text-slate-100"
                />
              </div>
              <div>
                <Label className="text-[11px] text-slate-300">Stale entry max %</Label>
                <Input
                  type="number"
                  value={settings.stale_entry_max_pct ?? 30}
                  onChange={(e) => setSettings({ ...settings, stale_entry_max_pct: Number(e.target.value) })}
                  className="mt-1 border-slate-700 bg-slate-950 text-slate-100"
                />
              </div>
            </div>
          </div>

          {/* SIZING & LEVELS */}
          <div className="rounded-md border border-slate-800 bg-slate-950/50 p-4">
            <h3 className="text-sm font-semibold text-slate-100">Sizing & Levels</h3>
            <div className="mt-3 grid grid-cols-3 gap-3">
              <div>
                <Label className="text-[11px] text-slate-300">Risk per trade %</Label>
                <Input
                  type="number"
                  step="0.5"
                  value={settings.risk_per_trade_pct ?? 8}
                  onChange={(e) => setSettings({ ...settings, risk_per_trade_pct: Number(e.target.value) })}
                  className="mt-1 border-slate-700 bg-slate-950 text-slate-100"
                />
              </div>
              <div>
                <Label className="text-[11px] text-slate-300">Stop = ATR ×</Label>
                <Input
                  type="number"
                  step="0.1"
                  value={settings.atr_sl_mult ?? 1.0}
                  onChange={(e) => setSettings({ ...settings, atr_sl_mult: Number(e.target.value) })}
                  className="mt-1 border-slate-700 bg-slate-950 text-slate-100"
                />
              </div>
              <div>
                <Label className="text-[11px] text-slate-300">Base reward:risk</Label>
                <Input
                  type="number"
                  step="0.1"
                  value={settings.base_rr ?? 1.8}
                  onChange={(e) => setSettings({ ...settings, base_rr: Number(e.target.value) })}
                  className="mt-1 border-slate-700 bg-slate-950 text-slate-100"
                />
              </div>
            </div>
          </div>

          {/* TRADE MANAGEMENT */}
          <div className="rounded-md border border-slate-800 bg-slate-950/50 p-4">
            <h3 className="text-sm font-semibold text-slate-100">Trade Management</h3>
            <div className="mt-3 grid grid-cols-3 gap-3">
              <div>
                <Label className="text-[11px] text-slate-300">Break-even at R</Label>
                <Input
                  type="number"
                  step="0.1"
                  value={settings.breakeven_at_r ?? 0.8}
                  onChange={(e) => setSettings({ ...settings, breakeven_at_r: Number(e.target.value) })}
                  className="mt-1 border-slate-700 bg-slate-950 text-slate-100"
                />
              </div>
              <div>
                <Label className="text-[11px] text-slate-300">Partial TP at R</Label>
                <Input
                  type="number"
                  step="0.1"
                  value={settings.partial_tp_at_r ?? 1.5}
                  onChange={(e) => setSettings({ ...settings, partial_tp_at_r: Number(e.target.value) })}
                  className="mt-1 border-slate-700 bg-slate-950 text-slate-100"
                />
              </div>
              <div>
                <Label className="text-[11px] text-slate-300">Partial TP fraction</Label>
                <Input
                  type="number"
                  step="0.1"
                  value={settings.partial_tp_fraction ?? 0.4}
                  onChange={(e) => setSettings({ ...settings, partial_tp_fraction: Number(e.target.value) })}
                  className="mt-1 border-slate-700 bg-slate-950 text-slate-100"
                />
              </div>
              <div>
                <Label className="text-[11px] text-slate-300">Trail starts at R</Label>
                <Input
                  type="number"
                  step="0.1"
                  value={settings.trail_start_r ?? 0.8}
                  onChange={(e) => setSettings({ ...settings, trail_start_r: Number(e.target.value) })}
                  className="mt-1 border-slate-700 bg-slate-950 text-slate-100"
                />
              </div>
              <div>
                <Label className="text-[11px] text-slate-300">Trail = ATR ×</Label>
                <Input
                  type="number"
                  step="0.1"
                  value={settings.trail_atr_mult ?? 0.6}
                  onChange={(e) => setSettings({ ...settings, trail_atr_mult: Number(e.target.value) })}
                  className="mt-1 border-slate-700 bg-slate-950 text-slate-100"
                />
              </div>
              <div>
                <Label className="text-[11px] text-slate-300">Max hold (minutes)</Label>
                <Input
                  type="number"
                  value={settings.max_hold_minutes ?? 15}
                  onChange={(e) => setSettings({ ...settings, max_hold_minutes: Number(e.target.value) })}
                  className="mt-1 border-slate-700 bg-slate-950 text-slate-100"
                />
              </div>
              <div>
                <Label className="text-[11px] text-slate-300">Cooldown (seconds)</Label>
                <Input
                  type="number"
                  value={settings.cooldown_seconds ?? 45}
                  onChange={(e) => setSettings({ ...settings, cooldown_seconds: Number(e.target.value) })}
                  className="mt-1 border-slate-700 bg-slate-950 text-slate-100"
                />
              </div>
            </div>
          </div>

          {/* CIRCUIT BREAKERS */}
          <div className="rounded-md border border-slate-800 bg-slate-950/50 p-4">
            <h3 className="text-sm font-semibold text-slate-100">Circuit Breakers</h3>
            <div className="mt-3 grid grid-cols-3 gap-3">
              <div>
                <Label className="text-[11px] text-slate-300">Daily loss limit %</Label>
                <Input
                  type="number"
                  step="0.5"
                  value={settings.daily_loss_limit_pct ?? 20}
                  onChange={(e) => setSettings({ ...settings, daily_loss_limit_pct: Number(e.target.value) })}
                  className="mt-1 border-slate-700 bg-slate-950 text-slate-100"
                />
              </div>
              <div>
                <Label className="text-[11px] text-slate-300">Max trades / hour</Label>
                <Input
                  type="number"
                  value={settings.max_trades_per_hour ?? 6}
                  onChange={(e) => setSettings({ ...settings, max_trades_per_hour: Number(e.target.value) })}
                  className="mt-1 border-slate-700 bg-slate-950 text-slate-100"
                />
              </div>
              <div>
                <Label className="text-[11px] text-slate-300">Loss streak to pause</Label>
                <Input
                  type="number"
                  value={settings.consecutive_loss_pause ?? 3}
                  onChange={(e) => setSettings({ ...settings, consecutive_loss_pause: Number(e.target.value) })}
                  className="mt-1 border-slate-700 bg-slate-950 text-slate-100"
                />
              </div>
              <div>
                <Label className="text-[11px] text-slate-300">Cool-off minutes</Label>
                <Input
                  type="number"
                  value={settings.pause_minutes_after_losses ?? 15}
                  onChange={(e) => setSettings({ ...settings, pause_minutes_after_losses: Number(e.target.value) })}
                  className="mt-1 border-slate-700 bg-slate-950 text-slate-100"
                />
              </div>
            </div>
          </div>

          {/* AUTO-TRADE TOGGLES */}
          <div className="rounded-md border border-slate-800 bg-slate-950/50 p-4">
            <h3 className="text-sm font-semibold text-slate-100">Auto-Trade</h3>
            <div className="mt-3 space-y-3">
              <div className="flex items-center justify-between">
                <Label className="text-[11px] text-slate-300">Auto-Trade Enabled</Label>
                <Switch
                  checked={settings.auto_trade_enabled ?? true}
                  onCheckedChange={(checked) => setSettings({ ...settings, auto_trade_enabled: checked })}
                />
              </div>
              <div className="flex items-center justify-between">
                <Label className="text-[11px] text-slate-300">Session Filter</Label>
                <Switch
                  checked={settings.session_filter_enabled ?? false}
                  onCheckedChange={(checked) => setSettings({ ...settings, session_filter_enabled: checked })}
                />
              </div>
            </div>
          </div>

          {/* ✅ TELEGRAM SETTINGS */}
          <TelegramSettings />

          {/* SAVE / RESET */}
          <div className="flex gap-2 pt-2">
            <Button
              onClick={handleSave}
              disabled={saving}
              className="bg-amber-600 hover:bg-amber-700"
            >
              {saving ? <Loader2 className="size-4 animate-spin" /> : <Save className="size-4" />}
              Save All Settings
            </Button>
            <Button
              variant="outline"
              onClick={onRestoreDefaults}
              className="border-slate-700 text-slate-300"
            >
              <RotateCcw className="size-4" />
              Restore Defaults
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
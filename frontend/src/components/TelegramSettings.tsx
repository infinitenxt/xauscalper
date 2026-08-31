import { useState, useEffect } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Checkbox } from "@/components/ui/checkbox";
import { apiGet, apiPatch, apiPost } from "@/lib/api";
import { Send, CheckCircle2, AlertCircle, Loader2 } from "lucide-react";  // ✅ Telegram hatao

export default function TelegramSettings() {
  const qc = useQueryClient();
  
  const { data: settings, isLoading, refetch } = useQuery({
    queryKey: ["settings"],
    queryFn: () => apiGet("/settings"),
    retry: false,
  });

  const [botToken, setBotToken] = useState("");
  const [channelId, setChannelId] = useState("");
  const [enabled, setEnabled] = useState(false);
  const [testStatus, setTestStatus] = useState<"idle" | "sending" | "success" | "error">("idle");

  useEffect(() => {
    if (settings) {
      setBotToken(settings.telegram_bot_token || "");
      setChannelId(settings.telegram_channel_id || "");
      setEnabled(settings.telegram_alerts_enabled || false);
    }
  }, [settings]);

  const saveSettings = useMutation({
    mutationFn: () => apiPatch("/settings/telegram", {
      bot_token: botToken,
      channel_id: channelId,
      enabled: enabled
    }),
    onSuccess: () => {
      toast.success("Telegram settings saved!");
      qc.invalidateQueries({ queryKey: ["settings"] });
      refetch();
    },
    onError: () => toast.error("Failed to save settings")
  });

  const testAlert = useMutation({
    mutationFn: () => apiPost("/telegram/test", {
      bot_token: botToken,
      channel_id: channelId
    }),
    onSuccess: () => {
      setTestStatus("success");
      toast.success("✅ Test message sent to Telegram!");
    },
    onError: () => {
      setTestStatus("error");
      toast.error("❌ Failed to send test message.");
    }
  });

  if (isLoading) {
    return (
      <div className="rounded-md border border-slate-800 bg-[#111827] p-4">
        <div className="flex items-center gap-2 text-slate-400">
          <Loader2 className="size-4 animate-spin" />
          Loading...
        </div>
      </div>
    );
  }

  return (
    <div className="rounded-md border border-slate-800 bg-[#111827] p-4">
      <h3 className="flex items-center gap-2 text-sm font-semibold text-slate-100">
        <Send className="size-4 text-sky-400" />  {/* ✅ Telegram → Send */}
        Telegram Alerts
      </h3>
      <p className="text-[11px] text-slate-500">Get signal alerts on your Telegram channel</p>

      <div className="mt-4 space-y-3">
        <div>
          <Label className="text-[11px] text-slate-300">Bot Token</Label>
          <Input
            value={botToken}
            onChange={(e) => setBotToken(e.target.value)}
            placeholder="123456:ABCdef..."
            className="mt-1 border-slate-700 bg-slate-950 text-slate-100 font-mono text-xs"
          />
        </div>

        <div>
          <Label className="text-[11px] text-slate-300">Channel ID</Label>
          <Input
            value={channelId}
            onChange={(e) => setChannelId(e.target.value)}
            placeholder="-100123456789"
            className="mt-1 border-slate-700 bg-slate-950 text-slate-100 font-mono text-xs"
          />
        </div>

        <div className="flex items-center gap-2">
          <Checkbox
            id="telegram-enabled"
            checked={enabled}
            onCheckedChange={(checked) => setEnabled(!!checked)}
          />
          <Label htmlFor="telegram-enabled" className="text-[11px] text-slate-300 cursor-pointer">
            Enable Alerts
          </Label>
        </div>

        <div className="flex gap-2">
          <Button
            size="sm"
            variant="outline"
            onClick={() => testAlert.mutate()}
            disabled={!botToken || !channelId || testAlert.isPending}
            className="border-slate-700"
          >
            {testAlert.isPending ? "Sending..." : "Test Alert"}
          </Button>
          <Button
            size="sm"
            onClick={() => saveSettings.mutate()}
            disabled={saveSettings.isPending}
            className="bg-sky-600 hover:bg-sky-700"
          >
            Save
          </Button>
        </div>

        {testStatus === "success" && (
          <div className="flex items-center gap-2 text-emerald-400 text-[11px]">
            <CheckCircle2 className="size-4" />
            Test message sent!
          </div>
        )}
        {testStatus === "error" && (
          <div className="flex items-center gap-2 text-rose-400 text-[11px]">
            <AlertCircle className="size-4" />
            Failed to send. Check credentials.
          </div>
        )}
      </div>
    </div>
  );
}
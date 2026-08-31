import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Check, Coins, HandCoins, Loader2, LogOut, ShieldCheck, Sparkles, TicketPercent } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Toaster } from "@/components/ui/sonner";
import { apiGet, apiPost } from "@/lib/api";
import { ME_KEY, errorText, useLogout, useMe } from "@/hooks/useAuth";
import { rupees } from "@/lib/types";
import { loadRazorpayCheckout } from "@/lib/razorpay";
import type { BillingStatus, CouponPreview, OrderResponse, Plan, SubscriptionInfo } from "@/lib/types";
import { cn } from "@/lib/utils";

export default function Subscribe() {
  const { data: me } = useMe();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const logout = useLogout();
  const [couponCode, setCouponCode] = useState("");
  const [coupon, setCoupon] = useState<CouponPreview | null>(null);

  const billing = useQuery({
    queryKey: ["billing", "status"],
    queryFn: () => apiGet<BillingStatus>("/billing/status"),
    retry: false,
  });

  const verify = useMutation({
    mutationFn: (body: {
      plan_id: string;
      razorpay_order_id: string;
      razorpay_payment_id: string;
      razorpay_signature: string;
    }) => apiPost<SubscriptionInfo>("/billing/verify", body),
    onSuccess: async () => {
      toast.success("Payment confirmed — welcome aboard.");
      await qc.invalidateQueries({ queryKey: ME_KEY });
      navigate("/", { replace: true });
    },
    onError: (err) => toast.error(errorText(err, "We could not verify that payment.")),
  });

  const couponPreview = useMutation({
    mutationFn: (code: string) => apiPost<CouponPreview>("/billing/coupon", { coupon_code: code }),
    onSuccess: (value) => {
      setCoupon(value);
      setCouponCode(value.code);
      toast.success(`${value.code} applied · ${value.discount_pct}% off eligible plans`);
    },
    onError: (err) => {
      setCoupon(null);
      toast.error(errorText(err, "Coupon could not be applied."));
    },
  });

  const checkout = useMutation({
    mutationFn: (plan: Plan) => {
      const eligible = coupon && (!coupon.eligible_plan_ids.length || coupon.eligible_plan_ids.includes(plan.id));
      return apiPost<OrderResponse>("/billing/order", {
        plan_id: plan.id,
        coupon_code: eligible ? coupon.code : undefined,
      });
    },
    onSuccess: async (order) => {
      const ready = await loadRazorpayCheckout();
      if (!ready || !window.Razorpay) {
        toast.error("Could not load the payment window. Check your connection and retry.");
        return;
      }
      const rz = new window.Razorpay({
        key: order.key_id,
        amount: order.amount,
        currency: order.currency,
        name: "Bitcoin Paper Terminal",
        description: `${order.plan.name} · ${order.plan.days} days`,
        order_id: order.order_id,
        prefill: { email: me?.email ?? "", name: me?.username ?? "" },
        theme: { color: "#eab308" },
        handler: (res) =>
          verify.mutate({
            plan_id: order.plan.id,
            razorpay_order_id: res.razorpay_order_id,
            razorpay_payment_id: res.razorpay_payment_id,
            razorpay_signature: res.razorpay_signature,
          }),
        modal: { ondismiss: () => toast.message("Payment window closed.") },
      });
      rz.open();
    },
    onError: (err) => toast.error(errorText(err, "Could not start checkout.")),
  });

  const data = billing.data;
  const sub = data?.subscription;

  return (
    <div className="min-h-screen bg-[#0b0e14] p-4">
      <Toaster position="bottom-right" richColors />
      <div className="mx-auto max-w-5xl">
        <header className="mb-8 flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <div className="flex size-10 items-center justify-center rounded border border-amber-500/30 bg-amber-500/10">
              <Coins className="size-5 text-amber-400" />
            </div>
            <div className="leading-tight">
              <h1 className="text-sm font-semibold text-slate-100">Bitcoin Paper Terminal</h1>
              <p className="text-[11px] text-slate-500">
                Signed in as {me?.email ?? "—"}
                {me?.role === "admin" ? " · admin" : ""}
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            {me?.role === "admin" ? (
              <Button
                variant="outline"
                size="sm"
                onClick={() => navigate("/admin")}
                data-testid="go-admin-button"
                className="border-slate-700 text-slate-300"
              >
                <ShieldCheck className="size-3.5" />
                Admin
              </Button>
            ) : null}
            <Button
              variant="outline"
              size="sm"
              onClick={() => navigate("/affiliate")}
              data-testid="go-affiliate-button"
              className="border-slate-700 text-slate-300"
            >
              <HandCoins className="size-3.5" />
              Affiliate
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() => logout.mutate()}
              data-testid="logout-button"
              className="border-slate-700 text-slate-300"
            >
              <LogOut className="size-3.5" />
              Sign out
            </Button>
          </div>
        </header>

        <div className="mb-8 max-w-2xl">
          <h2 className="text-2xl font-semibold tracking-tight text-slate-100">
            Unlock the live scalping terminal
          </h2>
          <p className="mt-2 text-[12px] leading-relaxed text-slate-400" data-testid="paywall-message">
            The terminal needs an active subscription. You get the 12-confirmation signal engine,
            automated paper trading with break-even, partial take-profit and trailing stops, AI trade
            explanations, voice announcements and strategy backtesting. The built-in account is simulated;
            optional MT5 execution is configured separately and no signal is a guarantee.
          </p>
          {sub && sub.status !== "none" ? (
            <p className="mt-3 rounded border border-slate-800 bg-slate-900/60 p-2.5 text-[11px] text-slate-300" data-testid="current-subscription">
              Current plan: {sub.plan_name ?? "—"} · status {sub.status}
              {sub.days_left ? ` · ${sub.days_left} day(s) left` : ""}
            </p>
          ) : null}
        </div>

        <form
          className="mb-5 flex max-w-xl flex-wrap items-end gap-2 rounded-md border border-slate-800 bg-[#111827] p-3"
          data-testid="coupon-form"
          onSubmit={(e) => {
            e.preventDefault();
            couponPreview.mutate(couponCode.trim().toUpperCase());
          }}
        >
          <div className="min-w-56 flex-1">
            <label htmlFor="coupon-code" className="flex items-center gap-1 text-[11px] text-slate-300">
              <TicketPercent className="size-3.5 text-amber-400" /> Coupon code
            </label>
            <Input
              id="coupon-code"
              value={couponCode}
              onChange={(e) => { setCouponCode(e.target.value.toUpperCase()); setCoupon(null); }}
              placeholder="SAVE20"
              data-testid="coupon-code-input"
              className="mt-1 border-slate-700 bg-slate-950 text-slate-100 uppercase"
            />
          </div>
          <Button type="submit" size="sm" disabled={!couponCode.trim() || couponPreview.isPending} data-testid="apply-coupon-button">
            Apply coupon
          </Button>
          {coupon ? (
            <p className="w-full text-[11px] text-emerald-300" data-testid="coupon-applied-message">
              {coupon.code}: {coupon.discount_pct}% off · {coupon.claims_remaining} claim(s) remaining
            </p>
          ) : null}
        </form>

        {billing.isLoading ? (
          <div className="flex items-center gap-2 text-[12px] text-slate-400">
            <Loader2 className="size-4 animate-spin" /> Loading plans…
          </div>
        ) : (
          <div className="grid gap-4 md:grid-cols-3" data-testid="plan-grid">
            {(data?.plans ?? []).map((plan) => (
              (() => {
                const eligible = coupon && (!coupon.eligible_plan_ids.length || coupon.eligible_plan_ids.includes(plan.id));
                const finalPrice = eligible ? plan.price_inr * (1 - coupon.discount_pct / 100) : plan.price_inr;
                return (
              <div
                key={plan.id}
                className={cn(
                  "flex flex-col rounded-md border bg-[#111827] p-4 transition-colors duration-200",
                  plan.highlight
                    ? "border-amber-500/60 shadow-[0_0_40px_-16px_rgba(234,179,8,0.6)]"
                    : "border-slate-800 hover:border-slate-700",
                )}
                data-testid={`plan-card-${plan.id}`}
              >
                {plan.highlight ? (
                  <span className="mb-2 flex w-fit items-center gap-1 rounded bg-amber-500/15 px-1.5 py-0.5 text-[9px] font-semibold tracking-wider text-amber-300 uppercase">
                    <Sparkles className="size-2.5" /> Most popular
                  </span>
                ) : null}
                <h3 className="text-sm font-semibold text-slate-100">{plan.name}</h3>
                <div className="mt-1 flex items-baseline gap-1">
                  <span className="text-2xl font-bold tabular-nums text-amber-300" data-testid={`plan-price-${plan.id}`}>
                    {rupees(finalPrice)}
                  </span>
                  <span className="text-[11px] text-slate-500">/ {plan.days} days</span>
                </div>
                {eligible ? (
                  <p className="text-[10px] text-slate-500" data-testid={`plan-discount-${plan.id}`}>
                    <span className="line-through">{rupees(plan.price_inr)}</span> · {coupon.code} applied
                  </p>
                ) : null}
                <ul className="mt-3 flex-1 space-y-1.5">
                  {plan.features.map((f) => (
                    <li key={f} className="flex items-start gap-1.5 text-[11px] text-slate-400">
                      <Check className="mt-0.5 size-3 shrink-0 text-emerald-400" />
                      {f}
                    </li>
                  ))}
                </ul>
                <Button
                  className="mt-4 w-full"
                  disabled={!data?.razorpay_enabled || checkout.isPending || verify.isPending}
                  onClick={() => checkout.mutate(plan)}
                  data-testid={`subscribe-button-${plan.id}`}
                >
                  {checkout.isPending || verify.isPending ? (
                    <Loader2 className="size-4 animate-spin" />
                  ) : null}
                  {data?.razorpay_enabled ? `Subscribe · ${rupees(finalPrice)}` : "Payment unavailable"}
                </Button>
              </div>
                );
              })()
            ))}
          </div>
        )}

        <p
          className={cn(
            "mt-6 rounded border p-3 text-[11px] leading-relaxed",
            data?.razorpay_enabled
              ? "border-slate-800 bg-slate-900/50 text-slate-400"
              : "border-amber-900/40 bg-amber-950/20 text-amber-200/80",
          )}
          data-testid="billing-message"
        >
          {data?.message ??
            "Online payment is not configured yet — ask an admin to enable Razorpay or grant access manually."}
        </p>
      </div>
    </div>
  );
}

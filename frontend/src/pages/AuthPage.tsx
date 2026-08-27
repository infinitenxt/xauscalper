import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { Coins, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Toaster } from "@/components/ui/sonner";
import { errorText, useLogin, useRegister } from "@/hooks/useAuth";
import { apiGet } from "@/lib/api";
import type { RegistrationPolicy } from "@/lib/types";
import { toast } from "sonner";

interface Props {
  mode: "login" | "register";
}

export default function AuthPage({ mode }: Props) {
  const isLogin = mode === "login";
  const navigate = useNavigate();
  const location = useLocation();
  const login = useLogin();
  const register = useRegister();
  const [email, setEmail] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [referralCode, setReferralCode] = useState(
    () => new URLSearchParams(location.search).get("ref")?.toUpperCase() ?? "",
  );
  const policy = useQuery({
    queryKey: ["registration-policy"],
    queryFn: () => apiGet<RegistrationPolicy>("/auth/registration-policy"),
    retry: false,
  });
  const pending = login.isPending || register.isPending;

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    const from = (location.state as { from?: string } | null)?.from;
    const done = (message: string, subscribed: boolean) => {
      toast.success(message);
      navigate(subscribed ? (from && from !== "/login" ? from : "/") : "/subscribe", { replace: true });
    };
    if (isLogin) {
      login.mutate(
        { email, password },
        {
          onSuccess: (res) => done(res.message, res.user.subscribed),
          onError: (err) => toast.error(errorText(err, "Could not sign in.")),
        },
      );
    } else {
      register.mutate(
        { email, username, password, referral_code: referralCode.trim() || undefined },
        {
          onSuccess: (res) => done(res.message, res.user.subscribed),
          onError: (err) => toast.error(errorText(err, "Could not create the account.")),
        },
      );
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-[#0b0e14] p-4">
      <Toaster position="bottom-right" richColors />
      <div className="w-full max-w-sm">
        <div className="mb-6 flex items-center gap-3">
          <div className="flex size-10 items-center justify-center rounded border border-amber-500/30 bg-amber-500/10">
            <Coins className="size-5 text-amber-400" />
          </div>
          <div className="leading-tight">
            <h1 className="text-sm font-semibold text-slate-100">Gold Paper Terminal</h1>
            <p className="text-[11px] text-slate-500">Educational XAUUSDT scalping intelligence</p>
          </div>
        </div>

        <form
          onSubmit={submit}
          className="space-y-4 rounded-md border border-slate-800 bg-[#111827] p-5"
          data-testid={isLogin ? "login-form" : "register-form"}
        >
          <div>
            <h2 className="text-lg font-semibold text-slate-100">
              {isLogin ? "Sign in" : "Create your account"}
            </h2>
            <p className="mt-0.5 text-[11px] text-slate-500">
              {isLogin
                ? "One active login per account — signing in here signs out your other device."
                : policy.data?.registration_open === false
                  ? "New registrations are currently closed by the administrator."
                  : policy.data?.invite_mode_enabled === false
                    ? "Registration is open. Add a referral code if another member invited you."
                    : "Sign-up is invite-only — use the email address the admin invited. A subscription unlocks the live terminal."}
            </p>
          </div>

          <div>
            <Label htmlFor="auth-email" className="text-[11px] text-slate-300">Email</Label>
            <Input
              id="auth-email"
              type="email"
              required
              autoComplete="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              data-testid="auth-email-input"
              className="mt-1 border-slate-700 bg-slate-950 text-slate-100"
              placeholder={isLogin ? "you@example.com" : "the email you were invited with"}
            />
          </div>

          {!isLogin ? (
            <div>
              <Label htmlFor="auth-username" className="text-[11px] text-slate-300">Username</Label>
              <Input
                id="auth-username"
                required
                minLength={3}
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                data-testid="auth-username-input"
                className="mt-1 border-slate-700 bg-slate-950 text-slate-100"
                placeholder="goldscalper"
              />
            </div>
          ) : null}

          {!isLogin ? (
            <div>
              <Label htmlFor="auth-referral-code" className="text-[11px] text-slate-300">
                Referral code <span className="text-slate-600">(optional)</span>
              </Label>
              <Input
                id="auth-referral-code"
                value={referralCode}
                onChange={(e) => setReferralCode(e.target.value.toUpperCase())}
                data-testid="auth-referral-code-input"
                className="mt-1 border-slate-700 bg-slate-950 text-slate-100 uppercase"
                placeholder="GOLDXXXXXX"
              />
            </div>
          ) : null}

          <div>
            <Label htmlFor="auth-password" className="text-[11px] text-slate-300">Password</Label>
            <Input
              id="auth-password"
              type="password"
              required
              minLength={isLogin ? 1 : 8}
              autoComplete={isLogin ? "current-password" : "new-password"}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              data-testid="auth-password-input"
              className="mt-1 border-slate-700 bg-slate-950 text-slate-100"
              placeholder={isLogin ? "Your password" : "At least 8 characters"}
            />
          </div>

          <Button type="submit" disabled={pending} className="w-full" data-testid="auth-submit-button">
            {pending ? <Loader2 className="size-4 animate-spin" /> : null}
            {isLogin ? "Sign in" : "Create account"}
          </Button>

          <p className="text-center text-[11px] text-slate-500">
            {isLogin ? "No account yet? " : "Already registered? "}
            <Link
              to={isLogin ? "/register" : "/login"}
              className="text-amber-400 transition-colors duration-150 hover:text-amber-300"
              data-testid="auth-switch-link"
            >
              {isLogin ? "Create one" : "Sign in"}
            </Link>
          </p>
        </form>

        <p className="mt-4 text-center text-[10px] leading-relaxed text-slate-600">
          Educational paper trading only. No real orders are placed and no signal is a guarantee.
        </p>
      </div>
    </div>
  );
}

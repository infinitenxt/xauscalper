import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  ArrowLeft,
  CreditCard,
  Globe,
  KeyRound,
  Layers,
  LogOut,
  MailPlus,
  Monitor,
  Users,
} from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Toaster } from "@/components/ui/sonner";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import ChangePasswordDialog from "@/components/ChangePasswordDialog";
import { apiDelete, apiGet, apiPatch, apiPost, apiPut } from "@/lib/api";
import { errorText, useLogout, useMe } from "@/hooks/useAuth";
import { rupees } from "@/lib/types";
import type {
  AdminStats,
  InviteRow,
  PaymentRow,
  Plan,
  SessionRow,
  SiteSettings,
  UserPublic,
} from "@/lib/types";
import { cn } from "@/lib/utils";

export default function Admin() {
  const { data: me } = useMe();
  const navigate = useNavigate();
  const logout = useLogout();
  const qc = useQueryClient();
  const refresh = () => {
    void qc.invalidateQueries({ queryKey: ["admin"] });
  };

  const stats = useQuery({ queryKey: ["admin", "stats"], queryFn: () => apiGet<AdminStats>("/admin/stats"), refetchInterval: 20000 });
  const [q, setQ] = useState("");
  const users = useQuery({
    queryKey: ["admin", "users", q],
    queryFn: () => apiGet<UserPublic[]>(`/admin/users?q=${encodeURIComponent(q)}`),
  });
  const plans = useQuery({ queryKey: ["admin", "plans"], queryFn: () => apiGet<Plan[]>("/admin/plans") });
  const site = useQuery({ queryKey: ["admin", "site"], queryFn: () => apiGet<SiteSettings>("/admin/site-settings") });
  const sessions = useQuery({ queryKey: ["admin", "sessions"], queryFn: () => apiGet<SessionRow[]>("/admin/sessions") });
  const payments = useQuery({ queryKey: ["admin", "payments"], queryFn: () => apiGet<PaymentRow[]>("/admin/payments") });
  const invites = useQuery({ queryKey: ["admin", "invites"], queryFn: () => apiGet<InviteRow[]>("/admin/invites") });

  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteNote, setInviteNote] = useState("");

  const sendInvite = useMutation({
    mutationFn: (body: { email: string; note: string }) => apiPost<InviteRow>("/admin/invites", body),
    onSuccess: (row) => { toast.success(`${row.email} can now create an account`); setInviteEmail(""); setInviteNote(""); refresh(); },
    onError: (e) => toast.error(errorText(e)),
  });

  const revokeInvite = useMutation({
    mutationFn: (email: string) => apiDelete<{ message: string }>(`/admin/invites/${encodeURIComponent(email)}`),
    onSuccess: () => { toast.success("Invite revoked"); refresh(); },
    onError: (e) => toast.error(errorText(e)),
  });

  const resetPassword = useMutation({
    mutationFn: ({ id, password }: { id: string; password: string }) =>
      apiPost<{ message: string }>(`/admin/users/${id}/password`, { new_password: password }),
    onSuccess: (res) => { toast.success(res.message); refresh(); },
    onError: (e) => toast.error(errorText(e)),
  });

  const patchUser = useMutation({
    mutationFn: ({ id, body }: { id: string; body: { is_active?: boolean; role?: string } }) =>
      apiPatch<UserPublic>(`/admin/users/${id}`, body),
    onSuccess: () => { toast.success("User updated"); refresh(); },
    onError: (e) => toast.error(errorText(e)),
  });

  const grant = useMutation({
    mutationFn: ({ id, body }: { id: string; body: { plan_id?: string; days?: number; revoke?: boolean } }) =>
      apiPost<UserPublic>(`/admin/users/${id}/subscription`, body),
    onSuccess: () => { toast.success("Subscription updated"); refresh(); },
    onError: (e) => toast.error(errorText(e)),
  });

  const removeUser = useMutation({
    mutationFn: (id: string) => apiDelete<{ message: string }>(`/admin/users/${id}`),
    onSuccess: () => { toast.success("User deleted"); refresh(); },
    onError: (e) => toast.error(errorText(e)),
  });

  const revokeDevice = useMutation({
    mutationFn: (id: string) => apiDelete<{ message: string }>(`/admin/sessions/${id}`),
    onSuccess: () => { toast.success("Device signed out"); refresh(); },
    onError: (e) => toast.error(errorText(e)),
  });

  const patchPlan = useMutation({
    mutationFn: ({ id, body }: { id: string; body: Partial<Plan> }) =>
      apiPatch<Plan>(`/admin/plans/${id}`, body),
    onSuccess: () => { toast.success("Plan updated"); refresh(); },
    onError: (e) => toast.error(errorText(e)),
  });

  const saveKeys = useMutation({
    mutationFn: (body: { razorpay_key_id: string; razorpay_key_secret?: string }) =>
      apiPut<SiteSettings>("/admin/payment-keys", body),
    onSuccess: () => { toast.success("Razorpay keys saved"); refresh(); },
    onError: (e) => toast.error(errorText(e)),
  });

  const clearKeys = useMutation({
    mutationFn: () => apiDelete<SiteSettings>("/admin/payment-keys"),
    onSuccess: () => { toast.success("Razorpay keys cleared"); refresh(); },
    onError: (e) => toast.error(errorText(e)),
  });

  const saveSite = useMutation({
    mutationFn: (body: Partial<SiteSettings>) => apiPut<SiteSettings>("/admin/site-settings", body),
    onSuccess: () => { toast.success("Website settings saved"); refresh(); },
    onError: (e) => toast.error(errorText(e)),
  });

  // local editors
  const [keyId, setKeyId] = useState("");
  const [keySecret, setKeySecret] = useState("");
  const [siteForm, setSiteForm] = useState({
    site_name: "", tagline: "", support_email: "", trial_days: 0,
    allow_registration: true, maintenance_mode: false,
  });
  useEffect(() => {
    if (!site.data) return;
    setKeyId(site.data.razorpay_key_id);
    setSiteForm({
      site_name: site.data.site_name,
      tagline: site.data.tagline,
      support_email: site.data.support_email,
      trial_days: site.data.trial_days,
      allow_registration: site.data.allow_registration,
      maintenance_mode: site.data.maintenance_mode,
    });
  }, [site.data]);

  const s = stats.data;

  return (
    <div className="min-h-screen bg-[#0b0e14] p-4">
      <Toaster position="bottom-right" richColors />
      <div className="mx-auto max-w-[1500px] space-y-4">
        <header className="flex flex-wrap items-center justify-between gap-3 rounded-md border border-slate-800 bg-[#111827] p-4">
          <div>
            <h1 className="text-sm font-semibold text-slate-100">Admin panel</h1>
            <p className="text-[11px] text-slate-500">Signed in as {me?.username} · {me?.email}</p>
          </div>
          <div className="flex items-center gap-2">
            <ChangePasswordDialog />
            <Button variant="outline" size="sm" onClick={() => navigate("/")} data-testid="back-to-terminal-button" className="border-slate-700 text-slate-300">
              <ArrowLeft className="size-3.5" /> Terminal
            </Button>
            <Button variant="outline" size="sm" onClick={() => logout.mutate()} data-testid="admin-logout-button" className="border-slate-700 text-slate-300">
              <LogOut className="size-3.5" /> Sign out
            </Button>
          </div>
        </header>

        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 lg:grid-cols-8" data-testid="admin-stats">
          {[
            ["Users", s?.users_total ?? "—"],
            ["Active", s?.users_active ?? "—"],
            ["Subscribers", s?.subscribers ?? "—"],
            ["Admins", s?.admins ?? "—"],
            ["Signed in", s?.signed_in_now ?? "—"],
            ["New (7d)", s?.new_users_7d ?? "—"],
            ["Invites", s?.invites_pending ?? "—"],
            ["Revenue", s ? rupees(s.revenue_inr) : "—"],
          ].map(([k, v]) => (
            <div key={String(k)} className="rounded border border-slate-800 bg-[#111827] p-3">
              <div className="text-[10px] uppercase tracking-wider text-slate-500">{k}</div>
              <div className="tabular-nums text-lg font-semibold text-amber-300">{v}</div>
            </div>
          ))}
        </div>

        <Tabs defaultValue="users">
          <TabsList className="bg-[#111827]">
            <TabsTrigger value="users" data-testid="tab-users"><Users className="size-3.5" /> Users</TabsTrigger>
            <TabsTrigger value="invites" data-testid="tab-invites"><MailPlus className="size-3.5" /> Invites</TabsTrigger>
            <TabsTrigger value="plans" data-testid="tab-plans"><Layers className="size-3.5" /> Plans</TabsTrigger>
            <TabsTrigger value="payments" data-testid="tab-payments"><CreditCard className="size-3.5" /> Payments</TabsTrigger>
            <TabsTrigger value="keys" data-testid="tab-keys"><KeyRound className="size-3.5" /> Razorpay</TabsTrigger>
            <TabsTrigger value="site" data-testid="tab-site"><Globe className="size-3.5" /> Website</TabsTrigger>
            <TabsTrigger value="devices" data-testid="tab-devices"><Monitor className="size-3.5" /> Devices</TabsTrigger>
          </TabsList>

          {/* ---------------------------------------------------------- users */}
          <TabsContent value="users" className="rounded-md border border-slate-800 bg-[#111827] p-4">
            <div className="mb-3 flex items-center gap-2">
              <Input
                value={q}
                onChange={(e) => setQ(e.target.value)}
                placeholder="Search email or username"
                data-testid="user-search-input"
                className="max-w-xs border-slate-700 bg-slate-950 text-slate-100"
              />
              <span className="text-[11px] text-slate-500">{users.data?.length ?? 0} user(s)</span>
            </div>
            <Table data-testid="users-table">
              <TableHeader>
                <TableRow className="border-slate-800 hover:bg-transparent">
                  {["User", "Role", "Status", "Subscription", "Expires", "Actions"].map((h) => (
                    <TableHead key={h} className="h-8 text-[10px] uppercase tracking-wider text-slate-500">{h}</TableHead>
                  ))}
                </TableRow>
              </TableHeader>
              <TableBody>
                {(users.data ?? []).map((u) => (
                  <TableRow key={u.id} className="border-slate-800 text-[11px]" data-testid="user-row">
                    <TableCell>
                      <div className="text-slate-200">{u.username}</div>
                      <div className="text-[10px] text-slate-500">{u.email}</div>
                    </TableCell>
                    <TableCell>
                      <span className={cn("rounded px-1.5 py-0.5 text-[10px] font-semibold", u.role === "admin" ? "bg-amber-950 text-amber-300" : "bg-slate-800 text-slate-400")}>
                        {u.role}
                      </span>
                    </TableCell>
                    <TableCell>
                      <span className={cn("rounded px-1.5 py-0.5 text-[10px]", u.is_active ? "bg-emerald-950 text-emerald-300" : "bg-rose-950 text-rose-300")}>
                        {u.is_active ? "active" : "disabled"}
                      </span>
                    </TableCell>
                    <TableCell>
                      <span className={cn("rounded px-1.5 py-0.5 text-[10px]", u.subscribed ? "bg-emerald-950 text-emerald-300" : "bg-slate-800 text-slate-400")} data-testid="user-subscription-state">
                        {u.subscribed ? (u.subscription.plan_name ?? "active") : "none"}
                      </span>
                    </TableCell>
                    <TableCell className="text-slate-400">
                      {u.subscription.expires_at ? `${u.subscription.days_left}d left` : "—"}
                    </TableCell>
                    <TableCell>
                      <div className="flex flex-wrap gap-1">
                        {(plans.data ?? []).filter((p) => p.is_active).map((p) => (
                          <Button key={p.id} size="sm" variant="outline" className="h-6 border-slate-700 px-1.5 text-[10px] text-slate-300"
                            onClick={() => grant.mutate({ id: u.id, body: { plan_id: p.id } })}
                            data-testid={`grant-${p.id}-button`}>
                            + {p.name}
                          </Button>
                        ))}
                        <Button size="sm" variant="outline" className="h-6 border-slate-700 px-1.5 text-[10px] text-slate-300"
                          onClick={() => grant.mutate({ id: u.id, body: { days: 7 } })} data-testid="grant-7d-button">
                          + 7d
                        </Button>
                        <Button size="sm" variant="outline" className="h-6 border-slate-700 px-1.5 text-[10px] text-rose-300"
                          onClick={() => grant.mutate({ id: u.id, body: { revoke: true } })} data-testid="revoke-subscription-button">
                          revoke
                        </Button>
                        <Button size="sm" variant="outline" className="h-6 border-slate-700 px-1.5 text-[10px] text-slate-300"
                          onClick={() => patchUser.mutate({ id: u.id, body: { is_active: !u.is_active } })} data-testid="toggle-active-button">
                          {u.is_active ? "disable" : "enable"}
                        </Button>
                        <Button size="sm" variant="outline" className="h-6 border-slate-700 px-1.5 text-[10px] text-slate-300"
                          onClick={() => patchUser.mutate({ id: u.id, body: { role: u.role === "admin" ? "user" : "admin" } })} data-testid="toggle-role-button">
                          {u.role === "admin" ? "demote" : "promote"}
                        </Button>
                        <Button size="sm" variant="outline" className="h-6 border-slate-700 px-1.5 text-[10px] text-amber-300"
                          onClick={() => {
                            const pw = window.prompt(`New password for ${u.email} (min 8 characters)`);
                            if (pw && pw.length >= 8) resetPassword.mutate({ id: u.id, password: pw });
                            else if (pw !== null) toast.error("Password must be at least 8 characters.");
                          }} data-testid="reset-password-button">
                          reset password
                        </Button>
                        <Button size="sm" variant="outline" className="h-6 border-slate-700 px-1.5 text-[10px] text-rose-300"
                          onClick={() => removeUser.mutate(u.id)} data-testid="delete-user-button">
                          delete
                        </Button>
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </TabsContent>

          {/* -------------------------------------------------------- invites */}
          <TabsContent value="invites" className="rounded-md border border-slate-800 bg-[#111827] p-4">
            <div className="space-y-4" data-testid="invites-panel">
              <div className="rounded border border-amber-900/40 bg-amber-950/20 p-2.5 text-[11px] text-amber-200/80">
                Sign-up is invite-only. Only the emails listed here can create an account — anyone
                else gets turned away at registration.
              </div>
              <form
                className="flex flex-wrap items-end gap-2"
                data-testid="invite-form"
                onSubmit={(e) => { e.preventDefault(); sendInvite.mutate({ email: inviteEmail.trim(), note: inviteNote.trim() }); }}
              >
                <div>
                  <Label className="text-[11px] text-slate-300">Email to invite</Label>
                  <Input type="email" required value={inviteEmail} onChange={(e) => setInviteEmail(e.target.value)}
                    placeholder="trader@example.com" data-testid="invite-email-input"
                    className="mt-1 w-64 border-slate-700 bg-slate-950 text-slate-100" />
                </div>
                <div>
                  <Label className="text-[11px] text-slate-300">Note (optional)</Label>
                  <Input value={inviteNote} onChange={(e) => setInviteNote(e.target.value)}
                    placeholder="Beta tester" data-testid="invite-note-input"
                    className="mt-1 w-56 border-slate-700 bg-slate-950 text-slate-100" />
                </div>
                <Button type="submit" size="sm" disabled={sendInvite.isPending} data-testid="invite-submit-button">
                  <MailPlus className="size-3.5" /> Add invite
                </Button>
              </form>

              {(invites.data ?? []).length === 0 ? (
                <p className="text-[12px] text-slate-400" data-testid="invites-empty">
                  No invites yet. Add an email above and that person can register at /register.
                </p>
              ) : (
                <Table data-testid="invites-table">
                  <TableHeader>
                    <TableRow className="border-slate-800 hover:bg-transparent">
                      {["Email", "Note", "State", "Invited by", "Added", "Action"].map((h) => (
                        <TableHead key={h} className="h-8 text-[10px] uppercase tracking-wider text-slate-500">{h}</TableHead>
                      ))}
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {(invites.data ?? []).map((i) => (
                      <TableRow key={i.email} className="border-slate-800 text-[11px]" data-testid="invite-row">
                        <TableCell className="text-slate-200">{i.email}</TableCell>
                        <TableCell className="text-slate-400">{i.note || "—"}</TableCell>
                        <TableCell>
                          <span className={cn("rounded px-1.5 py-0.5 text-[10px]", i.used ? "bg-slate-800 text-slate-400" : "bg-emerald-950 text-emerald-300")} data-testid="invite-state">
                            {i.used ? "used" : "pending"}
                          </span>
                        </TableCell>
                        <TableCell className="text-[10px] text-slate-500">{i.invited_by || "—"}</TableCell>
                        <TableCell className="text-slate-400">{i.created_at ? new Date(i.created_at).toLocaleString() : "—"}</TableCell>
                        <TableCell>
                          <Button size="sm" variant="outline" className="h-6 border-slate-700 px-1.5 text-[10px] text-rose-300"
                            onClick={() => revokeInvite.mutate(i.email)} data-testid="revoke-invite-button">
                            revoke
                          </Button>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              )}
            </div>
          </TabsContent>

          {/* ---------------------------------------------------------- plans */}
          <TabsContent value="plans" className="rounded-md border border-slate-800 bg-[#111827] p-4">
            <div className="grid gap-3 md:grid-cols-3" data-testid="admin-plans">
              {(plans.data ?? []).map((p) => (
                <div key={p.id} className="space-y-2 rounded border border-slate-800 bg-slate-950/40 p-3">
                  <div className="flex items-center justify-between">
                    <h3 className="text-sm font-semibold text-slate-100">{p.name}</h3>
                    <span className="text-[10px] text-slate-500">{p.id}</span>
                  </div>
                  <div>
                    <Label className="text-[10px] text-slate-400">Price (INR)</Label>
                    <Input type="number" defaultValue={p.price_inr} data-testid={`plan-price-${p.id}`}
                      onBlur={(e) => { const v = Number(e.target.value); if (v !== p.price_inr) patchPlan.mutate({ id: p.id, body: { price_inr: v } }); }}
                      className="mt-1 border-slate-700 bg-slate-950 text-slate-100" />
                  </div>
                  <div>
                    <Label className="text-[10px] text-slate-400">Days</Label>
                    <Input type="number" defaultValue={p.days} data-testid={`plan-days-${p.id}`}
                      onBlur={(e) => { const v = Number(e.target.value); if (v !== p.days) patchPlan.mutate({ id: p.id, body: { days: v } }); }}
                      className="mt-1 border-slate-700 bg-slate-950 text-slate-100" />
                  </div>
                  <div className="flex items-center gap-4">
                    <label className="flex items-center gap-2 text-[11px] text-slate-300">
                      <Checkbox checked={p.is_active} data-testid={`plan-active-${p.id}`}
                        onCheckedChange={(v) => patchPlan.mutate({ id: p.id, body: { is_active: Boolean(v) } })} />
                      Active
                    </label>
                    <label className="flex items-center gap-2 text-[11px] text-slate-300">
                      <Checkbox checked={p.highlight} data-testid={`plan-highlight-${p.id}`}
                        onCheckedChange={(v) => patchPlan.mutate({ id: p.id, body: { highlight: Boolean(v) } })} />
                      Featured
                    </label>
                  </div>
                  <ul className="space-y-0.5">
                    {p.features.map((f) => <li key={f} className="text-[10px] text-slate-500">· {f}</li>)}
                  </ul>
                </div>
              ))}
            </div>
          </TabsContent>

          {/* ------------------------------------------------------- payments */}
          <TabsContent value="payments" className="rounded-md border border-slate-800 bg-[#111827] p-4">
            {(payments.data ?? []).length === 0 ? (
              <p className="text-[12px] text-slate-400" data-testid="payments-empty">
                No payments recorded yet. Orders appear here as soon as Razorpay checkout is used.
              </p>
            ) : (
              <Table data-testid="payments-table">
                <TableHeader>
                  <TableRow className="border-slate-800 hover:bg-transparent">
                    {["User", "Plan", "Amount", "Status", "Order", "Payment"].map((h) => (
                      <TableHead key={h} className="h-8 text-[10px] uppercase tracking-wider text-slate-500">{h}</TableHead>
                    ))}
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {(payments.data ?? []).map((p) => (
                    <TableRow key={p.id} className="border-slate-800 text-[11px]" data-testid="payment-row">
                      <TableCell className="text-slate-300">{p.email}</TableCell>
                      <TableCell className="text-slate-300">{p.plan_name}</TableCell>
                      <TableCell className="tabular-nums text-slate-200">{rupees(p.amount_inr)}</TableCell>
                      <TableCell>
                        <span className={cn("rounded px-1.5 py-0.5 text-[10px]", p.status === "paid" ? "bg-emerald-950 text-emerald-300" : "bg-slate-800 text-slate-400")}>{p.status}</span>
                      </TableCell>
                      <TableCell className="text-[10px] text-slate-500">{p.order_id ?? "—"}</TableCell>
                      <TableCell className="text-[10px] text-slate-500">{p.payment_id ?? "—"}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </TabsContent>

          {/* ------------------------------------------------------- razorpay */}
          <TabsContent value="keys" className="rounded-md border border-slate-800 bg-[#111827] p-4">
            <div className="max-w-xl space-y-3">
              <div className={cn("rounded border p-2.5 text-[11px]", site.data?.razorpay_enabled ? "border-emerald-800/50 bg-emerald-950/20 text-emerald-200" : "border-amber-900/40 bg-amber-950/20 text-amber-200/80")} data-testid="razorpay-state">
                {site.data?.razorpay_enabled
                  ? "Razorpay is configured — paid checkout is live for all users."
                  : "Razorpay is not configured. Users cannot pay online; grant access manually from the Users tab until keys are saved."}
              </div>
              <div>
                <Label className="text-[11px] text-slate-300">Key ID</Label>
                <Input value={keyId} onChange={(e) => setKeyId(e.target.value)} placeholder="rzp_test_xxxxxxxx"
                  data-testid="razorpay-key-id-input" className="mt-1 border-slate-700 bg-slate-950 text-slate-100" />
              </div>
              <div>
                <Label className="text-[11px] text-slate-300">Key Secret</Label>
                <Input type="password" value={keySecret} onChange={(e) => setKeySecret(e.target.value)}
                  placeholder={site.data?.razorpay_key_secret_set ? "•••••••• (saved — type to replace)" : "Your Razorpay key secret"}
                  data-testid="razorpay-key-secret-input" className="mt-1 border-slate-700 bg-slate-950 text-slate-100" />
                <p className="mt-1 text-[10px] text-slate-600">
                  Write-only: the secret is never sent back to the browser after saving.
                </p>
              </div>
              <div className="flex gap-2">
                <Button size="sm" data-testid="save-razorpay-button" disabled={saveKeys.isPending}
                  onClick={() => saveKeys.mutate({ razorpay_key_id: keyId, razorpay_key_secret: keySecret || undefined })}>
                  Save keys
                </Button>
                <Button size="sm" variant="outline" className="border-slate-700 text-rose-300" data-testid="clear-razorpay-button"
                  onClick={() => { setKeySecret(""); clearKeys.mutate(); }}>
                  Clear keys
                </Button>
              </div>
              <p className="text-[10px] leading-relaxed text-slate-600">
                Get test keys from dashboard.razorpay.com → Settings → API Keys. Test mode keys start
                with <span className="text-slate-400">rzp_test_</span>. Amounts are charged in INR.
              </p>
            </div>
          </TabsContent>

          {/* --------------------------------------------------------- website */}
          <TabsContent value="site" className="rounded-md border border-slate-800 bg-[#111827] p-4">
            <div className="max-w-xl space-y-3" data-testid="site-settings-form">
              {([
                ["site_name", "Site name"],
                ["tagline", "Tagline"],
                ["support_email", "Support email"],
              ] as const).map(([key, label]) => (
                <div key={key}>
                  <Label className="text-[11px] text-slate-300">{label}</Label>
                  <Input value={siteForm[key]} onChange={(e) => setSiteForm((f) => ({ ...f, [key]: e.target.value }))}
                    data-testid={`site-${key.replace(/_/g, "-")}-input`} className="mt-1 border-slate-700 bg-slate-950 text-slate-100" />
                </div>
              ))}
              <div>
                <Label className="text-[11px] text-slate-300">Free trial days on sign-up</Label>
                <Input type="number" value={siteForm.trial_days}
                  onChange={(e) => setSiteForm((f) => ({ ...f, trial_days: Number(e.target.value) }))}
                  data-testid="site-trial-days-input" className="mt-1 border-slate-700 bg-slate-950 text-slate-100" />
                <p className="mt-1 text-[10px] text-slate-600">0 means new users must subscribe before the terminal unlocks.</p>
              </div>
              <label className="flex items-center gap-2 text-[11px] text-slate-300">
                <Checkbox checked={siteForm.allow_registration} data-testid="site-allow-registration"
                  onCheckedChange={(v) => setSiteForm((f) => ({ ...f, allow_registration: Boolean(v) }))} />
                Allow new registrations
              </label>
              <label className="flex items-center gap-2 text-[11px] text-slate-300">
                <Checkbox checked={siteForm.maintenance_mode} data-testid="site-maintenance-mode"
                  onCheckedChange={(v) => setSiteForm((f) => ({ ...f, maintenance_mode: Boolean(v) }))} />
                Maintenance mode banner
              </label>
              <Button size="sm" onClick={() => saveSite.mutate(siteForm)} disabled={saveSite.isPending} data-testid="save-site-button">
                Save website settings
              </Button>
            </div>
          </TabsContent>

          {/* --------------------------------------------------------- devices */}
          <TabsContent value="devices" className="rounded-md border border-slate-800 bg-[#111827] p-4">
            <p className="mb-3 text-[11px] text-slate-500">
              One active login per account. Signing in on a new device replaces the row below.
            </p>
            {(sessions.data ?? []).length === 0 ? (
              <p className="text-[12px] text-slate-400" data-testid="devices-empty">No active sessions.</p>
            ) : (
              <Table data-testid="devices-table">
                <TableHeader>
                  <TableRow className="border-slate-800 hover:bg-transparent">
                    {["User", "IP", "Device", "Signed in", "Action"].map((h) => (
                      <TableHead key={h} className="h-8 text-[10px] uppercase tracking-wider text-slate-500">{h}</TableHead>
                    ))}
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {(sessions.data ?? []).map((r) => (
                    <TableRow key={r.user_id} className="border-slate-800 text-[11px]" data-testid="device-row">
                      <TableCell className="text-slate-300">{r.username}<div className="text-[10px] text-slate-500">{r.email}</div></TableCell>
                      <TableCell className="text-slate-400">{r.ip || "—"}</TableCell>
                      <TableCell className="max-w-[380px] truncate text-[10px] text-slate-500">{r.user_agent || "—"}</TableCell>
                      <TableCell className="text-slate-400">{r.created_at ? new Date(r.created_at).toLocaleString() : "—"}</TableCell>
                      <TableCell>
                        <Button size="sm" variant="outline" className="h-6 border-slate-700 px-1.5 text-[10px] text-rose-300"
                          onClick={() => revokeDevice.mutate(r.user_id)} data-testid="revoke-device-button">
                          sign out
                        </Button>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </TabsContent>
        </Tabs>
      </div>
    </div>
  );
}

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, FlaskConical, Plus, ShieldCheck, XCircle } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { Badge, Button, Card, CardHeader, Dialog, ErrorState, Input, PageHeader, Skeleton, Tabs, TabsContent, TabsList, TabsTrigger, Textarea } from "@/components/ui/primitives";
import { api, authApi } from "@/lib/api";
import { dateTime, humanize, inr } from "@/lib/format";
import { ROLE_LABEL, useSession } from "@/stores/session";

type AnyObj = Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any

function useAdmin<T>(key: string, path: string) {
  return useQuery({ queryKey: ["admin", key], queryFn: () => api<T>(path) });
}

function Loading({ q, children }: { q: { isLoading: boolean; isError: boolean; error: unknown; refetch: () => unknown }; children: () => React.ReactNode }) {
  if (q.isLoading) return <Skeleton className="h-48" />;
  if (q.isError) return <ErrorState error={q.error} onRetry={() => void q.refetch()} />;
  return <>{children()}</>;
}

function Users() {
  const isAdmin = useSession((s) => s.has("admin"));
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["admin", "auth-users"], queryFn: authApi.users, enabled: isAdmin });
  const setRoles = useMutation({ mutationFn: (v: { id: string; roles: string[] }) => authApi.setRoles(v.id, v.roles), onSuccess: () => { toast.success("Roles updated (audited)"); void qc.invalidateQueries({ queryKey: ["admin", "auth-users"] }); }, onError: (e) => toast.error((e as Error).message) });
  if (!isAdmin) return <p className="text-sm text-subtle">User management requires the admin role.</p>;
  return (
    <Loading q={q}>{() => (
      <Card className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-muted/60 text-left text-xs uppercase text-subtle"><tr><th className="px-3 py-2">User</th><th className="px-3 py-2">Region</th><th className="px-3 py-2">Roles</th><th className="px-3 py-2">MFA</th><th className="px-3 py-2">Last sign-in</th></tr></thead>
          <tbody className="divide-y divide-border">
            {q.data!.map((u: AnyObj) => (
              <tr key={u.id}>
                <td className="px-3 py-2"><div className="font-medium">{u.full_name}</div><div className="text-xs text-subtle">{u.email}</div></td>
                <td className="px-3 py-2 capitalize">{u.region}</td>
                <td className="px-3 py-2">
                  <div className="flex flex-wrap gap-1">{Object.keys(ROLE_LABEL).map((r) => {
                    const on = (u.roles as string[]).includes(r);
                    return <button key={r} aria-pressed={on} onClick={() => setRoles.mutate({ id: u.id, roles: on ? u.roles.filter((x: string) => x !== r) : [...u.roles, r] })}
                      className={on ? "rounded-full bg-brand-soft px-2 py-0.5 text-xs text-brand" : "rounded-full border border-dashed border-border px-2 py-0.5 text-xs text-subtle"}>{ROLE_LABEL[r]}</button>;
                  })}</div>
                </td>
                <td className="px-3 py-2">{u.mfa_enabled ? <Badge tone="ok">On</Badge> : <Badge tone="warn">Off</Badge>}{u.locked && <Badge tone="danger">Locked</Badge>}</td>
                <td className="px-3 py-2 text-xs text-subtle">{dateTime(u.last_login_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
    )}</Loading>
  );
}

function Authority() {
  const qc = useQueryClient();
  const me = useSession((s) => s.user);
  const q = useAdmin<AnyObj[]>("authority", "/api/v1/admin/authority");
  const users = useAdmin<AnyObj[]>("users", "/api/v1/admin/users");
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({ user_id: "", line: "property", max_sum_insured: "", max_premium: "", regions: "west", reason: "" });
  const refresh = () => void qc.invalidateQueries({ queryKey: ["admin", "authority"] });
  const propose = useMutation({
    mutationFn: () => api("/api/v1/admin/authority", { method: "POST", json: { ...form, max_sum_insured: Number(form.max_sum_insured), max_premium: Number(form.max_premium), regions: form.regions.split(",").map((r) => r.trim()) } }),
    onSuccess: () => { toast.success("Change proposed. A second approver must check it."); setOpen(false); refresh(); }, onError: (e) => toast.error((e as Error).message),
  });
  const decide = useMutation({ mutationFn: (v: { id: string; approve: boolean }) => api(`/api/v1/admin/authority/${v.id}/decide`, { method: "POST", json: { approve: v.approve } }), onSuccess: () => { toast.success("Decision recorded"); refresh(); }, onError: (e) => toast.error((e as Error).message) });
  return (
    <Loading q={q}>{() => (
      <Card>
        <CardHeader title="Authority matrix" subtitle="Maker-checker: the proposer cannot approve. Approved limits become token claims and are re-validated on every quote." actions={<Button size="sm" onClick={() => setOpen(true)}><Plus className="h-4 w-4" aria-hidden /> Propose change</Button>} />
        <div className="overflow-x-auto"><table className="w-full text-sm">
          <thead className="bg-muted/60 text-left text-xs uppercase text-subtle"><tr><th className="px-3 py-2">User</th><th className="px-3 py-2">Line</th><th className="px-3 py-2">Max SI</th><th className="px-3 py-2">Max premium</th><th className="px-3 py-2">Regions</th><th className="px-3 py-2">Status</th><th /></tr></thead>
          <tbody className="divide-y divide-border">{q.data!.map((l) => (
            <tr key={l.id}><td className="px-3 py-2">{l.user ?? l.email}</td><td className="px-3 py-2 capitalize">{l.line}</td><td className="px-3 py-2 tabular-nums">{inr(l.max_sum_insured, { compact: true })}</td>
              <td className="px-3 py-2 tabular-nums">{inr(l.max_premium, { compact: true })}</td><td className="px-3 py-2">{l.regions.join(", ")}</td>
              <td className="px-3 py-2"><Badge tone={l.status === "approved" ? "ok" : "warn"}>{humanize(l.status)} v{l.version}</Badge></td>
              <td className="px-3 py-2">{l.status === "pending" && l.maker_id !== me?.id && <div className="flex gap-1"><Button size="sm" variant="success" onClick={() => decide.mutate({ id: l.id, approve: true })}>Approve</Button><Button size="sm" variant="secondary" onClick={() => decide.mutate({ id: l.id, approve: false })}>Reject</Button></div>}</td></tr>
          ))}</tbody>
        </table></div>
        <Dialog open={open} onOpenChange={setOpen} title="Propose authority change" footer={<><Button variant="secondary" onClick={() => setOpen(false)}>Cancel</Button><Button onClick={() => propose.mutate()} loading={propose.isPending}>Submit for approval</Button></>}>
          <div className="grid gap-3 text-sm">
            <label>User<select className="mt-1 h-9 w-full rounded-lg border border-border bg-surface px-2" value={form.user_id} onChange={(e) => setForm({ ...form, user_id: e.target.value })}><option value="">Select…</option>{users.data?.map((u) => <option key={u.id} value={u.id}>{u.full_name} ({u.email})</option>)}</select></label>
            <label>Line<select className="mt-1 h-9 w-full rounded-lg border border-border bg-surface px-2" value={form.line} onChange={(e) => setForm({ ...form, line: e.target.value })}><option value="property">Property</option><option value="package">Package</option></select></label>
            <label>Max sum insured (₹)<Input inputMode="numeric" value={form.max_sum_insured} onChange={(e) => setForm({ ...form, max_sum_insured: e.target.value })} /></label>
            <label>Max premium (₹)<Input inputMode="numeric" value={form.max_premium} onChange={(e) => setForm({ ...form, max_premium: e.target.value })} /></label>
            <label>Regions (comma separated, or all)<Input value={form.regions} onChange={(e) => setForm({ ...form, regions: e.target.value })} /></label>
            <label>Reason<Textarea rows={2} value={form.reason} onChange={(e) => setForm({ ...form, reason: e.target.value })} /></label>
          </div>
        </Dialog>
      </Card>
    )}</Loading>
  );
}

function Appetite() {
  const qc = useQueryClient();
  const isCuo = useSession((s) => s.has("cuo"));
  const q = useAdmin<AnyObj[]>("appetite", "/api/v1/admin/appetite/versions");
  const [json, setJson] = useState<string | null>(null);
  const refresh = () => void qc.invalidateQueries({ queryKey: ["admin", "appetite"] });
  const draft = useMutation({ mutationFn: () => api("/api/v1/admin/appetite/drafts", { method: "POST", json: { rules: JSON.parse(json ?? "[]"), notes: "edited in workbench" } }), onSuccess: () => { toast.success("Draft created"); setJson(null); refresh(); }, onError: (e) => toast.error(e instanceof SyntaxError ? "Rules must be valid JSON" : (e as Error).message) });
  const test = useMutation({ mutationFn: (id: string) => api<AnyObj>(`/api/v1/admin/appetite/versions/${id}/test`, { method: "POST" }), onSuccess: (r) => { toast.success(`Tested on ${r.evaluated} historical submissions: ${r.changed} would change`); refresh(); } });
  const approve = useMutation({ mutationFn: (id: string) => api(`/api/v1/admin/appetite/versions/${id}/approve`, { method: "POST" }), onSuccess: () => { toast.success("Ruleset approved and live"); refresh(); }, onError: (e) => toast.error((e as Error).message) });
  return (
    <Loading q={q}>{() => (
      <div className="space-y-3">
        {q.data!.map((v) => (
          <Card key={v.id}>
            <CardHeader title={<span className="flex items-center gap-2">Ruleset v{v.version_no}<Badge tone={v.status === "approved" ? "ok" : v.status === "draft" ? "warn" : "neutral"}>{humanize(v.status)}</Badge></span>} subtitle={v.notes}
              actions={<div className="flex gap-2">
                {v.status === "approved" && <Button size="sm" variant="secondary" onClick={() => setJson(JSON.stringify(v.rules.map(({ id, name, outcome, priority, condition, decline_reason, enabled }: AnyObj) => ({ id, name, outcome, priority, condition, decline_reason, enabled })), null, 2))}>Draft new version</Button>}
                {v.status === "draft" && <Button size="sm" variant="secondary" onClick={() => test.mutate(v.id)} loading={test.isPending}><FlaskConical className="h-4 w-4" aria-hidden /> Test on history</Button>}
                {v.status === "draft" && isCuo && <Button size="sm" onClick={() => approve.mutate(v.id)} disabled={!v.test_report?.evaluated}><ShieldCheck className="h-4 w-4" aria-hidden /> Approve (CUO)</Button>}
              </div>} />
            {v.test_report?.evaluated !== undefined && <p className="px-4 pt-3 text-xs text-subtle">Test: {v.test_report.evaluated} evaluated, {v.test_report.changed} changed, {v.test_report.newly_declined_previously_in_appetite} newly declined.</p>}
            <ul className="divide-y divide-border text-sm">{v.rules.map((r: AnyObj) => (
              <li key={r.id} className="flex flex-wrap items-center gap-2 px-4 py-2"><Badge tone={r.outcome === "out_of_appetite" ? "danger" : r.outcome === "needs_info" ? "info" : "warn"}>{r.id}</Badge><span className="font-medium">{r.name}</span><span className="text-xs text-subtle">{humanize(r.outcome)}</span><code className="ml-auto max-w-md truncate text-[11px] text-subtle">{JSON.stringify(r.condition)}</code></li>
            ))}</ul>
          </Card>
        ))}
        <Dialog open={json !== null} onOpenChange={(o) => !o && setJson(null)} title="Edit rules (JSON)" description="Saved as a draft. It must be tested against history and approved by the CUO."
          footer={<><Button variant="secondary" onClick={() => setJson(null)}>Cancel</Button><Button onClick={() => draft.mutate()} loading={draft.isPending}>Save draft</Button></>}>
          <Textarea aria-label="Rules JSON" rows={16} className="font-mono text-xs" value={json ?? ""} onChange={(e) => setJson(e.target.value)} />
        </Dialog>
      </div>
    )}</Loading>
  );
}

function Mappings() {
  const qc = useQueryClient();
  const q = useAdmin<AnyObj[]>("mappings", "/api/v1/admin/mappings");
  const decide = useMutation({ mutationFn: (v: { id: string; approve: boolean }) => api(`/api/v1/admin/mappings/${v.id}/decide`, { method: "POST", json: { approve: v.approve } }), onSuccess: () => { toast.success("Mapping updated"); void qc.invalidateQueries({ queryKey: ["admin", "mappings"] }); } });
  return (
    <Loading q={q}>{() => (
      <Card>
        <CardHeader title="Broker SOV layout library" subtitle="Known layouts map deterministically. Mappings learned by the AI for unknown layouts need approval before reuse." />
        <ul className="divide-y divide-border text-sm">{q.data!.map((m) => (
          <li key={m.id} className="px-4 py-2">
            <div className="flex flex-wrap items-center gap-2"><span className="font-mono text-xs">{m.layout_id}</span><Badge tone={m.status === "approved" ? "ok" : m.status === "proposed" ? "warn" : "neutral"}>{humanize(m.status)}</Badge><Badge>{m.source}</Badge><span className="text-xs text-subtle">{m.broker_hint} · used {m.times_used}×</span>
              {m.status === "proposed" && <span className="ml-auto flex gap-1"><Button size="sm" variant="success" onClick={() => decide.mutate({ id: m.id, approve: true })}><CheckCircle2 className="h-4 w-4" aria-hidden />Approve</Button><Button size="sm" variant="secondary" onClick={() => decide.mutate({ id: m.id, approve: false })}><XCircle className="h-4 w-4" aria-hidden />Reject</Button></span>}</div>
            <p className="mt-1 truncate text-xs text-subtle">{Object.entries(m.mapping as Record<string, AnyObj>).map(([h, s]) => `${h} → ${s.field}${s.unit_multiplier !== 1 ? ` ×${s.unit_multiplier}` : ""}`).join(" · ")}</p>
          </li>
        ))}</ul>
      </Card>
    )}</Loading>
  );
}

function Integrations() {
  const qc = useQueryClient();
  const flags = useAdmin<AnyObj[]>("flags", "/api/v1/admin/flags");
  const cfg = useAdmin<AnyObj>("integrations", "/api/v1/admin/integrations");
  const cost = useAdmin<AnyObj>("cost", "/api/v1/admin/cost");
  const isAdmin = useSession((s) => s.has("admin"));
  const toggle = useMutation({ mutationFn: (v: { key: string; enabled: boolean }) => api(`/api/v1/admin/flags/${v.key}`, { method: "PUT", json: { enabled: v.enabled } }), onSuccess: () => void qc.invalidateQueries({ queryKey: ["admin", "flags"] }), onError: (e) => toast.error((e as Error).message) });
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Card>
        <CardHeader title="Feature flags" subtitle="Region-by-region rollout starts with one mailbox." />
        <Loading q={flags}>{() => <ul className="divide-y divide-border">{flags.data!.map((f) => (
          <li key={f.key} className="flex items-center gap-3 px-4 py-2 text-sm"><div className="min-w-0 flex-1"><p className="font-mono text-xs">{f.key}</p><p className="text-xs text-subtle">{f.description}</p></div>
            <button role="switch" aria-checked={f.enabled} aria-label={f.key} disabled={!isAdmin} onClick={() => toggle.mutate({ key: f.key, enabled: !f.enabled })}
              className={`relative h-6 w-11 rounded-full transition ${f.enabled ? "bg-ok" : "bg-border"}`}><span className={`absolute top-0.5 h-5 w-5 rounded-full bg-white shadow transition ${f.enabled ? "left-[22px]" : "left-0.5"}`} /></button></li>
        ))}</ul>}</Loading>
      </Card>
      <div className="space-y-4">
        <Card>
          <CardHeader title="Monthly cost projection" subtitle="Unit cost from the last 30 days × 9,000 submissions" />
          <Loading q={cost}>{() => (
            <div className="space-y-2 p-4 text-sm">
              <p className="text-2xl font-semibold tabular-nums">{inr(cost.data!.projected_monthly_inr)}</p>
              <p className="text-xs text-subtle">Budget {inr(cost.data!.budgets.monthly_budget_inr)} · LLM projection {inr(cost.data!.projected_llm_monthly_inr)}</p>
              {cost.data!.alerts.map((a: string) => <p key={a} className="rounded-lg bg-warn/10 p-2 text-xs text-warn">{a}</p>)}
            </div>
          )}</Loading>
        </Card>
        <Card>
          <CardHeader title="Integrations" subtitle="Secrets are never stored here; they come from the secrets manager." />
          <Loading q={cfg}>{() => <pre className="max-h-80 overflow-auto p-4 text-[11px]">{JSON.stringify(cfg.data, null, 2)}</pre>}</Loading>
        </Card>
      </div>
    </div>
  );
}

export default function AdminPage() {
  return (
    <div>
      <PageHeader title="Administration" subtitle="Every change here is maker-checker controlled or audited." />
      <Tabs defaultValue="authority">
        <TabsList aria-label="Admin sections" className="mb-4">
          <TabsTrigger value="authority">Authority matrix</TabsTrigger><TabsTrigger value="appetite">Appetite rules</TabsTrigger>
          <TabsTrigger value="mappings">SOV mappings</TabsTrigger><TabsTrigger value="integrations">Integrations and flags</TabsTrigger><TabsTrigger value="users">Users</TabsTrigger>
        </TabsList>
        <TabsContent value="authority"><Authority /></TabsContent>
        <TabsContent value="appetite"><Appetite /></TabsContent>
        <TabsContent value="mappings"><Mappings /></TabsContent>
        <TabsContent value="integrations"><Integrations /></TabsContent>
        <TabsContent value="users"><Users /></TabsContent>
      </Tabs>
    </div>
  );
}

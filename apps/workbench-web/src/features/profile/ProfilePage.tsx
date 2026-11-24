import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Laptop, LogOut, ShieldCheck } from "lucide-react";
import { toast } from "sonner";
import { Badge, Button, Card, CardHeader, ErrorState, PageHeader, Skeleton } from "@/components/ui/primitives";
import { api, authApi, logout } from "@/lib/api";
import { dateTime, humanize, inr } from "@/lib/format";
import { ROLE_LABEL, useSession } from "@/stores/session";
import { useUi, type Theme } from "@/stores/ui";

export default function ProfilePage() {
  const user = useSession((s) => s.user);
  const { theme, setTheme } = useUi();
  const qc = useQueryClient();
  const me = useQuery({ queryKey: ["me"], queryFn: () => api<{ authority: Array<Record<string, unknown>>; mfa: boolean }>("/api/v1/me") });
  const sessions = useQuery({ queryKey: ["sessions"], queryFn: authApi.sessions });
  const revoke = useMutation({
    mutationFn: (id: string) => authApi.revoke(id),
    onSuccess: () => { toast.success("Session signed out"); void qc.invalidateQueries({ queryKey: ["sessions"] }); },
    onError: (e) => toast.error((e as Error).message),
  });
  return (
    <div className="space-y-4">
      <PageHeader title="Profile and sessions" />
      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader title={user?.full_name ?? ""} subtitle={user?.email} />
          <div className="space-y-3 p-4 text-sm">
            <p>Roles: {user?.roles.map((r) => <Badge key={r} tone="brand" className="mr-1">{ROLE_LABEL[r] ?? r}</Badge>)}</p>
            <p>Region: <span className="capitalize">{user?.region}</span></p>
            <p className="flex items-center gap-2">{me.data?.mfa ? <><ShieldCheck className="h-4 w-4 text-ok" aria-hidden /> Signed in with two-step verification</> : "Signed in with password only"}</p>
            <fieldset><legend className="mb-1 font-medium">Theme</legend>
              <div className="flex gap-2">{(["light", "dark", "system"] as Theme[]).map((t) => (
                <label key={t} className="flex items-center gap-1"><input type="radio" name="theme" checked={theme === t} onChange={() => setTheme(t)} />{humanize(t)}</label>
              ))}</div>
            </fieldset>
          </div>
        </Card>
        <Card>
          <CardHeader title="Underwriting authority" subtitle="Approved via maker-checker; re-validated on every quote." />
          <ul className="divide-y divide-border text-sm">
            {me.data?.authority.length ? me.data.authority.map((a) => (
              <li key={String(a.limit_id)} className="flex flex-wrap gap-3 px-4 py-2"><span className="font-medium capitalize">{String(a.line)}</span><span>SI up to {inr(a.max_sum_insured as number, { compact: true })}</span><span>Premium up to {inr(a.max_premium as number, { compact: true })}</span><span className="text-subtle">{(a.regions as string[]).join(", ")}</span></li>
            )) : <li className="px-4 py-3 text-subtle">No quoting authority.</li>}
          </ul>
        </Card>
      </div>
      <Card>
        <CardHeader title="Active sessions" subtitle="Sign out any device remotely." actions={<Button variant="secondary" size="sm" onClick={() => void logout()}><LogOut className="h-4 w-4" aria-hidden /> Sign out here</Button>} />
        {sessions.isLoading ? <Skeleton className="m-4 h-24" /> : sessions.isError ? <ErrorState error={sessions.error} onRetry={() => sessions.refetch()} /> : (
          <ul className="divide-y divide-border text-sm">
            {sessions.data!.map((s) => (
              <li key={s.id} className="flex flex-wrap items-center gap-3 px-4 py-2">
                <Laptop className="h-4 w-4 text-subtle" aria-hidden />
                <span className="min-w-0 flex-1 truncate">{s.user_agent || "Unknown device"} · {s.ip}</span>
                <span className="text-xs text-subtle">since {dateTime(s.created_at)}</span>
                {s.current ? <Badge tone="ok">This device</Badge> : <Button size="sm" variant="secondary" onClick={() => revoke.mutate(s.id)}>Sign out</Button>}
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}

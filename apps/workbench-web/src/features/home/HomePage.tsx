import { useQuery } from "@tanstack/react-query";
import { ArrowRight, Copy, Inbox, ShieldAlert, Stethoscope } from "lucide-react";
import { Link } from "react-router-dom";
import { OutcomeBadge, SlaTimer, StatusBadge } from "@/components/ui/domain";
import { Card, CardHeader, EmptyState, ErrorState, PageHeader, Skeleton, StatTile } from "@/components/ui/primitives";
import { api } from "@/lib/api";
import { inr, pct } from "@/lib/format";
import { useSession } from "@/stores/session";
import type { Page, SubmissionSummary } from "@/types/api";

type Ops = { submissions: number; duplicate_rate: number; median_review_minutes: number | null; sla_breaches_open: number;
  triage_outcomes: Record<string, number>; cost: { per_submission_inr: number } };

export default function HomePage() {
  const user = useSession((s) => s.user);
  const has = useSession((s) => s.has);
  const canQueue = has("data_entry", "underwriter", "senior_underwriter", "risk_engineer", "cuo", "admin");
  const canOps = has("data_entry", "underwriter", "senior_underwriter", "cuo", "admin");
  const queue = useQuery({
    queryKey: ["submissions", "home"],
    queryFn: () => api<Page<SubmissionSummary>>("/api/v1/submissions?queue=review&page_size=8&sort=sla"),
    enabled: canQueue,
  });
  const ops = useQuery({ queryKey: ["dash", "ops", 30], queryFn: () => api<Ops>("/api/v1/dashboards/ops?days=30"), enabled: canOps });
  const counts = queue.data?.status_counts ?? {};
  const triaged = ops.data ? Object.values(ops.data.triage_outcomes).reduce((a, b) => a + b, 0) : 0;

  return (
    <div className="space-y-6">
      <PageHeader title={`Good day, ${user?.full_name?.split(" ")[0] ?? ""}`} subtitle="Your queue, SLA risks and today's pipeline at a glance." />
      {canOps && (
        <section aria-label="Key indicators" className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          {ops.isLoading ? Array.from({ length: 4 }, (_, i) => <Skeleton key={i} className="h-24" />) : ops.data && (
            <>
              <StatTile label="Submissions (30 days)" value={ops.data.submissions} hint={`Out of appetite ${pct((ops.data.triage_outcomes.out_of_appetite ?? 0) / (triaged || 1), 0)}`} />
              <StatTile label="Median review time" value={ops.data.median_review_minutes !== null ? `${ops.data.median_review_minutes} min` : "—"} hint="Target under 15 min (baseline 70)" tone={ops.data.median_review_minutes !== null && ops.data.median_review_minutes <= 15 ? "ok" : "neutral"} />
              <StatTile label="SLA breaches open" value={ops.data.sla_breaches_open} tone={ops.data.sla_breaches_open ? "danger" : "ok"} hint="48-hour quote clock" />
              <StatTile label="Cost per submission" value={inr(ops.data.cost.per_submission_inr)} hint={`Duplicate rate ${pct(ops.data.duplicate_rate)}`} />
            </>
          )}
        </section>
      )}
      <div className="grid gap-4 lg:grid-cols-3">
        {canQueue && (
          <Card className="lg:col-span-2">
            <CardHeader title="Next up in review" subtitle="Ordered by SLA" actions={<Link to="/submissions" className="flex items-center gap-1 text-sm text-brand hover:underline">Open queue <ArrowRight className="h-3.5 w-3.5" /></Link>} />
            {queue.isLoading ? <div className="space-y-2 p-4">{Array.from({ length: 5 }, (_, i) => <Skeleton key={i} className="h-10" />)}</div>
              : queue.isError ? <ErrorState error={queue.error} onRetry={() => queue.refetch()} />
              : !queue.data?.items.length ? <EmptyState title="Queue is clear" body="New submissions appear here as soon as triage and extraction finish." />
              : (
                <ul className="divide-y divide-border">
                  {queue.data.items.map((s) => (
                    <li key={s.id}>
                      <Link to={`/submissions/${s.id}`} className="flex flex-wrap items-center gap-3 px-4 py-3 hover:bg-muted/60">
                        <span className="font-mono text-xs text-subtle">{s.reference}</span>
                        <span className="min-w-0 flex-1 truncate font-medium">{s.insured_name || "Unnamed insured"}</span>
                        {s.injection_flagged && <ShieldAlert className="h-4 w-4 text-danger" aria-label="Injection flagged" />}
                        <OutcomeBadge outcome={s.triage_outcome} />
                        <span className="w-24 text-right text-sm tabular-nums">{inr(s.total_sum_insured, { compact: true })}</span>
                        <SlaTimer dueAt={s.sla_due_at} compact />
                      </Link>
                    </li>
                  ))}
                </ul>
              )}
          </Card>
        )}
        <Card>
          <CardHeader title="Work queues" />
          <ul className="space-y-1 p-3 text-sm">
            {[
              { to: "/submissions?queue=review", label: "In review", n: (counts.in_review ?? 0) + (counts.needs_info ?? 0), icon: Inbox },
              { to: "/submissions?queue=triage", label: "Declines to confirm", n: counts.decline_pending ?? 0, icon: ShieldAlert },
              { to: "/clearance", label: "Duplicate checks", n: counts.clearance_review ?? 0, icon: Copy },
              { to: "/referrals", label: "Risk engineering referrals", n: null, icon: Stethoscope },
              { to: "/submissions?queue=ready", label: "Ready for rating", n: (counts.ready_for_rating ?? 0) + (counts.rated ?? 0), icon: ArrowRight },
            ].map((q) => (
              <li key={q.to}>
                <Link to={q.to} className="flex items-center gap-3 rounded-lg px-3 py-2 hover:bg-muted">
                  <q.icon className="h-4 w-4 text-subtle" aria-hidden /> {q.label}
                  {q.n !== null && <span className="ml-auto rounded-full bg-muted px-2 text-xs tabular-nums">{q.n}</span>}
                </Link>
              </li>
            ))}
          </ul>
          {counts.manual_review ? <p className="px-4 pb-4 text-xs text-danger"><StatusBadge status="manual_review" /> {counts.manual_review} need manual handling (gateway fallback).</p> : null}
        </Card>
      </div>
    </div>
  );
}

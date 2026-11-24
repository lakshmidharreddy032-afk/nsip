import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, ShieldCheck } from "lucide-react";
import { useState } from "react";
import { Bar, BarChart, CartesianGrid, Cell, Legend, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Badge, Card, CardHeader, ErrorState, PageHeader, Skeleton, StatTile, Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/primitives";
import { api } from "@/lib/api";
import { humanize, inr, pct } from "@/lib/format";
import { useSession } from "@/stores/session";

const C = { brand: "rgb(var(--brand))", ok: "rgb(var(--ok))", warn: "rgb(var(--warn))", danger: "rgb(var(--danger))", info: "rgb(var(--info))", grid: "rgb(var(--border))", subtle: "rgb(var(--subtle))" };
const OUTCOME_COLOR: Record<string, string> = { in_appetite: C.ok, out_of_appetite: C.danger, refer_risk_engineering: C.warn, needs_info: C.info, pending: C.subtle };
const axis = { stroke: C.subtle, fontSize: 11, tickLine: false, axisLine: false };

function Chart({ title, subtitle, children, height = 240 }: { title: string; subtitle?: string; children: React.ReactElement; height?: number }) {
  return (
    <Card>
      <CardHeader title={title} subtitle={subtitle} />
      <div className="p-3" style={{ height }}><ResponsiveContainer width="100%" height="100%">{children}</ResponsiveContainer></div>
    </Card>
  );
}

function useDash<T>(key: string, path: string, enabled = true) {
  return useQuery({ queryKey: ["dash", key, path], queryFn: () => api<T>(path), enabled });
}

type AnyObj = Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any

function Ops() {
  const [drill, setDrill] = useState<string | null>(null);
  const q = useDash<AnyObj>("ops", "/api/v1/dashboards/ops?days=30");
  if (q.isLoading) return <Skeleton className="h-96" />;
  if (q.isError) return <ErrorState error={q.error} onRetry={() => q.refetch()} />;
  const d = q.data!;
  const outcomes = Object.entries(d.triage_outcomes).map(([k, v]) => ({ name: humanize(k), key: k, value: v as number }));
  const cost = Object.entries(d.cost.per_submission_breakdown_inr).map(([k, v]) => ({ name: humanize(k), value: v as number }));
  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
        <StatTile label="Submissions" value={d.submissions} hint="last 30 days" />
        <StatTile label="Duplicate rate" value={pct(d.duplicate_rate)} hint="baseline 18%" />
        <StatTile label="Median review" value={d.median_review_minutes !== null ? `${d.median_review_minutes} min` : "—"} hint={`target ${d.target_review_minutes} · baseline ${d.baseline_keying_minutes}`} />
        <StatTile label="SLA breaches" value={d.sla_breaches_open} tone={d.sla_breaches_open ? "danger" : "ok"} hint={`${d.sla_breaches_closed} closed late`} />
        <StatTile label="Cost / submission" value={inr(d.cost.per_submission_inr)} hint={`${d.manual_queue} in manual queue`} />
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        <Chart title="Daily volume" subtitle="Email-first intake, portal secondary">
          <BarChart data={d.volume_by_day}><CartesianGrid stroke={C.grid} vertical={false} /><XAxis dataKey="date" {...axis} /><YAxis {...axis} allowDecimals={false} /><Tooltip /><Bar dataKey="count" fill={C.brand} radius={[4, 4, 0, 0]} isAnimationActive /></BarChart>
        </Chart>
        <Chart title="Triage outcomes" subtitle={drill ? `Selected: ${humanize(drill)} (click again to clear)` : "Click a bar to drill down"}>
          <BarChart data={outcomes} onClick={(e) => { const k = (e?.activePayload?.[0]?.payload as AnyObj | undefined)?.key; setDrill(k === drill ? null : k ?? null); }}>
            <CartesianGrid stroke={C.grid} vertical={false} /><XAxis dataKey="name" {...axis} /><YAxis {...axis} allowDecimals={false} /><Tooltip />
            <Bar dataKey="value" radius={[4, 4, 0, 0]}>{outcomes.map((o) => <Cell key={o.key} fill={OUTCOME_COLOR[o.key] ?? C.brand} opacity={drill && drill !== o.key ? 0.35 : 1} cursor="pointer" />)}</Bar>
          </BarChart>
        </Chart>
        <Chart title="Cost per submission by component (₹)" subtitle="LLM tokens, OCR, geocoding, cat model and compute">
          <BarChart data={cost} layout="vertical"><CartesianGrid stroke={C.grid} horizontal={false} /><XAxis type="number" {...axis} /><YAxis type="category" dataKey="name" width={90} {...axis} /><Tooltip /><Bar dataKey="value" fill={C.info} radius={[0, 4, 4, 0]} /></BarChart>
        </Chart>
        <Card>
          <CardHeader title="Status mix" />
          <ul className="grid grid-cols-2 gap-2 p-4 text-sm">{Object.entries(d.status_counts).map(([k, v]) => <li key={k} className="flex justify-between rounded-lg bg-muted px-3 py-1.5"><span>{humanize(k)}</span><span className="tabular-nums">{String(v)}</span></li>)}</ul>
        </Card>
      </div>
    </div>
  );
}

function Underwriting() {
  const q = useDash<AnyObj>("uw", "/api/v1/dashboards/underwriting?days=90");
  if (q.isLoading) return <Skeleton className="h-96" />;
  if (q.isError) return <ErrorState error={q.error} onRetry={() => q.refetch()} />;
  const d = q.data!;
  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
        <StatTile label="Median time to quote" value={d.median_time_to_quote_hours !== null ? `${d.median_time_to_quote_hours} h` : "—"} hint={`primary metric · baseline ${d.baseline_time_to_quote_days} days`} tone="ok" />
        <StatTile label="Quoted within 48h" value={pct(d.pct_quoted_within_48h)} />
        <StatTile label="Decline turnaround" value={d.median_decline_turnaround_hours !== null ? `${d.median_decline_turnaround_hours} h` : "—"} />
        <StatTile label="Quote to bind" value={pct(d.quote_to_bind)} hint={`${d.bound} bound of ${d.quotes}`} />
        <StatTile label="Authority blocks" value={d.authority_blocks} hint={`${d.fast_lane_quotes} fast-lane quotes`} />
      </div>
      <Chart title="AI suggestion override rate by field" subtitle="Share of extracted values corrected by reviewers" height={320}>
        <BarChart data={d.ai_override_rates.slice(0, 15)} layout="vertical" margin={{ left: 40 }}>
          <CartesianGrid stroke={C.grid} horizontal={false} /><XAxis type="number" tickFormatter={(v) => pct(v, 0)} {...axis} /><YAxis type="category" dataKey="field" width={170} {...axis} />
          <Tooltip formatter={(v: number) => pct(v)} /><Bar dataKey="override_rate" fill={C.warn} radius={[0, 4, 4, 0]} />
        </BarChart>
      </Chart>
    </div>
  );
}

function Cuo() {
  const q = useDash<AnyObj>("cuo", "/api/v1/dashboards/cuo");
  if (q.isLoading) return <Skeleton className="h-96" />;
  if (q.isError) return <ErrorState error={q.error} onRetry={() => q.refetch()} />;
  const d = q.data!;
  const months = [...new Set(d.loss_ratio_monthly.map((r: AnyObj) => r.month))].map((m) => {
    const row: AnyObj = { month: m };
    d.loss_ratio_monthly.filter((r: AnyObj) => r.month === m).forEach((r: AnyObj) => (row[r.cohort] = r.loss_ratio));
    return row;
  });
  return (
    <div className="space-y-4">
      <Card className="p-4">
        <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-subtle">Outcome hierarchy</p>
        <ol className="grid gap-2 md:grid-cols-3">{d.outcome_hierarchy.map((h: AnyObj, i: number) => (
          <li key={h.metric} className="rounded-lg border border-border p-3 text-sm"><Badge tone={i === 0 ? "danger" : i === 1 ? "brand" : "neutral"}>{humanize(h.role)}</Badge><p className="mt-1 font-medium">{h.metric}</p><p className="text-xs text-subtle">{h.rule}</p></li>
        ))}</ol>
      </Card>
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <StatTile label="Loss ratio: AI-assisted" value={pct(d.loss_ratio_by_cohort.ai_assisted)} tone={d.guardrail_ok ? "ok" : "danger"} hint={d.guardrail_ok ? "guardrail holding" : "guardrail breached"} />
        <StatTile label="Loss ratio: baseline" value={pct(d.loss_ratio_by_cohort.baseline)} hint={`reference ${pct(d.loss_ratio_baseline, 0)}`} />
        <StatTile label="Assistant disagreement" value={pct(d.assistant_disagreement_rate)} hint="advisory vs rules" />
        <StatTile label="Avg extraction confidence" value={pct(d.avg_extraction_confidence)} hint={`claims snapshot ${d.claims_snapshot_date}`} />
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        <Chart title="Loss ratio by cohort (monthly claims snapshot)" subtitle="Must not worsen versus the 68% baseline">
          <LineChart data={months}><CartesianGrid stroke={C.grid} vertical={false} /><XAxis dataKey="month" {...axis} /><YAxis domain={[0.55, 0.8]} tickFormatter={(v) => pct(v, 0)} {...axis} /><Tooltip formatter={(v: number) => pct(v)} /><Legend />
            <ReferenceLine y={d.loss_ratio_baseline} stroke={C.danger} strokeDasharray="4 4" label={{ value: "guardrail", fill: C.danger, fontSize: 11 }} />
            <Line dataKey="baseline" stroke={C.subtle} strokeWidth={2} dot={false} /><Line dataKey="ai_assisted" stroke={C.brand} strokeWidth={2} dot={false} /></LineChart>
        </Chart>
        <Chart title="Appetite rule hit rates" subtitle={`${d.triaged} current triage results`}>
          <BarChart data={d.appetite_rule_hits}><CartesianGrid stroke={C.grid} vertical={false} /><XAxis dataKey="rule_id" {...axis} /><YAxis tickFormatter={(v) => pct(v, 0)} {...axis} /><Tooltip formatter={(v: number) => pct(v)} /><Bar dataKey="rate" fill={C.brand} radius={[4, 4, 0, 0]} /></BarChart>
        </Chart>
      </div>
      <Card>
        <CardHeader title="Drift alerts" />
        {d.drift_alerts.length ? <ul className="divide-y divide-border">{d.drift_alerts.map((a: AnyObj, i: number) => <li key={i} className="flex items-center gap-2 px-4 py-2 text-sm"><AlertTriangle className={a.severity === "critical" ? "h-4 w-4 text-danger" : "h-4 w-4 text-warn"} aria-hidden />{a.message}</li>)}</ul>
          : <p className="flex items-center gap-2 p-4 text-sm text-ok"><ShieldCheck className="h-4 w-4" aria-hidden /> No drift detected.</p>}
      </Card>
    </div>
  );
}

function Distribution() {
  const list = useDash<AnyObj>("dist", "/api/v1/dashboards/distribution");
  const [broker, setBroker] = useState<string>("");
  const one = useDash<AnyObj>("dist-one", `/api/v1/dashboards/distribution?broker_id=${broker}`, !!broker);
  if (list.isLoading) return <Skeleton className="h-64" />;
  if (list.isError) return <ErrorState error={list.error} onRetry={() => list.refetch()} />;
  const b = one.data?.broker;
  return (
    <div className="space-y-4">
      <Card className="p-4">
        <label htmlFor="broker" className="text-sm font-medium">Broker</label>
        <select id="broker" value={broker} onChange={(e) => setBroker(e.target.value)} className="ml-3 h-9 rounded-lg border border-border bg-surface px-2 text-sm">
          <option value="">Select a broker…</option>{list.data!.brokers.map((x: AnyObj) => <option key={x.id} value={x.id}>{x.name}</option>)}
        </select>
        <p className="mt-2 text-xs text-subtle">Each view shows one broker's own figures only; no cross-broker comparison is exposed.</p>
      </Card>
      {one.isLoading && <Skeleton className="h-32" />}
      {b && (
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
          <StatTile label="Submissions" value={b.submissions} hint={`${b.duplicates} duplicates`} />
          <StatTile label="Quoted" value={b.quoted} hint={`${b.declined} declined`} />
          <StatTile label="Median turnaround" value={b.median_turnaround_hours !== null ? `${b.median_turnaround_hours} h` : "—"} />
          <StatTile label="Win rate" value={pct(b.win_rate)} hint="lagging; baseline 11%" />
          <StatTile label="Out of appetite" value={pct(b.out_of_appetite_share)} />
        </div>
      )}
    </div>
  );
}

export default function DashboardsPage() {
  const has = useSession((s) => s.has);
  const tabs = [
    { key: "ops", label: "Operations", ok: has("data_entry", "underwriter", "senior_underwriter", "cuo", "admin"), el: <Ops /> },
    { key: "uw", label: "Underwriting", ok: has("underwriter", "senior_underwriter", "cuo", "admin"), el: <Underwriting /> },
    { key: "cuo", label: "CUO", ok: has("cuo", "admin"), el: <Cuo /> },
    { key: "dist", label: "Distribution", ok: has("distribution", "cuo", "admin"), el: <Distribution /> },
  ].filter((t) => t.ok);
  if (!tabs.length) return <PageHeader title="Dashboards" subtitle="No dashboards are available for your role." />;
  return (
    <div>
      <PageHeader title="Dashboards" subtitle="Loss ratio is the guardrail, time to quote the primary metric, win rate the lagging metric." />
      <Tabs defaultValue={tabs[0].key}>
        <TabsList aria-label="Dashboard" className="mb-4">{tabs.map((t) => <TabsTrigger key={t.key} value={t.key}>{t.label}</TabsTrigger>)}</TabsList>
        {tabs.map((t) => <TabsContent key={t.key} value={t.key}>{t.el}</TabsContent>)}
      </Tabs>
    </div>
  );
}

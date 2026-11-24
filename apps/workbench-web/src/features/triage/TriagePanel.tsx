import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Bot, Gavel, Send, Undo2 } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { InjectionBadge, OutcomeBadge } from "@/components/ui/domain";
import { Badge, Button, Card, CardHeader, Dialog, Textarea } from "@/components/ui/primitives";
import { api } from "@/lib/api";
import { humanize, inr } from "@/lib/format";
import { useSession } from "@/stores/session";
import type { SubmissionDetail } from "@/types/api";

export function TriagePanel({ sub }: { sub: SubmissionDetail }) {
  const t = sub.triage;
  const qc = useQueryClient();
  const canDecide = useSession((s) => s.has("underwriter", "senior_underwriter"));
  const [draft, setDraft] = useState(t?.decline_draft ?? "");
  const [override, setOverride] = useState(false);
  const [reason, setReason] = useState("");
  const [outcome, setOutcome] = useState("in_appetite");
  const refresh = () => qc.invalidateQueries({ queryKey: ["submission", sub.id] });

  const decline = useMutation({
    mutationFn: () => api(`/api/v1/submissions/${sub.id}/triage/decline`, { method: "POST", json: { body: draft, reason: "" } }),
    onSuccess: () => { toast.success("Decline sent to broker"); void refresh(); void qc.invalidateQueries({ queryKey: ["submissions"] }); },
    onError: (e) => toast.error((e as Error).message),
  });
  const doOverride = useMutation({
    mutationFn: () => api(`/api/v1/submissions/${sub.id}/triage/override`, { method: "POST", json: { outcome, reason } }),
    onSuccess: () => { toast.success("Triage overridden and recorded"); setOverride(false); void refresh(); },
    onError: (e) => toast.error((e as Error).message),
  });
  if (!t) return <Card className="p-4 text-sm text-subtle">Not yet triaged.</Card>;
  const f = t.features as Record<string, string | number | boolean | null>;

  return (
    <div className="space-y-3">
      <Card>
        <CardHeader title={<span className="flex items-center gap-2">Appetite triage <OutcomeBadge outcome={t.override_outcome ?? t.outcome} /></span>}
          subtitle={`Rules v${t.rule_version} · ${t.stage === "initial" ? "at intake" : "after extraction"} · deterministic decision`}
          actions={canDecide && <Button size="sm" variant="secondary" onClick={() => setOverride(true)}><Undo2 className="h-3.5 w-3.5" aria-hidden /> Override</Button>} />
        <div className="space-y-3 p-4 text-sm">
          {sub.injection_flagged && <div className="rounded-lg border border-danger/30 bg-danger/5 p-3"><InjectionBadge /><p className="mt-1 text-xs text-subtle">Instruction-like text was found in the broker content. It was treated as data and did not influence routing.</p>
            <ul className="mt-2 space-y-1 text-xs">{sub.injection_flags.slice(0, 4).map((x, i) => <li key={i}><Badge tone="danger">{humanize(x.pattern)}</Badge> <span className="text-subtle">{x.location}:</span> “{x.excerpt}”</li>)}</ul></div>}
          {t.override_outcome && <p className="rounded-lg bg-warn/10 p-2 text-xs">Overridden to {humanize(t.override_outcome)}: {t.override_reason}</p>}
          <div>
            <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-subtle">Rules fired</p>
            {t.fired_rules.length ? (
              <ul className="space-y-1">{t.fired_rules.map((r) => <li key={r.rule_id} className="flex items-center gap-2"><Badge tone={r.outcome === "out_of_appetite" ? "danger" : r.outcome === "needs_info" ? "info" : "warn"}>{r.rule_id}</Badge>{r.name}</li>)}</ul>
            ) : <p className="text-subtle">None. Within appetite.</p>}
          </div>
          <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
            {[["Occupancy", f.occupancy_code], ["Hazard", f.occupancy_hazard], ["Sum insured", inr(f.sum_insured as number, { compact: true })], ["Construction", f.construction],
              ["Cat zone", f.cat_zone], ["Year built", f.year_built], ["Claims (3y)", f.claims_count_3y], ["Locations", f.locations]].map(([k, v]) => (
              <div key={String(k)} className="flex justify-between gap-2 border-b border-border/60 py-1"><dt className="text-subtle">{k}</dt><dd className="font-medium">{v === null || v === undefined ? "—" : String(v)}</dd></div>
            ))}
          </dl>
          {typeof t.llm_signals.rationale === "string" && (
            <div className="rounded-lg bg-muted p-3 text-xs">
              <p className="mb-1 flex items-center gap-1 font-medium"><Bot className="h-3.5 w-3.5" aria-hidden /> Assistant notes (advisory only)</p>
              <p className="text-subtle">{t.llm_signals.rationale}</p>
              {t.llm_signals.agrees_with_rules === false && <p className="mt-1 text-warn">The assistant's suggestion differed from the rules and was ignored for routing.</p>}
            </div>
          )}
        </div>
      </Card>
      {(sub.status === "decline_pending" || (t.outcome === "needs_info" && t.decline_draft)) && (
        <Card>
          <CardHeader title={sub.status === "decline_pending" ? "Draft decline to broker" : "Information request draft"} subtitle="Review and edit. Nothing is sent without your confirmation." />
          <div className="space-y-3 p-4">
            <Textarea aria-label="Decline message" rows={10} value={draft} onChange={(e) => setDraft(e.target.value)} className="font-mono text-xs" />
            {sub.status === "decline_pending" && canDecide && (
              <Button variant="danger" onClick={() => decline.mutate()} loading={decline.isPending}><Send className="h-4 w-4" aria-hidden /> Confirm and send decline</Button>
            )}
          </div>
        </Card>
      )}
      <Dialog open={override} onOpenChange={setOverride} title="Override triage outcome" description="Overrides are audited and reported on the CUO dashboard."
        footer={<><Button variant="secondary" onClick={() => setOverride(false)}>Cancel</Button><Button onClick={() => doOverride.mutate()} loading={doOverride.isPending} disabled={reason.trim().length < 10}><Gavel className="h-4 w-4" aria-hidden /> Record override</Button></>}>
        <label className="block text-sm font-medium" htmlFor="ov-outcome">New outcome</label>
        <select id="ov-outcome" value={outcome} onChange={(e) => setOutcome(e.target.value)} className="mt-1 h-9 w-full rounded-lg border border-border bg-surface px-2 text-sm">
          <option value="in_appetite">In appetite</option><option value="refer_risk_engineering">Refer to risk engineering</option><option value="out_of_appetite">Out of appetite</option>
        </select>
        <label className="mt-3 block text-sm font-medium" htmlFor="ov-reason">Reason (min. 10 characters)</label>
        <Textarea id="ov-reason" rows={3} value={reason} onChange={(e) => setReason(e.target.value)} />
      </Dialog>
    </div>
  );
}

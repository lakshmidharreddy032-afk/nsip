import { useMutation, useQueryClient } from "@tanstack/react-query";
import { BadgeCheck, Calculator, FileCheck2, Lock, Zap } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { Badge, Button, Card, CardHeader, Dialog, Textarea } from "@/components/ui/primitives";
import { api, ApiError } from "@/lib/api";
import { humanize, inr } from "@/lib/format";
import { useSession } from "@/stores/session";
import type { AuthorityCheck, RatingRun, SubmissionDetail } from "@/types/api";

type RateResponse = { rating_run: RatingRun; authority: AuthorityCheck; fast_lane: boolean };

/** Rating from filed sources only, authority check before any decision, explicit human confirmation. */
export function RatingPanel({ sub }: { sub: SubmissionDetail }) {
  const qc = useQueryClient();
  const isUw = useSession((s) => s.has("underwriter", "senior_underwriter"));
  const [result, setResult] = useState<RateResponse | null>(null);
  const [confirm, setConfirm] = useState(false);
  const [referOpen, setReferOpen] = useState(false);
  const [referReason, setReferReason] = useState("");
  const run = result?.rating_run ?? sub.rating_runs[0] ?? null;
  const refresh = () => { void qc.invalidateQueries({ queryKey: ["submission", sub.id] }); void qc.invalidateQueries({ queryKey: ["submissions"] }); };

  const rate = useMutation({ mutationFn: () => api<RateResponse>(`/api/v1/submissions/${sub.id}/rating`, { method: "POST" }), onSuccess: (r) => { setResult(r); refresh(); }, onError: (e) => toast.error((e as Error).message) });
  const quote = useMutation({
    mutationFn: () => api<{ policy_admin_ref: string; premium: string }>(`/api/v1/submissions/${sub.id}/quote`, { method: "POST", json: { rating_run_id: run!.id, confirm: true } }),
    onSuccess: (q) => { setConfirm(false); toast.success(`Quote ${q.policy_admin_ref} created in policy admin`); refresh(); },
    onError: (e) => { setConfirm(false); toast.error(e instanceof ApiError ? e.message : "Quote failed"); },
  });
  const refer = useMutation({
    mutationFn: () => api(`/api/v1/submissions/${sub.id}/refer`, { method: "POST", json: { reason: referReason } }),
    onSuccess: () => { setReferOpen(false); toast.success("Referred"); refresh(); },
    onError: (e) => toast.error((e as Error).message),
  });

  if (sub.quote) {
    return (
      <Card className="p-4 text-sm">
        <p className="flex items-center gap-2 font-semibold text-ok"><BadgeCheck className="h-5 w-5" aria-hidden /> Quoted {inr(sub.quote.premium)}</p>
        <p className="mt-1 text-subtle">Policy admin ref {sub.quote.policy_admin_ref}{sub.quote.fast_lane && " · fast lane"}</p>
        <p className="mt-2 break-all font-mono text-[11px] text-subtle">Audit seal {sub.quote.audit_seal_hash}</p>
      </Card>
    );
  }
  const blocked = sub.referral_status === "open" ? "Risk-engineering referral must be completed before pricing."
    : !["ready_for_rating", "rated"].includes(sub.status) ? "Mark the submission ready after review to enable rating." : null;
  const auth = result?.authority;

  return (
    <div className="space-y-3">
      <Card>
        <CardHeader title="Rating" subtitle="Premiums come only from the filed rating API or the filed actuarial workbook."
          actions={isUw && <Button size="sm" onClick={() => rate.mutate()} loading={rate.isPending} disabled={!!blocked}><Calculator className="h-4 w-4" aria-hidden /> {run ? "Re-run" : "Run rating"}</Button>} />
        <div className="p-4 text-sm">
          {blocked && <p className="flex items-center gap-2 text-subtle"><Lock className="h-4 w-4" aria-hidden /> {blocked}</p>}
          {run && (
            <div className="space-y-3">
              <div className="flex flex-wrap items-baseline gap-3">
                <span className="text-2xl font-semibold tabular-nums">{inr(run.premium)}</span>
                <span className="text-xs text-subtle">excl. GST ({inr(run.outputs.gst_18pct)})</span>
              </div>
              <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
                <dt className="text-subtle">Rate source</dt><dd><Badge tone="info"><FileCheck2 className="h-3 w-3" aria-hidden />{run.source === "rating_api" ? "Rating API (package)" : "Actuarial workbook"}</Badge></dd>
                <dt className="text-subtle">Table version</dt><dd className="font-mono">{run.source_version}</dd>
                <dt className="text-subtle">Filing reference</dt><dd className="font-mono">{run.filing_ref}</dd>
                {run.workbook_hash && <><dt className="text-subtle">Workbook SHA-256</dt><dd className="truncate font-mono" title={run.workbook_hash}>{run.workbook_hash.slice(0, 16)}…</dd></>}
                {Object.entries(run.outputs).filter(([k]) => k !== "premium" && k !== "gst_18pct").map(([k, v]) => <><dt key={k} className="text-subtle">{humanize(k)}</dt><dd key={`${k}v`} className="tabular-nums">{v}</dd></>)}
              </dl>
            </div>
          )}
        </div>
      </Card>
      {run && auth && (
        <Card className="p-4 text-sm">
          <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-subtle">Authority check</p>
          {auth.allowed ? <p className="flex items-center gap-2 text-ok"><BadgeCheck className="h-4 w-4" aria-hidden /> Within your authority ({humanize(auth.line)}, region {auth.region})</p>
            : <ul className="space-y-1 text-danger">{auth.reasons.map((r) => <li key={r}>{r}</li>)}</ul>}
          <div className="mt-3 flex flex-wrap gap-2">
            {auth.allowed && isUw && (
              <Button onClick={() => setConfirm(true)} variant="success">{result?.fast_lane ? <><Zap className="h-4 w-4" aria-hidden /> Fast lane: confirm quote</> : "Issue quote"}</Button>
            )}
            {isUw && <Button variant="secondary" onClick={() => setReferOpen(true)}>Refer {auth.requires_referral_to ? `to ${humanize(auth.requires_referral_to)}` : ""}</Button>}
          </div>
        </Card>
      )}
      <Dialog open={confirm} onOpenChange={setConfirm} title="Confirm quote" description="This creates the quote in policy administration under your authority and seals the audit record."
        footer={<><Button variant="secondary" onClick={() => setConfirm(false)}>Cancel</Button><Button variant="success" onClick={() => quote.mutate()} loading={quote.isPending}>Confirm and issue</Button></>}>
        <dl className="grid grid-cols-2 gap-2 text-sm"><dt className="text-subtle">Insured</dt><dd>{sub.insured_name}</dd><dt className="text-subtle">Premium</dt><dd className="font-semibold">{inr(run?.premium)}</dd>
          <dt className="text-subtle">Sum insured</dt><dd>{inr(sub.total_sum_insured)}</dd><dt className="text-subtle">Rate source</dt><dd>{run?.source_version}</dd></dl>
      </Dialog>
      <Dialog open={referOpen} onOpenChange={setReferOpen} title="Refer submission"
        footer={<><Button variant="secondary" onClick={() => setReferOpen(false)}>Cancel</Button><Button onClick={() => refer.mutate()} disabled={referReason.trim().length < 5} loading={refer.isPending}>Refer</Button></>}>
        <Textarea aria-label="Referral reason" rows={3} value={referReason} onChange={(e) => setReferReason(e.target.value)} placeholder="Why is this being referred?" />
      </Dialog>
    </div>
  );
}

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ClipboardCheck, Hand } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import { SlaTimer } from "@/components/ui/domain";
import { Badge, Button, Card, Dialog, EmptyState, ErrorState, Input, PageHeader, Skeleton, Tabs, TabsList, TabsTrigger, Textarea } from "@/components/ui/primitives";
import { api } from "@/lib/api";
import { humanize, inr } from "@/lib/format";
import { useSession } from "@/stores/session";
import type { Referral } from "@/types/api";

export default function ReferralsPage() {
  const qc = useQueryClient();
  const isRe = useSession((s) => s.has("risk_engineer"));
  const [status, setStatus] = useState("open,in_progress");
  const [active, setActive] = useState<Referral | null>(null);
  const [findings, setFindings] = useState("");
  const [rec, setRec] = useState("proceed");
  const [conditions, setConditions] = useState("");
  const q = useQuery({ queryKey: ["referrals", status], queryFn: () => api<Referral[]>(`/api/v1/referrals?status=${status}`) });
  const done = () => void qc.invalidateQueries({ queryKey: ["referrals"] });
  const claim = useMutation({ mutationFn: (id: string) => api(`/api/v1/referrals/${id}/claim`, { method: "POST" }), onSuccess: () => { toast.success("Referral assigned to you"); done(); }, onError: (e) => toast.error((e as Error).message) });
  const complete = useMutation({
    mutationFn: () => api(`/api/v1/referrals/${active!.id}/complete`, { method: "POST", json: { findings, recommendation: rec, conditions: conditions.split("\n").map((c) => c.trim()).filter(Boolean) } }),
    onSuccess: () => { toast.success("Findings attached. Pricing unlocked."); setActive(null); done(); },
    onError: (e) => toast.error((e as Error).message),
  });
  return (
    <div>
      <PageHeader title="Risk engineering referrals" subtitle="Raised at triage and worked in parallel with extraction. Findings unlock pricing." />
      <Tabs value={status} onValueChange={setStatus} className="mb-3">
        <TabsList aria-label="Referral status"><TabsTrigger value="open,in_progress">Open</TabsTrigger><TabsTrigger value="completed">Completed</TabsTrigger></TabsList>
      </Tabs>
      {q.isLoading ? <Skeleton className="h-64" /> : q.isError ? <ErrorState error={q.error} onRetry={() => q.refetch()} />
        : !q.data?.length ? <Card><EmptyState title="No referrals" body="Triage rules raise referrals automatically for high-hazard, old or large risks." /></Card>
        : (
          <div className="grid gap-3 lg:grid-cols-2">
            {q.data.map((r) => (
              <Card key={r.id} className="p-4">
                <div className="flex flex-wrap items-center gap-2">
                  <Link to={`/submissions/${r.submission_id}`} className="font-medium hover:underline">{r.submission?.insured_name}</Link>
                  <span className="font-mono text-xs text-subtle">{r.submission?.reference}</span>
                  <Badge tone={r.status === "completed" ? "ok" : r.status === "in_progress" ? "info" : "warn"}>{humanize(r.status)}</Badge>
                  {r.status !== "completed" && <span className="ml-auto"><SlaTimer dueAt={r.sla_due_at} compact /></span>}
                </div>
                <p className="mt-2 text-sm">{r.reason}</p>
                <p className="mt-1 text-xs text-subtle">{inr(r.submission?.total_sum_insured, { compact: true })} · {r.submission?.occupancy_code} · {r.region}</p>
                {r.findings && <p className="mt-2 rounded-lg bg-muted p-2 text-xs">{humanize(r.recommendation)}: {r.findings}{r.conditions.length ? ` Conditions: ${r.conditions.join("; ")}` : ""}</p>}
                {isRe && r.status !== "completed" && (
                  <div className="mt-3 flex gap-2">
                    {r.status === "open" && <Button size="sm" variant="secondary" onClick={() => claim.mutate(r.id)}><Hand className="h-4 w-4" aria-hidden /> Claim</Button>}
                    <Button size="sm" onClick={() => { setActive(r); setFindings(""); setConditions(""); }}><ClipboardCheck className="h-4 w-4" aria-hidden /> Attach findings</Button>
                  </div>
                )}
              </Card>
            ))}
          </div>
        )}
      <Dialog open={!!active} onOpenChange={(o) => !o && setActive(null)} title="Survey findings" description={active?.submission?.insured_name}
        footer={<><Button variant="secondary" onClick={() => setActive(null)}>Cancel</Button><Button onClick={() => complete.mutate()} disabled={!findings.trim()} loading={complete.isPending}>Complete referral</Button></>}>
        <label className="text-sm font-medium" htmlFor="findings">Findings</label>
        <Textarea id="findings" rows={5} value={findings} onChange={(e) => setFindings(e.target.value)} />
        <label className="mt-3 block text-sm font-medium" htmlFor="rec">Recommendation</label>
        <select id="rec" value={rec} onChange={(e) => setRec(e.target.value)} className="mt-1 h-9 w-full rounded-lg border border-border bg-surface px-2 text-sm">
          <option value="proceed">Proceed</option><option value="proceed_with_conditions">Proceed with conditions</option><option value="decline">Decline</option>
        </select>
        <label className="mt-3 block text-sm font-medium" htmlFor="cond">Conditions (one per line)</label>
        <Input id="cond" value={conditions} onChange={(e) => setConditions(e.target.value)} />
      </Dialog>
    </div>
  );
}

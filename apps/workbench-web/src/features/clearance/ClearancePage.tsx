import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Crown, X } from "lucide-react";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import { Badge, Button, Card, EmptyState, ErrorState, PageHeader, Skeleton } from "@/components/ui/primitives";
import { api } from "@/lib/api";
import { dateTime, inr, pct } from "@/lib/format";
import { useSession } from "@/stores/session";
import type { SubmissionSummary } from "@/types/api";

type Link_ = { id: string; score: number; band: string; status: string; components: Record<string, number>; bor_rule: string;
  first_arrived_id: string; submission: SubmissionSummary; candidate: SubmissionSummary };

function Side({ s, first, label }: { s: SubmissionSummary; first: boolean; label: string }) {
  return (
    <div className="rounded-lg border border-border p-3">
      <p className="mb-1 flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-subtle">{label}{first && <Badge tone="brand"><Crown className="h-3 w-3" aria-hidden />First received</Badge>}</p>
      <Link to={`/submissions/${s.id}`} className="font-medium hover:underline">{s.insured_name}</Link>
      <dl className="mt-2 grid grid-cols-2 gap-1 text-xs">
        <dt className="text-subtle">Broker</dt><dd>{s.broker ?? "—"}</dd>
        <dt className="text-subtle">Received</dt><dd>{dateTime(s.received_at)}</dd>
        <dt className="text-subtle">Sum insured</dt><dd className="tabular-nums">{inr(s.declared_sum_insured, { compact: true })}</dd>
        <dt className="text-subtle">Occupancy</dt><dd>{s.occupancy_code ?? "—"}</dd>
        <dt className="text-subtle">Reference</dt><dd className="font-mono">{s.reference}</dd>
      </dl>
    </div>
  );
}

export default function ClearancePage() {
  const qc = useQueryClient();
  const canResolve = useSession((s) => s.has("data_entry", "underwriter", "senior_underwriter"));
  const q = useQuery({ queryKey: ["clearance"], queryFn: () => api<Link_[]>("/api/v1/clearance") });
  const resolve = useMutation({
    mutationFn: (v: { id: string; confirm: boolean }) => api(`/api/v1/clearance/${v.id}/resolve`, { method: "POST", json: { confirm: v.confirm, reason: v.confirm ? "same risk" : "different risk" } }),
    onMutate: async (v) => {
      await qc.cancelQueries({ queryKey: ["clearance"] });
      const prev = qc.getQueryData<Link_[]>(["clearance"]);
      qc.setQueryData<Link_[]>(["clearance"], (old) => old?.filter((l) => l.id !== v.id));
      return { prev };
    },
    onError: (e, _v, ctx) => { qc.setQueryData(["clearance"], ctx?.prev); toast.error((e as Error).message); },
    onSuccess: (_d, v) => toast.success(v.confirm ? "Linked as duplicate" : "Cleared; submission resumes processing"),
    onSettled: () => qc.invalidateQueries({ queryKey: ["submissions"] }),
  });
  return (
    <div>
      <PageHeader title="Duplicate resolution" subtitle="Same risk via different brokers is caught before any keying. Broker-of-record follows the configured rule." />
      {q.isLoading ? <Skeleton className="h-64" /> : q.isError ? <ErrorState error={q.error} onRetry={() => q.refetch()} />
        : !q.data?.length ? <Card><EmptyState title="No duplicates to review" body="Matches above the auto-link threshold are linked automatically; mid-band matches appear here." /></Card>
        : (
          <ul className="space-y-3">
            {q.data.map((l) => (
              <li key={l.id}>
                <Card className="p-4">
                  <div className="mb-3 flex flex-wrap items-center gap-2">
                    <Badge tone={l.band === "auto" ? "danger" : "warn"}>{l.band === "auto" ? "Auto-linked" : "Needs confirmation"}</Badge>
                    <span className="text-sm font-semibold tabular-nums">Match score {pct(l.score, 0)}</span>
                    <span className="text-xs text-subtle">name {pct(l.components.name, 0)} · address {pct(l.components.address, 0)} · occupancy {pct(l.components.occupancy, 0)} · SI {pct(l.components.sum_insured, 0)} · rule {l.bor_rule}</span>
                    {canResolve && (
                      <div className="ml-auto flex gap-2">
                        <Button size="sm" variant="secondary" onClick={() => resolve.mutate({ id: l.id, confirm: false })}><X className="h-4 w-4" aria-hidden /> Not a duplicate</Button>
                        <Button size="sm" onClick={() => resolve.mutate({ id: l.id, confirm: true })}><Check className="h-4 w-4" aria-hidden /> Confirm duplicate</Button>
                      </div>
                    )}
                  </div>
                  <div className="grid gap-3 md:grid-cols-2">
                    <Side s={l.submission} label="Incoming" first={l.first_arrived_id === l.submission.id} />
                    <Side s={l.candidate} label="Existing" first={l.first_arrived_id === l.candidate.id} />
                  </div>
                </Card>
              </li>
            ))}
          </ul>
        )}
    </div>
  );
}

import { useQuery } from "@tanstack/react-query";
import { Download, ShieldCheck, ShieldX } from "lucide-react";
import { useState } from "react";
import { Badge, Button, Card, EmptyState, ErrorState, Input, PageHeader, Skeleton } from "@/components/ui/primitives";
import { api } from "@/lib/api";
import { dateTime } from "@/lib/format";
import { useSession } from "@/stores/session";

type Ev = { seq: number; ts: string; actor_id: string | null; actor_type: string; action: string; entity_type: string; entity_id: string; data: Record<string, unknown>; hash: string; prev_hash: string };

export default function AuditPage() {
  const canVerify = useSession((s) => s.has("cuo", "admin"));
  const [filters, setFilters] = useState({ action: "", entity_id: "" });
  const [applied, setApplied] = useState(filters);
  const [open, setOpen] = useState<number | null>(null);
  const qs = new URLSearchParams(Object.entries(applied).filter(([, v]) => v));
  const q = useQuery({ queryKey: ["audit", qs.toString()], queryFn: () => api<{ items: Ev[]; total: number }>(`/api/v1/audit?limit=200&${qs}`) });
  const verify = useQuery({ queryKey: ["audit-verify"], queryFn: () => api<{ valid: boolean; checked: number; broken_at_seq?: number }>("/api/v1/audit/verify"), enabled: canVerify });
  const exportFile = async (fmt: string) => {
    const res = await api<Response>(`/api/v1/audit/export?fmt=${fmt}&${qs}`, { raw: true });
    const url = URL.createObjectURL(await res.blob());
    const a = Object.assign(document.createElement("a"), { href: url, download: `nsip-audit.${fmt === "csv" ? "csv" : "jsonl"}` });
    a.click();
    URL.revokeObjectURL(url);
  };
  return (
    <div>
      <PageHeader title="Audit explorer" subtitle="Append-only, hash-chained record of every decision, edit and system action."
        actions={canVerify && <><Button variant="secondary" size="sm" onClick={() => exportFile("csv")}><Download className="h-4 w-4" aria-hidden />CSV</Button><Button variant="secondary" size="sm" onClick={() => exportFile("jsonl")}><Download className="h-4 w-4" aria-hidden />JSONL</Button></>} />
      {verify.data && (
        <Card className="mb-3 flex items-center gap-2 p-3 text-sm" role="status">
          {verify.data.valid ? <><ShieldCheck className="h-4 w-4 text-ok" aria-hidden /> Chain verified: {verify.data.checked} events intact.</>
            : <><ShieldX className="h-4 w-4 text-danger" aria-hidden /> Chain broken at event #{verify.data.broken_at_seq}. Escalate per runbook.</>}
        </Card>
      )}
      <form className="mb-3 flex flex-wrap gap-2" onSubmit={(e) => { e.preventDefault(); setApplied(filters); }} role="search">
        <Input aria-label="Action prefix" placeholder="Action, e.g. quote or field.edited" value={filters.action} onChange={(e) => setFilters({ ...filters, action: e.target.value })} className="w-64" />
        <Input aria-label="Entity ID" placeholder="Entity ID (submission, quote…)" value={filters.entity_id} onChange={(e) => setFilters({ ...filters, entity_id: e.target.value })} className="w-80" />
        <Button type="submit" size="md">Filter</Button>
      </form>
      <Card>
        {q.isLoading ? <Skeleton className="m-4 h-64" /> : q.isError ? <ErrorState error={q.error} onRetry={() => q.refetch()} />
          : !q.data?.items.length ? <EmptyState title="No events match" /> : (
            <ul className="divide-y divide-border text-sm">
              {q.data.items.map((e) => (
                <li key={e.seq}>
                  <button className="flex w-full flex-wrap items-center gap-3 px-4 py-2 text-left hover:bg-muted/50" aria-expanded={open === e.seq} onClick={() => setOpen(open === e.seq ? null : e.seq)}>
                    <span className="w-12 font-mono text-xs text-subtle">#{e.seq}</span>
                    <span className="w-32 text-xs text-subtle">{dateTime(e.ts)}</span>
                    <Badge tone={e.actor_type === "human" ? "brand" : "neutral"}>{e.actor_type}</Badge>
                    <span className="font-medium">{e.action}</span>
                    <span className="text-xs text-subtle">{e.entity_type} {e.entity_id.slice(0, 8)}</span>
                    <span className="ml-auto font-mono text-[11px] text-subtle">{e.hash.slice(0, 12)}…</span>
                  </button>
                  {open === e.seq && <pre className="mx-4 mb-3 overflow-auto rounded-lg bg-muted p-3 text-[11px]">{JSON.stringify({ ...e.data, prev_hash: e.prev_hash, hash: e.hash, actor_id: e.actor_id }, null, 2)}</pre>}
                </li>
              ))}
            </ul>
          )}
      </Card>
    </div>
  );
}

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { createColumnHelper, flexRender, getCoreRowModel, useReactTable } from "@tanstack/react-table";
import { AlertTriangle, ChevronLeft, ChevronRight, RefreshCw, ShieldAlert } from "lucide-react";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate, useSearchParams } from "react-router-dom";
import { InjectionBadge, OutcomeBadge, SlaTimer, StatusBadge } from "@/components/ui/domain";
import { Badge, Button, Card, EmptyState, ErrorState, Input, PageHeader, Skeleton, Tabs, TabsList, TabsTrigger } from "@/components/ui/primitives";
import { api } from "@/lib/api";
import { dateTime, inr } from "@/lib/format";
import type { Page, SubmissionSummary } from "@/types/api";

const QUEUES = [
  { key: "review", label: "In review" }, { key: "triage", label: "Triage" }, { key: "ready", label: "Ready / rated" },
  { key: "manual", label: "Manual" }, { key: "closed", label: "Closed" }, { key: "all", label: "All" },
];
const col = createColumnHelper<SubmissionSummary>();

export default function QueuePage() {
  const { t } = useTranslation();
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const queue = params.get("queue") ?? "review";
  const [q, setQ] = useState(params.get("q") ?? "");
  const [page, setPage] = useState(1);
  const region = params.get("region") ?? "";
  const priority = params.get("priority") ?? "";
  const sort = params.get("sort") ?? "sla";

  const qs = new URLSearchParams({ page: String(page), page_size: "25", sort });
  if (queue !== "all") qs.set("queue", queue);
  if (q) qs.set("q", q);
  if (region) qs.set("region", region);
  if (priority) qs.set("priority", priority);
  const data = useQuery({ queryKey: ["submissions", qs.toString()], queryFn: () => api<Page<SubmissionSummary>>(`/api/v1/submissions?${qs}`), placeholderData: keepPreviousData });

  const columns = useMemo(() => [
    col.accessor("reference", { header: "Reference", cell: (c) => <span className="font-mono text-xs">{c.getValue()}</span> }),
    col.accessor("insured_name", {
      header: "Insured", cell: (c) => (
        <div className="min-w-[12rem]">
          <div className="font-medium">{c.getValue() || "Unnamed insured"}</div>
          <div className="text-xs text-subtle">{c.row.original.broker ?? "Unknown broker"} · {c.row.original.channel}</div>
        </div>
      ),
    }),
    col.accessor("status", { header: "Status", cell: (c) => <div className="flex flex-wrap gap-1"><StatusBadge status={c.getValue()} />{c.row.original.has_pending_update && <Badge tone="info">Updated SOV</Badge>}</div> }),
    col.accessor("triage_outcome", { header: "Triage", cell: (c) => <OutcomeBadge outcome={c.getValue()} /> }),
    col.accessor("total_sum_insured", { header: "Sum insured", cell: (c) => <span className="tabular-nums">{inr(c.getValue(), { compact: true })}</span> }),
    col.display({
      id: "flags", header: "Flags", cell: (c) => (
        <div className="flex gap-1">
          {c.row.original.injection_flagged && <InjectionBadge />}
          {c.row.original.sov_reconciled === false && <Badge tone="danger"><AlertTriangle className="h-3 w-3" aria-hidden />SOV mismatch</Badge>}
          {c.row.original.referral_status === "open" && <Badge tone="warn">RE referral</Badge>}
        </div>
      ),
    }),
    col.accessor("region", { header: "Region", cell: (c) => <span className="capitalize">{c.getValue()}</span> }),
    col.accessor("received_at", { header: "Received", cell: (c) => <span className="text-xs text-subtle">{dateTime(c.getValue())}</span> }),
    col.accessor("sla_due_at", { header: "SLA", cell: (c) => ["quoted", "declined", "duplicate"].includes(c.row.original.status) ? <span className="text-xs text-subtle">Closed</span> : <SlaTimer dueAt={c.getValue()} compact /> }),
  ], []);
  const table = useReactTable({ data: data.data?.items ?? [], columns, getCoreRowModel: getCoreRowModel() });
  const set = (k: string, v: string) => {
    const p = new URLSearchParams(params);
    if (v) p.set(k, v);
    else p.delete(k);
    setParams(p);
    setPage(1);
  };
  const pages = Math.max(1, Math.ceil((data.data?.total ?? 0) / 25));

  return (
    <div>
      <PageHeader title="Submissions" subtitle="Live queue. Updates arrive in real time as the pipeline completes."
        actions={<Button variant="secondary" size="sm" onClick={() => data.refetch()} loading={data.isFetching}><RefreshCw className="h-4 w-4" aria-hidden /> Refresh</Button>} />
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <Tabs value={queue} onValueChange={(v) => set("queue", v)}>
          <TabsList aria-label="Queue">{QUEUES.map((x) => <TabsTrigger key={x.key} value={x.key}>{x.label}</TabsTrigger>)}</TabsList>
        </Tabs>
        <form className="ml-auto flex flex-wrap gap-2" onSubmit={(e) => { e.preventDefault(); set("q", q); }} role="search">
          <Input aria-label="Search insured or reference" placeholder="Search insured or reference" value={q} onChange={(e) => setQ(e.target.value)} className="w-56" />
          <select aria-label="Region" value={region} onChange={(e) => set("region", e.target.value)} className="h-9 rounded-lg border border-border bg-surface px-2 text-sm">
            <option value="">All regions</option>{["west", "south", "north", "east"].map((r) => <option key={r} value={r}>{r}</option>)}
          </select>
          <select aria-label="Priority" value={priority} onChange={(e) => set("priority", e.target.value)} className="h-9 rounded-lg border border-border bg-surface px-2 text-sm">
            <option value="">Any priority</option><option value="high">High</option><option value="normal">Normal</option>
          </select>
          <select aria-label="Sort" value={sort} onChange={(e) => set("sort", e.target.value)} className="h-9 rounded-lg border border-border bg-surface px-2 text-sm">
            <option value="sla">SLA first</option><option value="received">Newest</option><option value="sum_insured">Largest</option>
          </select>
        </form>
      </div>
      <Card className="overflow-hidden">
        {data.isLoading ? <div className="space-y-2 p-4">{Array.from({ length: 8 }, (_, i) => <Skeleton key={i} className="h-11" />)}</div>
          : data.isError ? <ErrorState error={data.error} onRetry={() => data.refetch()} />
          : !data.data?.items.length ? <EmptyState title={t("common.empty")} body="No submissions match this queue and filter." icon={<ShieldAlert className="h-6 w-6" />} />
          : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="bg-muted/60 text-left text-xs uppercase tracking-wide text-subtle">
                  {table.getHeaderGroups().map((hg) => <tr key={hg.id}>{hg.headers.map((h) => <th key={h.id} scope="col" className="px-3 py-2 font-medium">{flexRender(h.column.columnDef.header, h.getContext())}</th>)}</tr>)}
                </thead>
                <tbody className="divide-y divide-border">
                  {table.getRowModel().rows.map((r) => (
                    <tr key={r.id} tabIndex={0} onClick={() => navigate(`/submissions/${r.original.id}`)} onKeyDown={(e) => e.key === "Enter" && navigate(`/submissions/${r.original.id}`)}
                      className="cursor-pointer hover:bg-muted/50 focus:bg-brand-soft/50" aria-label={`Open ${r.original.reference}`}>
                      {r.getVisibleCells().map((c) => <td key={c.id} className="px-3 py-2.5 align-top">{flexRender(c.column.columnDef.cell, c.getContext())}</td>)}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        <div className="flex items-center justify-between border-t border-border px-3 py-2 text-xs text-subtle">
          <span>{data.data?.total ?? 0} submissions</span>
          <div className="flex items-center gap-1">
            <Button variant="ghost" size="icon" aria-label="Previous page" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}><ChevronLeft className="h-4 w-4" /></Button>
            <span>Page {page} of {pages}</span>
            <Button variant="ghost" size="icon" aria-label="Next page" disabled={page >= pages} onClick={() => setPage((p) => p + 1)}><ChevronRight className="h-4 w-4" /></Button>
          </div>
        </div>
      </Card>
    </div>
  );
}

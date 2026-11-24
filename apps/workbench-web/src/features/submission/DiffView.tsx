import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ArrowRight } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { Badge, Button, Card, CardHeader, EmptyState } from "@/components/ui/primitives";
import { api } from "@/lib/api";
import { dateTime, displayValue } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { SubmissionDetail } from "@/types/api";

const CHANGE_TONE = { added: "ok", changed: "info", removed: "neutral", conflict: "danger", kept_human_edit: "brand" } as const;
const CHANGE_LABEL = { added: "Added", changed: "Changed", removed: "Removed", conflict: "Conflict", kept_human_edit: "Your edit kept" };

/** Side-by-side field-level diff of broker schedule updates; conflicts never overwrite reviewed data. */
export function DiffView({ sub }: { sub: SubmissionDetail }) {
  const qc = useQueryClient();
  const versions = sub.versions.filter((v) => v.version_no > 1);
  const [sel, setSel] = useState(versions.at(-1)?.version_no ?? 0);
  const resolve = useMutation({
    mutationFn: (v: { fieldId: string; keep: "mine" | "incoming" }) => api(`/api/v1/submissions/${sub.id}/fields/${v.fieldId}/resolve`, { method: "POST", json: { keep: v.keep } }),
    onSuccess: () => { toast.success("Conflict resolved"); void qc.invalidateQueries({ queryKey: ["submission", sub.id] }); },
    onError: (e) => toast.error((e as Error).message),
  });
  if (!versions.length) return <EmptyState title="No schedule updates" body="When the broker sends a revised SOV, a field-level comparison appears here." />;
  const v = versions.find((x) => x.version_no === sel) ?? versions.at(-1)!;
  const byPath = new Map(sub.fields.map((f) => [f.path, f]));
  return (
    <Card>
      <CardHeader title={`Version ${v.version_no} changes`} subtitle={`Received ${dateTime(v.created_at)} · unchanged source values keep your corrections`}
        actions={versions.length > 1 && <select aria-label="Version" value={sel} onChange={(e) => setSel(Number(e.target.value))} className="h-8 rounded-lg border border-border bg-surface px-2 text-sm">{versions.map((x) => <option key={x.version_no} value={x.version_no}>v{x.version_no}</option>)}</select>} />
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-muted/60 text-left text-xs uppercase text-subtle"><tr><th className="px-3 py-2">Field</th><th className="px-3 py-2">Before</th><th aria-hidden /><th className="px-3 py-2">After</th><th className="px-3 py-2">Change</th><th className="px-3 py-2"><span className="sr-only">Actions</span></th></tr></thead>
          <tbody className="divide-y divide-border">
            {v.diff.map((d) => {
              const f = byPath.get(d.path);
              const open = d.change === "conflict" && f?.status === "conflict";
              return (
                <tr key={d.path} className={cn(open && "bg-danger/5")}>
                  <td className="px-3 py-2 font-medium">{d.label}</td>
                  <td className="px-3 py-2 tabular-nums text-subtle line-through decoration-danger/40">{displayValue(d.path, d.before)}</td>
                  <td aria-hidden><ArrowRight className="h-3.5 w-3.5 text-subtle" /></td>
                  <td className="px-3 py-2 tabular-nums font-medium">{displayValue(d.path, d.after)}</td>
                  <td className="px-3 py-2"><Badge tone={CHANGE_TONE[d.change]}>{CHANGE_LABEL[d.change]}</Badge></td>
                  <td className="px-3 py-2">
                    {open && f && (
                      <div className="flex gap-1">
                        <Button size="sm" variant="secondary" onClick={() => resolve.mutate({ fieldId: f.id, keep: "mine" })}>Keep mine</Button>
                        <Button size="sm" onClick={() => resolve.mutate({ fieldId: f.id, keep: "incoming" })}>Take update</Button>
                      </div>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

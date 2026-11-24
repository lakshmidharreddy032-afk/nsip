import { useMutation, useQueryClient } from "@tanstack/react-query";
import { AlertCircle, Check, Link2, Pencil } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";
import { ConfidenceChip } from "@/components/ui/domain";
import { Badge, Button, Input, Kbd } from "@/components/ui/primitives";
import { api } from "@/lib/api";
import { displayValue } from "@/lib/format";
import { cn, fieldGroup } from "@/lib/utils";
import type { Field, SourceRef, SubmissionDetail } from "@/types/api";

type Props = { sub: SubmissionDetail; editable: boolean; onHover: (ref: SourceRef | null) => void; onFlag: (f: Field) => void };

/** Structured review form: grouped fields, inline edit with change tracking, keyboard review flow. */
export function FieldForm({ sub, editable, onHover, onFlag }: Props) {
  const qc = useQueryClient();
  const [active, setActive] = useState(0);
  const [editing, setEditing] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [filter, setFilter] = useState<"all" | "attention">("attention");
  const rowRefs = useRef<Record<string, HTMLDivElement | null>>({});
  const key = ["submission", sub.id];

  const ordered = useMemo(() => {
    const needs = (f: Field) => f.status !== "ok" || (f.critical && !f.reviewed);
    const list = sub.fields.filter((f) => filter === "all" || needs(f));
    return list.sort((a, b) => Number(b.critical) - Number(a.critical) || a.path.localeCompare(b.path, undefined, { numeric: true }));
  }, [sub.fields, filter]);

  const groups = useMemo(() => {
    const g = new Map<string, Field[]>();
    for (const f of ordered) g.set(fieldGroup(f.path), [...(g.get(fieldGroup(f.path)) ?? []), f]);
    return [...g.entries()];
  }, [ordered]);
  const flat = useMemo(() => groups.flatMap(([, fs]) => fs), [groups]);

  const patchCache = (updated: Field) =>
    qc.setQueryData<SubmissionDetail>(key, (old) => old && { ...old, fields: old.fields.map((f) => (f.id === updated.id ? updated : f)) });

  const edit = useMutation({
    mutationFn: (v: { f: Field; value: string }) => api<{ field: Field }>(`/api/v1/submissions/${sub.id}/fields/${v.f.id}`, { method: "PATCH", json: { value: v.value, reason: "reviewer correction" } }),
    onMutate: async ({ f, value }) => {
      await qc.cancelQueries({ queryKey: key });
      const prev = qc.getQueryData<SubmissionDetail>(key);
      patchCache({ ...f, value, edited: true, reviewed: true });
      return { prev };
    },
    onError: (e, _v, ctx) => {
      if (ctx?.prev) qc.setQueryData(key, ctx.prev);
      toast.error((e as Error).message);
    },
    onSuccess: () => toast.success("Field updated"),
    onSettled: () => qc.invalidateQueries({ queryKey: key }),
  });
  const accept = useMutation({
    mutationFn: (f: Field) => api<Field>(`/api/v1/submissions/${sub.id}/fields/${f.id}/accept`, { method: "POST" }),
    onMutate: (f) => {
      const prev = qc.getQueryData<SubmissionDetail>(key);
      patchCache({ ...f, reviewed: true });
      return { prev };
    },
    onError: (e, _f, ctx) => {
      if (ctx?.prev) qc.setQueryData(key, ctx.prev);
      toast.error((e as Error).message);
    },
    onSettled: () => qc.invalidateQueries({ queryKey: key }),
  });

  useEffect(() => {
    const f = flat[active];
    if (f) {
      onHover(f.source_ref);
      rowRefs.current[f.id]?.scrollIntoView?.({ block: "nearest" });
    }
  }, [active, flat, onHover]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement)?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || e.ctrlKey || e.metaKey || e.altKey) return;
      const f = flat[active];
      if (e.key === "j" || e.key === "ArrowDown") { setActive((i) => Math.min(i + 1, flat.length - 1)); e.preventDefault(); }
      else if (e.key === "k" || e.key === "ArrowUp") { setActive((i) => Math.max(i - 1, 0)); e.preventDefault(); }
      else if (e.key === "a" && f && editable) { accept.mutate(f); setActive((i) => Math.min(i + 1, flat.length - 1)); }
      else if (e.key === "e" && f && editable) { setEditing(f.id); setDraft(f.value === null ? "" : String(f.value)); e.preventDefault(); }
      else if (e.key === "f" && f) onFlag(f);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [flat, active, editable, accept, onFlag]);

  const attention = sub.fields.filter((f) => f.status !== "ok" || (f.critical && !f.reviewed)).length;

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex flex-wrap items-center gap-2 border-b border-border px-3 py-2 text-xs text-subtle">
        <div role="radiogroup" aria-label="Field filter" className="flex rounded-lg bg-muted p-0.5">
          {(["attention", "all"] as const).map((k) => (
            <button key={k} role="radio" aria-checked={filter === k} onClick={() => { setFilter(k); setActive(0); }}
              className={cn("rounded-md px-2.5 py-1", filter === k && "bg-surface text-fg shadow-sm")}>{k === "attention" ? `Needs attention (${attention})` : `All fields (${sub.fields.length})`}</button>
          ))}
        </div>
        <span className="ml-auto hidden items-center gap-1 lg:flex"><Kbd>J</Kbd>/<Kbd>K</Kbd> move <Kbd>A</Kbd> accept <Kbd>E</Kbd> edit <Kbd>F</Kbd> flag</span>
      </div>
      <div className="min-h-0 flex-1 overflow-auto" role="list" aria-label="Extracted fields">
        {!flat.length && <p className="p-6 text-center text-sm text-subtle">All fields reviewed. Mark the submission ready when you are done.</p>}
        {groups.map(([group, fields]) => (
          <section key={group} aria-label={group}>
            <h3 className="sticky top-0 z-10 bg-surface/95 px-3 py-1.5 text-xs font-semibold uppercase tracking-wide text-subtle backdrop-blur">{group}</h3>
            {fields.map((f) => {
              const idx = flat.indexOf(f);
              const isActive = idx === active;
              return (
                <div key={f.id} role="listitem" ref={(el) => { rowRefs.current[f.id] = el; }} data-testid={`field-${f.path}`}
                  onMouseEnter={() => onHover(f.source_ref)} onFocus={() => setActive(idx)} onClick={() => setActive(idx)}
                  className={cn("group grid grid-cols-[minmax(8rem,11rem)_1fr_auto] items-start gap-3 border-l-2 px-3 py-2 text-sm",
                    isActive ? "border-brand bg-brand-soft/40" : "border-transparent hover:bg-muted/50")}>
                  <div>
                    <div className="font-medium">{f.label}{f.critical && <span className="ml-1 text-danger" title="Critical field">*</span>}</div>
                    <div className="mt-0.5 flex flex-wrap gap-1">
                      <ConfidenceChip confidence={f.confidence} status={f.status} method={f.method} />
                      {f.edited && <Badge tone="info">Edited</Badge>}
                      {f.reviewed && !f.edited && <Badge tone="ok">Reviewed</Badge>}
                    </div>
                  </div>
                  <div className="min-w-0">
                    {editing === f.id ? (
                      <form onSubmit={(e) => { e.preventDefault(); edit.mutate({ f, value: draft }); setEditing(null); }} className="flex gap-2">
                        <Input autoFocus aria-label={`Edit ${f.label}`} value={draft} onChange={(e) => setDraft(e.target.value)} onKeyDown={(e) => e.key === "Escape" && setEditing(null)} />
                        <Button type="submit" size="sm">Save</Button>
                      </form>
                    ) : (
                      <div className="break-words tabular-nums">{displayValue(f.path, f.value)}</div>
                    )}
                    {f.status === "conflict" && <p className="mt-1 text-xs text-danger">Broker update proposes: {displayValue(f.path, f.conflict_value)}. Resolve in the Changes tab.</p>}
                    {f.edited && f.source_value !== f.value && <p className="mt-0.5 text-xs text-subtle">Extracted: {displayValue(f.path, f.source_value)}</p>}
                    {f.validation_errors.map((err) => <p key={err} className="mt-1 flex items-start gap-1 text-xs text-danger"><AlertCircle className="mt-0.5 h-3 w-3 shrink-0" aria-hidden />{err}</p>)}
                    <p className="mt-0.5 flex items-center gap-1 truncate text-[11px] text-subtle"><Link2 className="h-3 w-3" aria-hidden />{refLabel(f.source_ref)}</p>
                  </div>
                  {editable && (
                    <div className="flex gap-1 opacity-70 group-hover:opacity-100">
                      <Button variant="ghost" size="icon" aria-label={`Edit ${f.label}`} onClick={() => { setEditing(f.id); setDraft(f.value === null ? "" : String(f.value)); }}><Pencil className="h-3.5 w-3.5" /></Button>
                      <Button variant="ghost" size="icon" aria-label={`Accept ${f.label}`} disabled={f.status === "conflict"} onClick={() => accept.mutate(f)}><Check className="h-3.5 w-3.5" /></Button>
                    </div>
                  )}
                </div>
              );
            })}
          </section>
        ))}
      </div>
    </div>
  );
}

export function refLabel(r: SourceRef): string {
  if (!r || !Object.keys(r).length) return "Derived";
  if (r.reference) return `Reference data: ${r.reference}`;
  const parts = [r.file ?? "email"];
  if (r.sheet && r.sheet !== "csv") parts.push(r.sheet);
  if (r.cell) parts.push(r.cell);
  if (r.page) parts.push(`page ${r.page}`);
  if (r.line) parts.push(`line ${r.line}`);
  return parts.join(" · ");
}

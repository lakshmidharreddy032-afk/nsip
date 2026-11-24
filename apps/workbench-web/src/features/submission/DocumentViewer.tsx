import { useQuery } from "@tanstack/react-query";
import { FileSpreadsheet, FileText, Image as ImageIcon, Mail, ShieldX } from "lucide-react";
import { lazy, Suspense, useEffect, useMemo, useRef, useState } from "react";
import { Badge, EmptyState, ErrorState, Skeleton, Tabs, TabsList, TabsTrigger } from "@/components/ui/primitives";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";
import type { SourceRef, SubmissionDetail } from "@/types/api";

const PdfView = lazy(() => import("./PdfView"));

type Preview = {
  kind: string; filename: string; ocr_engine: string | null;
  sheets: Array<{ name: string; rows: Array<Array<{ v: string | null; ref: string | null }>> }>;
  lines: Array<{ text: string; page: number | null; line: number | null; bbox: number[] | null; image_size: number[] | null }>;
};

function useBlobUrl(path: string | null) {
  const q = useQuery({
    queryKey: ["blob", path], enabled: !!path, staleTime: Infinity,
    queryFn: async () => URL.createObjectURL(await (await api<Response>(path!, { raw: true })).blob()),
  });
  return q.data;
}

export function DocumentViewer({ sub, highlight }: { sub: SubmissionDetail; highlight: SourceRef | null }) {
  const sources = useMemo(() => [
    { id: "body", label: "Email", icon: Mail },
    ...sub.attachments.map((a) => ({ id: a.id, label: a.filename, icon: /\.(xlsx|xls|csv)$/i.test(a.filename) ? FileSpreadsheet : /\.(png|jpe?g|tiff?)$/i.test(a.filename) ? ImageIcon : FileText, att: a })),
  ], [sub.attachments]);
  const [active, setActive] = useState("body");

  useEffect(() => {
    if (!highlight) return;
    const target = highlight.attachment_id && highlight.attachment_id !== "body" ? highlight.attachment_id : "body";
    if (sources.some((s) => s.id === target)) setActive(target);
  }, [highlight, sources]);

  const current = sources.find((s) => s.id === active);
  return (
    <div className="flex h-full min-h-0 flex-col">
      <Tabs value={active} onValueChange={setActive} className="border-b border-border px-3 py-2">
        <TabsList aria-label="Source documents" className="max-w-full overflow-x-auto">
          {sources.map((s) => (
            <TabsTrigger key={s.id} value={s.id} className="flex items-center gap-1.5">
              <s.icon className="h-3.5 w-3.5" aria-hidden /><span className="max-w-[10rem] truncate">{s.label}</span>
            </TabsTrigger>
          ))}
        </TabsList>
      </Tabs>
      <div className="min-h-0 flex-1 overflow-auto p-3">
        {active === "body" ? <EmailBody sub={sub} highlight={highlight?.attachment_id === "body" || (highlight && !highlight.attachment_id) ? highlight : null} />
          : current && "att" in current && current.att ? (
            current.att.av_status !== "clean"
              ? <EmptyState title="Attachment quarantined" body={`Antivirus status: ${current.att.av_status}. It is not opened in the workbench.`} icon={<ShieldX className="h-6 w-6" />} />
              : <AttachmentView subId={sub.id} attId={current.att.id} filename={current.att.filename} highlight={highlight?.attachment_id === current.att.id ? highlight : null} />
          ) : null}
      </div>
    </div>
  );
}

function useScrollIntoView(dep: unknown) {
  const ref = useRef<HTMLElement | null>(null);
  useEffect(() => {
    ref.current?.scrollIntoView?.({ block: "center", behavior: "smooth" });
  }, [dep]);
  return ref;
}

function EmailBody({ sub, highlight }: { sub: SubmissionDetail; highlight: SourceRef | null }) {
  const lines = `${sub.email?.subject ?? ""}\n${sub.email?.body ?? ""}`.split("\n");
  const ref = useScrollIntoView(highlight?.line);
  return (
    <div className="rounded-lg border border-border bg-bg p-3 font-mono text-xs leading-6">
      <p className="mb-2 font-sans text-xs text-subtle">From {sub.email?.from} · untrusted content, shown as text only</p>
      {lines.map((l, i) => {
        const hl = highlight?.line === i + 1;
        return (
          <div key={i} ref={hl ? (el) => { ref.current = el; } : undefined} className={cn("flex gap-3 whitespace-pre-wrap rounded px-1", hl && "source-hl")}>
            <span className="w-6 shrink-0 select-none text-right text-subtle">{i + 1}</span><span>{l || " "}</span>
          </div>
        );
      })}
    </div>
  );
}

function AttachmentView({ subId, attId, filename, highlight }: { subId: string; attId: string; filename: string; highlight: SourceRef | null }) {
  const preview = useQuery({ queryKey: ["preview", subId, attId], queryFn: () => api<Preview>(`/api/v1/submissions/${subId}/documents/${attId}/preview`), staleTime: Infinity });
  const isImage = /\.(png|jpe?g|tiff?)$/i.test(filename);
  const isPdf = /\.pdf$/i.test(filename);
  const content = `/api/v1/submissions/${subId}/documents/${attId}/content`;
  const blob = useBlobUrl(isImage ? content : null);
  const ref = useScrollIntoView(highlight?.cell ?? highlight?.line);
  if (preview.isLoading) return <Skeleton className="h-96 w-full" />;
  if (preview.isError) return <ErrorState error={preview.error} onRetry={() => preview.refetch()} />;
  const p = preview.data!;
  if (p.kind === "spreadsheet") {
    return (
      <div className="space-y-4">
        {p.sheets.map((sh) => (
          <div key={sh.name}>
            <p className="mb-1 text-xs font-medium text-subtle">Sheet: {sh.name}</p>
            <div className="overflow-auto rounded-lg border border-border">
              <table className="text-xs"><tbody>
                {sh.rows.map((row, r) => (
                  <tr key={r} className="even:bg-muted/40">
                    <td className="select-none border-r border-border px-2 text-right text-subtle">{r + 1}</td>
                    {row.map((c, i) => {
                      const hl = !!highlight?.cell && c.ref === highlight.cell && (!highlight.sheet || highlight.sheet === sh.name);
                      return <td key={i} ref={hl ? (el) => { ref.current = el; } : undefined} className={cn("whitespace-nowrap border-r border-border px-2 py-1", hl && "source-hl")}>{c.v}</td>;
                    })}
                  </tr>
                ))}
              </tbody></table>
            </div>
          </div>
        ))}
      </div>
    );
  }
  if (isImage && blob) {
    const size = p.lines[0]?.image_size;
    return (
      <div className="relative inline-block">
        {p.ocr_engine && <Badge tone="info" className="mb-2">OCR: {p.ocr_engine}</Badge>}
        <div className="relative">
          <img src={blob} alt={`Scanned document ${filename}`} className="max-w-full rounded-lg border border-border" />
          {highlight?.bbox && size && (
            <div ref={(el) => { ref.current = el; }} className="source-hl pointer-events-none absolute rounded" style={{
              left: `${(highlight.bbox[0] / size[0]) * 100}%`, top: `${(highlight.bbox[1] / size[1]) * 100}%`,
              width: `${(highlight.bbox[2] / size[0]) * 100}%`, height: `${(highlight.bbox[3] / size[1]) * 100}%` }} />
          )}
        </div>
      </div>
    );
  }
  return (
    <div className="space-y-3">
      {isPdf && p.kind === "pdf_text" && <Suspense fallback={<Skeleton className="h-96" />}><PdfView url={content} highlight={highlight?.text ?? null} /></Suspense>}
      {p.ocr_engine && <Badge tone="info">Scanned PDF, OCR: {p.ocr_engine}</Badge>}
      <div className="rounded-lg border border-border bg-bg p-3 font-mono text-xs leading-6" aria-label="Extracted text">
        {p.lines.map((l, i) => {
          const hl = highlight?.line === l.line && (highlight?.page ?? 1) === (l.page ?? 1);
          return <div key={i} ref={hl ? (el) => { ref.current = el; } : undefined} className={cn("flex gap-3 whitespace-pre-wrap rounded px-1", hl && "source-hl")}><span className="w-10 shrink-0 text-right text-subtle">{l.page ? `p${l.page}:` : ""}{l.line}</span><span>{l.text}</span></div>;
        })}
      </div>
    </div>
  );
}

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, ArrowLeft, CheckCircle2, Copy, MessageSquareWarning, Stethoscope } from "lucide-react";
import { useCallback, useState } from "react";
import { Panel, PanelGroup, PanelResizeHandle } from "react-resizable-panels";
import { Link, useParams } from "react-router-dom";
import { toast } from "sonner";
import { InjectionBadge, OutcomeBadge, SlaTimer, StatusBadge } from "@/components/ui/domain";
import { Badge, Button, Card, Dialog, ErrorState, Skeleton, Tabs, TabsContent, TabsList, TabsTrigger, Textarea } from "@/components/ui/primitives";
import { api } from "@/lib/api";
import { inr } from "@/lib/format";
import { useSession } from "@/stores/session";
import type { Field, SourceRef, SubmissionDetail } from "@/types/api";
import { RatingPanel } from "@/features/rating/RatingPanel";
import { TriagePanel } from "@/features/triage/TriagePanel";
import { DiffView } from "./DiffView";
import { DocumentViewer } from "./DocumentViewer";
import { FieldForm } from "./FieldForm";

export default function ReviewPage() {
  const { id = "" } = useParams();
  const qc = useQueryClient();
  const canEdit = useSession((s) => s.has("data_entry", "underwriter", "senior_underwriter"));
  const q = useQuery({ queryKey: ["submission", id], queryFn: () => api<SubmissionDetail>(`/api/v1/submissions/${id}`) });
  const [highlight, setHighlight] = useState<SourceRef | null>(null);
  const [flagged, setFlagged] = useState<Field | null>(null);
  const [infoMsg, setInfoMsg] = useState("");
  const onHover = useCallback((r: SourceRef | null) => setHighlight(r), []);
  const onFlag = useCallback((f: Field) => {
    setFlagged(f);
    setInfoMsg(`Please confirm or provide: ${f.label}.`);
  }, []);

  const ready = useMutation({
    mutationFn: () => api(`/api/v1/submissions/${id}/ready`, { method: "POST" }),
    onSuccess: () => { toast.success("Marked ready for rating"); void qc.invalidateQueries({ queryKey: ["submission", id] }); },
    onError: (e) => toast.error((e as Error).message),
  });
  const requestInfo = useMutation({
    mutationFn: () => api(`/api/v1/submissions/${id}/request-info`, { method: "POST", json: { message: infoMsg } }),
    onSuccess: () => { setFlagged(null); toast.success("Information request sent"); void qc.invalidateQueries({ queryKey: ["submission", id] }); },
    onError: (e) => toast.error((e as Error).message),
  });

  if (q.isLoading) return <div className="space-y-3"><Skeleton className="h-12 w-full" /><Skeleton className="h-[70vh] w-full" /></div>;
  if (q.isError || !q.data) return <ErrorState error={q.error} onRetry={() => q.refetch()} />;
  const s = q.data;
  const editable = canEdit && !["quoted", "declined", "duplicate", "closed"].includes(s.status);
  const conflicts = s.fields.filter((f) => f.status === "conflict").length;

  return (
    <div className="flex h-full min-h-[600px] flex-col gap-3">
      <div className="flex flex-wrap items-center gap-3">
        <Link to="/submissions" aria-label="Back to queue" className="rounded-lg p-1.5 hover:bg-muted"><ArrowLeft className="h-4 w-4" /></Link>
        <div className="min-w-0">
          <h1 className="truncate text-lg font-semibold">{s.insured_name || "Unnamed insured"}</h1>
          <p className="text-xs text-subtle"><span className="font-mono">{s.reference}</span> · {s.broker ?? "Unknown broker"} · {s.line} · {s.region} · {inr(s.total_sum_insured, { compact: true })}</p>
        </div>
        <div className="flex flex-wrap items-center gap-1.5">
          <StatusBadge status={s.status} /><OutcomeBadge outcome={s.triage_outcome} />
          {s.injection_flagged && <InjectionBadge />}
          {s.sov_reconciled === false && <Badge tone="danger"><AlertTriangle className="h-3 w-3" aria-hidden /> SOV does not reconcile</Badge>}
          {s.referral_status === "open" && <Badge tone="warn"><Stethoscope className="h-3 w-3" aria-hidden /> RE referral open</Badge>}
          {s.duplicate_of_id && <Link to={`/submissions/${s.duplicate_of_id}`}><Badge tone="neutral"><Copy className="h-3 w-3" aria-hidden /> Duplicate of original</Badge></Link>}
          {conflicts > 0 && <Badge tone="danger">{conflicts} update conflict(s)</Badge>}
        </div>
        <div className="ml-auto flex items-center gap-2">
          {!["quoted", "declined", "duplicate"].includes(s.status) && <SlaTimer dueAt={s.sla_due_at} />}
          {editable && ["in_review", "needs_info", "info_requested"].includes(s.status) && (
            <Button onClick={() => ready.mutate()} loading={ready.isPending}><CheckCircle2 className="h-4 w-4" aria-hidden /> Mark ready</Button>
          )}
        </div>
      </div>
      {s.pipeline_error && <Card className="border-danger/30 bg-danger/5 p-3 text-sm text-danger" role="alert">Automated processing stopped: {s.pipeline_error}. Complete this submission manually.</Card>}
      <Card className="min-h-0 flex-1 overflow-hidden">
        <PanelGroup direction="horizontal" autoSaveId="nsip-review">
          <Panel defaultSize={48} minSize={25}>
            <DocumentViewer sub={s} highlight={highlight} />
          </Panel>
          <PanelResizeHandle className="w-1.5 bg-border transition hover:bg-brand/50 focus-visible:bg-brand" aria-label="Resize panels" />
          <Panel defaultSize={52} minSize={30}>
            <Tabs defaultValue="fields" className="flex h-full flex-col">
              <div className="border-b border-border px-3 py-2">
                <TabsList aria-label="Review sections">
                  <TabsTrigger value="fields">Fields</TabsTrigger>
                  <TabsTrigger value="triage">Triage</TabsTrigger>
                  <TabsTrigger value="changes">Changes{s.versions.length > 1 ? ` (v${s.current_version})` : ""}</TabsTrigger>
                  <TabsTrigger value="decision">Rating and decision</TabsTrigger>
                </TabsList>
              </div>
              <TabsContent value="fields" className="min-h-0 flex-1"><FieldForm sub={s} editable={editable} onHover={onHover} onFlag={onFlag} /></TabsContent>
              <TabsContent value="triage" className="min-h-0 flex-1 overflow-auto p-3"><TriagePanel sub={s} /></TabsContent>
              <TabsContent value="changes" className="min-h-0 flex-1 overflow-auto p-3"><DiffView sub={s} /></TabsContent>
              <TabsContent value="decision" className="min-h-0 flex-1 overflow-auto p-3"><RatingPanel sub={s} /></TabsContent>
            </Tabs>
          </Panel>
        </PanelGroup>
      </Card>
      <Dialog open={!!flagged} onOpenChange={(o) => !o && setFlagged(null)} title="Request information from broker" description={flagged ? `Flagged field: ${flagged.label}` : undefined}
        footer={<><Button variant="secondary" onClick={() => setFlagged(null)}>Cancel</Button><Button onClick={() => requestInfo.mutate()} loading={requestInfo.isPending} disabled={infoMsg.trim().length < 10}><MessageSquareWarning className="h-4 w-4" aria-hidden /> Send request</Button></>}>
        <Textarea aria-label="Message to broker" rows={5} value={infoMsg} onChange={(e) => setInfoMsg(e.target.value)} />
      </Dialog>
    </div>
  );
}

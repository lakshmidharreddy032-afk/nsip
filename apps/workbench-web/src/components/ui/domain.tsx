import { Clock, ShieldAlert } from "lucide-react";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { duration } from "@/lib/format";
import { cn, confidenceTone, slaTone } from "@/lib/utils";
import { Badge, type Tone } from "./primitives";

export function ConfidenceChip({ confidence, status, method }: { confidence: number; status?: string; method?: string }) {
  const tone = confidenceTone(confidence, status);
  const label = status === "conflict" ? "Conflict" : status === "invalid" ? "Invalid" : `${Math.round(confidence * 100)}%`;
  return (
    <Badge tone={tone} title={`Confidence ${Math.round(confidence * 100)}%${method ? ` via ${method}` : ""}`} aria-label={`Confidence ${label}`}>
      <span className={cn("h-1.5 w-1.5 rounded-full", tone === "ok" ? "bg-ok" : tone === "warn" ? "bg-warn" : "bg-danger")} aria-hidden />
      {label}
    </Badge>
  );
}

/** Live 48-hour SLA countdown. */
export function SlaTimer({ dueAt, compact }: { dueAt: string | null; compact?: boolean }) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 30_000);
    return () => clearInterval(t);
  }, []);
  if (!dueAt) return <span className="text-subtle">—</span>;
  const left = (new Date(dueAt).getTime() - now) / 1000;
  const tone = slaTone(left);
  return (
    <Badge tone={tone} aria-label={left <= 0 ? `SLA breached by ${duration(-left)}` : `SLA ${duration(left)} left`}>
      <Clock className="h-3 w-3" aria-hidden />
      {left <= 0 ? `Breached ${duration(-left)}` : compact ? duration(left) : `${duration(left)} left`}
    </Badge>
  );
}

const STATUS_TONE: Record<string, Tone> = {
  in_review: "brand", ready_for_rating: "info", rated: "info", quoted: "ok", declined: "neutral", decline_pending: "danger",
  duplicate: "neutral", clearance_review: "warn", needs_info: "warn", info_requested: "warn", manual_review: "danger", received: "neutral",
};

export function StatusBadge({ status }: { status: string }) {
  const { t } = useTranslation();
  return <Badge tone={STATUS_TONE[status] ?? "neutral"}>{t(`status.${status}`, { defaultValue: status })}</Badge>;
}

const OUTCOME_TONE: Record<string, Tone> = { in_appetite: "ok", out_of_appetite: "danger", refer_risk_engineering: "warn", needs_info: "info" };

export function OutcomeBadge({ outcome }: { outcome: string | null }) {
  const { t } = useTranslation();
  if (!outcome) return <Badge>Pending</Badge>;
  return <Badge tone={OUTCOME_TONE[outcome] ?? "neutral"}>{t(`outcome.${outcome}`, { defaultValue: outcome })}</Badge>;
}

export function InjectionBadge() {
  return (
    <Badge tone="danger" title="Instruction-like text detected in broker content. It was treated as data only.">
      <ShieldAlert className="h-3 w-3" aria-hidden /> Injection flagged
    </Badge>
  );
}

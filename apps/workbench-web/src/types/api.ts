export type Outcome = "in_appetite" | "out_of_appetite" | "refer_risk_engineering" | "needs_info";

export type SubmissionSummary = {
  id: string; reference: string; region: string; status: string; priority: string; line: string;
  insured_name: string; broker: string | null; broker_id: string | null; channel: string; occupancy_code: string | null;
  declared_sum_insured: number | null; total_sum_insured: number | null; triage_outcome: Outcome | null;
  referral_status: string; duplicate_of_id: string | null; injection_flagged: boolean; sov_reconciled: boolean | null;
  has_pending_update: boolean; received_at: string; sla_due_at: string | null; sla_seconds_left: number | null; current_version: number;
};

export type SourceRef = { attachment_id?: string; file?: string; sheet?: string; cell?: string; page?: number; line?: number; bbox?: number[]; text?: string; reference?: string };

export type Field = {
  id: string; path: string; label: string; value: unknown; source_value: unknown; confidence: number; source_ref: SourceRef;
  method: string; model_version: string | null; prompt_version: string | null; validation_errors: string[];
  status: "ok" | "low_confidence" | "invalid" | "conflict"; reviewed: boolean; edited: boolean; critical: boolean;
  conflict_value: unknown; version_no: number;
};

export type Triage = {
  id: string; outcome: Outcome; fired_rules: Array<{ rule_id: string; name: string; outcome: string; decline_reason: string }>;
  rule_version: number; features: Record<string, unknown>; llm_signals: Record<string, unknown>; rationale: string;
  decline_draft: string | null; stage: string; override_outcome: string | null; override_reason: string | null; created_at: string;
};

export type RatingRun = { id: string; source: string; source_version: string; filing_ref: string; workbook_hash: string | null;
  inputs_hash: string; inputs: Record<string, unknown>; outputs: Record<string, string>; premium: string; created_at: string };

export type AuthorityCheck = { allowed: boolean; reasons: string[]; limit: Record<string, unknown> | null; requires_referral_to: string | null;
  line: string; sum_insured: number; premium: string; region: string };

export type Referral = { id: string; submission_id: string; kind: string; reason: string; rule_ids: string[]; status: string; region: string;
  sla_due_at: string | null; sla_seconds_left: number | null; findings: string | null; recommendation: string | null; conditions: string[];
  submission?: { reference: string; insured_name: string; total_sum_insured: number | null; occupancy_code: string | null } };

export type DiffEntry = { path: string; label: string; before: unknown; after: unknown; change: "added" | "changed" | "removed" | "conflict" | "kept_human_edit" };

export type SubmissionDetail = SubmissionSummary & {
  email: { id: string; from: string; subject: string; body: string; message_id: string } | null;
  emails: Array<{ id: string; subject: string; from: string; received_at: string; classification: string; body: string }>;
  attachments: Array<{ id: string; email_id: string; filename: string; content_type: string; size: number; sha256: string; av_status: string; macro_stripped: boolean }>;
  fields: Field[]; triage: Triage | null;
  duplicates: Array<{ id: string; candidate_id: string; score: number; components: Record<string, number>; band: string; status: string }>;
  injection_flags: Array<{ pattern: string; excerpt: string; location: string }>;
  versions: Array<{ version_no: number; created_at: string; diff: DiffEntry[] }>;
  rating_runs: RatingRun[]; referral: Referral | null;
  quote: { id: string; premium: string; policy_admin_ref: string; fast_lane: boolean; audit_seal_hash: string; authority_snapshot: AuthorityCheck } | null;
  decisions: Array<{ action: string; reason: string; created_at: string }>;
  pipeline_error: string | null;
};

export type Page<T> = { items: T[]; total: number; page: number; page_size: number; status_counts: Record<string, number> };

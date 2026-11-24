import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ConfidenceChip, SlaTimer } from "@/components/ui/domain";
import { useSession } from "@/stores/session";
import { detail, mockApi, preview, summary } from "@/test/fixtures";
import AdminPage from "./admin/AdminPage";
import AuditPage from "./audit/AuditPage";
import ClearancePage from "./clearance/ClearancePage";
import DashboardsPage from "./dashboards/DashboardsPage";
import HomePage from "./home/HomePage";
import ProfilePage from "./profile/ProfilePage";
import QueuePage from "./queue/QueuePage";
import ReferralsPage from "./referrals/ReferralsPage";
import ReviewPage from "./submission/ReviewPage";
import { refLabel } from "./submission/FieldForm";

vi.mock("./submission/PdfView", () => ({ default: () => <div>pdf</div> }));
// jsdom has no layout, so the resize handle's global pointer capture would swallow every click.
vi.mock("react-resizable-panels", () => ({
  PanelGroup: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  Panel: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  PanelResizeHandle: () => <div />,
}));

function wrap(ui: ReactNode, path = "/", route = "*") {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[path]}><Routes><Route path={route} element={ui} /></Routes></MemoryRouter>
    </QueryClientProvider>,
  );
}

function login(roles: string[], region = "west") {
  useSession.getState().setToken("tok", 900, { id: "me", email: "me@x", full_name: "Arjun Mehta", region, roles });
}

const page = { items: [summary], total: 1, page: 1, page_size: 25, status_counts: { in_review: 3, decline_pending: 2, manual_review: 1 } };
const ops = { submissions: 40, duplicate_rate: 0.18, median_review_minutes: 12, sla_breaches_open: 2, sla_breaches_closed: 1, target_review_minutes: 15, baseline_keying_minutes: 70,
  triage_outcomes: { in_appetite: 20, out_of_appetite: 18 }, cost: { per_submission_inr: 5.6, per_submission_breakdown_inr: { llm_tokens: 1.2, ocr: 0.4 } },
  volume_by_day: [{ date: "2026-11-20", count: 4 }], status_counts: { in_review: 3 }, manual_queue: 0 };

beforeEach(() => login(["underwriter"]));
afterEach(() => vi.unstubAllGlobals());

describe("small components", () => {
  it("confidence chip and SLA timer", () => {
    render(<><ConfidenceChip confidence={0.95} /><ConfidenceChip confidence={0.5} status="invalid" /><SlaTimer dueAt={new Date(Date.now() - 3600_000).toISOString()} /><SlaTimer dueAt={null} /></>);
    expect(screen.getByLabelText("Confidence 95%")).toBeInTheDocument();
    expect(screen.getByLabelText("Confidence Invalid")).toBeInTheDocument();
    expect(screen.getByText(/Breached/)).toBeInTheDocument();
    expect(refLabel({ file: "SOV.xlsx", sheet: "SOV", cell: "D2" })).toBe("SOV.xlsx · SOV · D2");
    expect(refLabel({})).toBe("Derived");
    expect(refLabel({ reference: "pincode" })).toMatch(/Reference/);
    expect(refLabel({ file: "a.pdf", page: 1, line: 3 })).toBe("a.pdf · page 1 · line 3");
  });
});

describe("home and queue", () => {
  it("home shows KPIs and next-up queue", async () => {
    mockApi([{ match: /submissions\?/, body: page }, { match: /dashboards\/ops/, body: ops }]);
    wrap(<HomePage />);
    expect(await screen.findByText("Apex Shakti Technologies Pvt Ltd")).toBeInTheDocument();
    expect(await screen.findByText("12 min")).toBeInTheDocument();
    expect(screen.getByText(/need manual handling/)).toBeInTheDocument();
  });
  it("queue renders table, filters and paging", async () => {
    const calls = mockApi([{ match: /submissions\?/, body: page }]);
    wrap(<QueuePage />, "/submissions?queue=review");
    expect(await screen.findByText("NSIP-2026-000001")).toBeInTheDocument();
    expect(screen.getByText("SOV mismatch")).toBeInTheDocument();
    expect(screen.getByText("Updated SOV")).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText("Search insured or reference"), "apex{enter}");
    await userEvent.selectOptions(screen.getByLabelText("Region"), "west");
    await userEvent.selectOptions(screen.getByLabelText("Sort"), "received");
    await userEvent.click(screen.getByRole("tab", { name: "Closed" }));
    await waitFor(() => expect(calls.some((c) => c.url.includes("q=apex"))).toBe(true));
    expect(calls.some((c) => c.url.includes("queue=closed"))).toBe(true);
  });
  it("queue empty and error states", async () => {
    mockApi([{ match: /submissions\?/, body: { ...page, items: [], total: 0 } }]);
    wrap(<QueuePage />);
    expect(await screen.findByText(/No submissions match/)).toBeInTheDocument();
  });
});

describe("review", () => {
  const routes = () => [
    { match: /\/api\/v1\/submissions\/s1$/, body: detail },
    { match: /documents\/a1\/preview/, body: preview },
    { method: "POST", match: /\/accept$/, body: {} },
    { method: "PATCH", match: /\/fields\//, body: { field: detail.fields[0] } },
    { method: "POST", match: /\/resolve$/, body: {} },
    { method: "POST", match: /\/ready$/, status: 422, body: { detail: { message: "Fix invalid critical fields first" } } },
    { method: "POST", match: /\/request-info$/, body: summary },
    { method: "POST", match: /\/triage\/override$/, body: summary },
    { method: "POST", match: /\/rating$/, body: { rating_run: { id: "r1", source: "rating_api", source_version: "NSG-PKG-2026.1", filing_ref: "F", workbook_hash: null, inputs_hash: "h", inputs: {}, outputs: { premium: "47520", gst_18pct: "8554", base_rate_per_mille: "0.45" }, premium: "47520", created_at: "" }, authority: { allowed: true, reasons: [], limit: {}, requires_referral_to: null, line: "package", sum_insured: 1, premium: "47520", region: "west" }, fast_lane: true } },
    { method: "POST", match: /\/quote$/, body: { policy_admin_ref: "PA-1", premium: "47520" } },
  ];

  it("shows split review with flags, fields and source highlight", async () => {
    mockApi(routes());
    wrap(<ReviewPage />, "/submissions/s1", "/submissions/:id");
    expect(await screen.findByText("Apex Shakti Technologies Pvt Ltd")).toBeInTheDocument();
    expect(screen.getByText(/Automated processing stopped/)).toBeInTheDocument();
    expect(screen.getByText("SOV does not reconcile")).toBeInTheDocument();
    expect(screen.getByText("SOV total does not reconcile")).toBeInTheDocument();
    expect(screen.getByText(/Broker update proposes/)).toBeInTheDocument();
    // keyboard review: move, accept, edit, flag
    fireEvent.keyDown(window, { key: "j" });
    fireEvent.keyDown(window, { key: "a" });
    fireEvent.keyDown(window, { key: "k" });
    fireEvent.keyDown(window, { key: "e" });
    const input = await screen.findByLabelText(/^Edit /, { selector: "input" });
    await userEvent.clear(input);
    await userEvent.type(input, "4.5 crore{enter}");
    fireEvent.keyDown(window, { key: "f" });
    expect(await screen.findByText("Request information from broker")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /Send request/ }));
    await userEvent.click(await screen.findByRole("radio", { name: /All fields/ }));
    fireEvent.mouseEnter(screen.getByTestId("field-locations[0].sov.stock"));
    expect(await screen.findByText("500000")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("tab", { name: /virus.pdf/ }));
    expect(screen.getByText("Attachment quarantined")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Mark ready" }));
  });

  it("triage, changes and rating tabs", async () => {
    const calls = mockApi(routes());
    wrap(<ReviewPage />, "/submissions/s1", "/submissions/:id");
    await screen.findByText("Apex Shakti Technologies Pvt Ltd");
    await userEvent.click(screen.getByRole("tab", { name: "Triage" }));
    expect(screen.getByText(/advisory only/)).toBeInTheDocument();
    expect(screen.getByText(/ignored for routing/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /Override/ }));
    const dialog = await screen.findByRole("dialog");
    await userEvent.type(within(dialog).getByLabelText(/Reason/), "Survey confirms the risk is fine");
    await userEvent.click(within(dialog).getByRole("button", { name: /Record override/ }));
    await waitFor(() => expect(calls.some((c) => c.url.endsWith("/triage/override"))).toBe(true));
    await userEvent.click(screen.getByRole("tab", { name: /Changes/ }));
    await userEvent.click(screen.getByRole("button", { name: "Keep mine" }));
    await waitFor(() => expect(calls.some((c) => c.url.endsWith("/resolve"))).toBe(true));
    await userEvent.click(screen.getByRole("tab", { name: /Rating and decision/ }));
    expect(screen.getByText(/Mark the submission ready/)).toBeInTheDocument();
  });

  it("rating to quote with explicit confirmation", async () => {
    const ready = { ...detail, status: "ready_for_rating", pipeline_error: null };
    const calls = mockApi([{ match: /\/api\/v1\/submissions\/s1$/, body: ready }, ...routes().slice(1)]);
    wrap(<ReviewPage />, "/submissions/s1", "/submissions/:id");
    await screen.findByText("Apex Shakti Technologies Pvt Ltd");
    await userEvent.click(screen.getByRole("tab", { name: /Rating and decision/ }));
    await userEvent.click(screen.getByRole("button", { name: /Run rating/ }));
    expect(await screen.findByText("NSG-PKG-2026.1")).toBeInTheDocument();
    expect(screen.getByText(/Within your authority/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /Fast lane/ }));
    await userEvent.click(await screen.findByRole("button", { name: "Confirm and issue" }));
    await waitFor(() => expect(calls.find((c) => c.url.endsWith("/quote"))?.body).toEqual({ rating_run_id: "r1", confirm: true }));
  });

  it("decline confirmation", async () => {
    const pending = { ...detail, status: "decline_pending", triage: { ...detail.triage!, outcome: "out_of_appetite" as const } };
    const calls = mockApi([{ match: /\/api\/v1\/submissions\/s1$/, body: pending }, { method: "POST", match: /triage\/decline/, body: summary }]);
    wrap(<ReviewPage />, "/submissions/s1", "/submissions/:id");
    await screen.findByText("Apex Shakti Technologies Pvt Ltd");
    await userEvent.click(screen.getByRole("tab", { name: "Triage" }));
    await userEvent.click(screen.getByRole("button", { name: /Confirm and send decline/ }));
    await waitFor(() => expect(calls.some((c) => c.url.endsWith("/triage/decline"))).toBe(true));
  });
});

describe("other pages", () => {
  it("clearance resolves duplicates optimistically", async () => {
    const link = { id: "l1", score: 0.93, band: "auto", status: "linked", components: { name: 1, address: 0.9, occupancy: 1, sum_insured: 1 }, bor_rule: "first_received", first_arrived_id: "s2", submission: summary, candidate: { ...summary, id: "s2", reference: "NSIP-2026-000000" } };
    const calls = mockApi([{ match: /\/api\/v1\/clearance$/, body: [link] }, { method: "POST", match: /resolve/, body: summary }]);
    wrap(<ClearancePage />);
    expect(await screen.findByText(/Match score 93%/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /Confirm duplicate/ }));
    await waitFor(() => expect(calls.some((c) => c.method === "POST")).toBe(true));
  });

  it("referrals claim and complete", async () => {
    login(["risk_engineer"]);
    const ref = { id: "r1", submission_id: "s1", kind: "risk_engineering", reason: "APP-007 High hazard", rule_ids: ["APP-007"], status: "open", region: "west", sla_due_at: summary.sla_due_at, sla_seconds_left: 1, findings: null, recommendation: null, conditions: [], submission: { reference: "NSIP-1", insured_name: "Apex", total_sum_insured: 1, occupancy_code: "PHARMA_MFG" } };
    const calls = mockApi([{ match: /referrals\?/, body: [ref] }, { method: "POST", match: /claim/, body: ref }, { method: "POST", match: /complete/, body: ref }]);
    wrap(<ReferralsPage />);
    expect(await screen.findByText("APP-007 High hazard")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /Claim/ }));
    await userEvent.click(screen.getByRole("button", { name: /Attach findings/ }));
    await userEvent.type(await screen.findByLabelText("Findings"), "Hydrants adequate");
    await userEvent.click(screen.getByRole("button", { name: "Complete referral" }));
    await waitFor(() => expect(calls.find((c) => c.url.endsWith("/complete"))?.body).toMatchObject({ findings: "Hydrants adequate" }));
  });

  it("dashboards render for CUO", async () => {
    login(["cuo"], "all");
    mockApi([
      { match: /dashboards\/ops/, body: ops },
      { match: /dashboards\/underwriting/, body: { median_time_to_quote_hours: 30, pct_quoted_within_48h: 0.8, median_decline_turnaround_hours: 0.5, quote_to_bind: 0.2, bound: 1, quotes: 5, authority_blocks: 1, fast_lane_quotes: 2, baseline_time_to_quote_days: 6, ai_override_rates: [{ field: "risk.address", override_rate: 0.1 }] } },
      { match: /dashboards\/cuo/, body: { outcome_hierarchy: [{ metric: "Loss ratio", role: "guardrail", rule: "x" }], loss_ratio_by_cohort: { ai_assisted: 0.66, baseline: 0.68 }, loss_ratio_baseline: 0.68, guardrail_ok: true, assistant_disagreement_rate: 0.1, avg_extraction_confidence: 0.95, claims_snapshot_date: "2026-11-01", loss_ratio_monthly: [{ month: "2026-10", cohort: "baseline", loss_ratio: 0.68 }], appetite_rule_hits: [{ rule_id: "APP-001", rate: 0.2 }], triaged: 10, drift_alerts: [{ message: "Out-of-appetite share moved", severity: "warning" }] } },
      { match: /dashboards\/distribution\?broker_id=b1/, body: { brokers: [], broker: { submissions: 4, duplicates: 1, quoted: 2, declined: 1, median_turnaround_hours: 20, win_rate: 0.5, out_of_appetite_share: 0.25 } } },
      { match: /dashboards\/distribution/, body: { brokers: [{ id: "b1", name: "Meridian" }], broker: null } },
    ]);
    wrap(<DashboardsPage />);
    expect(await screen.findByText("Submissions")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("tab", { name: "Underwriting" }));
    expect(await screen.findByText("30 h")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("tab", { name: "CUO" }));
    expect(await screen.findByText(/guardrail holding/)).toBeInTheDocument();
    expect(screen.getByText("Out-of-appetite share moved")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("tab", { name: "Distribution" }));
    await userEvent.selectOptions(await screen.findByLabelText("Broker"), "b1");
    expect(await screen.findByText("50.0%")).toBeInTheDocument();
  });

  it("admin sections", async () => {
    login(["admin", "cuo"], "all");
    const calls = mockApi([
      { match: /auth\/admin\/users$/, body: [{ id: "u1", full_name: "Arjun", email: "a@x", region: "west", roles: ["underwriter"], mfa_enabled: true, locked: false, last_login_at: null }] },
      { match: /admin\/authority$/, body: [{ id: "l1", user: "Arjun", line: "property", max_sum_insured: 250000000, max_premium: 1000000, regions: ["west"], status: "pending", version: 2, maker_id: "other" }] },
      { match: /api\/v1\/admin\/users$/, body: [{ id: "u1", full_name: "Arjun", email: "a@x" }] },
      { method: "POST", match: /authority\/l1\/decide/, body: {} },
      { match: /appetite\/versions$/, body: [{ id: "v2", version_no: 2, status: "draft", notes: "n", test_report: { evaluated: 10, changed: 1, newly_declined_previously_in_appetite: 0 }, rules: [{ id: "APP-001", name: "Prohibited", outcome: "out_of_appetite", condition: {} }] }, { id: "v1", version_no: 1, status: "approved", notes: "", test_report: {}, rules: [] }] },
      { method: "POST", match: /versions\/v2\/approve/, body: {} },
      { match: /admin\/mappings$/, body: [{ id: "m1", layout_id: "LEARNED-1", status: "proposed", source: "llm", broker_hint: "b", times_used: 1, mapping: { "unit ref": { field: "loc_no", unit_multiplier: 1 } } }] },
      { method: "POST", match: /mappings\/m1\/decide/, body: {} },
      { match: /admin\/flags$/, body: [{ key: "region.west", enabled: true, description: "Pilot" }] },
      { method: "PUT", match: /flags\/region.west/, body: {} },
      { match: /admin\/integrations$/, body: { budgets: {} } },
      { match: /admin\/cost$/, body: { projected_monthly_inr: 50000, projected_llm_monthly_inr: 1000, budgets: { monthly_budget_inr: 250000 }, alerts: ["Projected cost above 80% of monthly budget"] } },
      { method: "PUT", match: /roles$/, body: {} },
    ]);
    wrap(<AdminPage />);
    await userEvent.click(await screen.findByRole("button", { name: "Approve" }));
    await userEvent.click(screen.getByRole("tab", { name: "Appetite rules" }));
    await userEvent.click(await screen.findByRole("button", { name: /Approve \(CUO\)/ }));
    await userEvent.click(screen.getByRole("button", { name: /Draft new version/ }));
    expect(await screen.findByLabelText("Rules JSON")).toBeInTheDocument();
    await userEvent.keyboard("{Escape}");
    await userEvent.click(screen.getByRole("tab", { name: "SOV mappings" }));
    await userEvent.click(await screen.findByRole("button", { name: /Approve/ }));
    await userEvent.click(screen.getByRole("tab", { name: /Integrations/ }));
    await userEvent.click(await screen.findByRole("switch", { name: "region.west" }));
    expect(await screen.findByText(/above 80%/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("tab", { name: "Users" }));
    await userEvent.click(await screen.findByRole("button", { name: "CUO" }));
    await waitFor(() => expect(calls.filter((c) => c.method !== "GET").length).toBeGreaterThanOrEqual(5));
  });

  it("audit explorer and profile", async () => {
    login(["cuo"], "all");
    mockApi([
      { match: /audit\/verify/, body: { valid: true, checked: 12 } },
      { match: /\/api\/v1\/audit\?/, body: { items: [{ seq: 1, ts: "2026-11-20T10:00:00Z", actor_id: "u", actor_type: "human", action: "quote.issued", entity_type: "quote", entity_id: "abcdef123", data: { premium: "1" }, hash: "h".repeat(64), prev_hash: "0".repeat(64) }], total: 1 } },
      { match: /\/api\/v1\/me/, body: { mfa: true, authority: [{ limit_id: "l", line: "property", max_sum_insured: 1e8, max_premium: 1e6, regions: ["west"] }] } },
      { match: /auth\/sessions$/, body: [{ id: "x1", created_at: "", last_seen_at: "", ip: "1.1.1.1", user_agent: "Chrome", current: true, mfa_verified: true }, { id: "x2", created_at: "", last_seen_at: "", ip: "2.2.2.2", user_agent: "Edge", current: false, mfa_verified: true }] },
      { method: "DELETE", match: /sessions\/x2/, body: {} },
    ]);
    wrap(<AuditPage />);
    expect(await screen.findByText(/Chain verified: 12/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /quote.issued/ }));
    expect(screen.getByText(/"premium"/)).toBeInTheDocument();
    cleanupAndProfile();
    expect(await screen.findByText(/two-step verification/)).toBeInTheDocument();
    await userEvent.click(await screen.findByRole("button", { name: "Sign out" }));
  });
});

function cleanupAndProfile() {
  document.body.innerHTML = "";
  wrap(<ProfilePage />);
}

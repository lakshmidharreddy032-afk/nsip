import { afterEach, describe, expect, it, vi } from "vitest";
import { useSession } from "@/stores/session";
import { applyTheme, useUi } from "@/stores/ui";
import { api, ApiError, refreshSession } from "./api";
import { dateTime, displayValue, duration, groupIndian, humanize, inr, isMoneyPath, parseInr, pct } from "./format";
import { parseSse } from "./sse";
import { cn, confidenceTone, fieldGroup, slaTone } from "./utils";

afterEach(() => {
  vi.unstubAllGlobals();
  useSession.getState().clear();
});

describe("format", () => {
  it("uses Indian grouping and lakh/crore", () => {
    expect(groupIndian(125000000)).toBe("12,50,00,000");
    expect(groupIndian(999)).toBe("999");
    expect(groupIndian(-150000)).toBe("-1,50,000");
    expect(inr(125000000)).toBe("₹12,50,00,000");
    expect(inr(125000000, { compact: true })).toBe("₹12.5 Cr");
    expect(inr(250000, { compact: true })).toBe("₹2.5 L");
    expect(inr(999, { compact: true })).toBe("₹999");
    expect(inr(null)).toBe("—");
    expect(inr("abc")).toBe("—");
    expect(inr("47520")).toBe("₹47,520");
  });
  it("parses rupee input", () => {
    expect(parseInr("12.5 Cr")).toBe(125000000);
    expect(parseInr("₹ 40 lakh")).toBe(4000000);
    expect(parseInr("1,00,000")).toBe(100000);
    expect(parseInr("lots")).toBeNull();
  });
  it("misc helpers", () => {
    expect(duration(3 * 3600 + 120)).toBe("3h 2m");
    expect(duration(50 * 3600)).toBe("2d 2h");
    expect(duration(-600)).toBe("-10m");
    expect(pct(0.1234)).toBe("12.3%");
    expect(pct(null)).toBe("—");
    expect(dateTime(null)).toBe("—");
    expect(dateTime("2026-11-20T10:00:00Z")).toMatch(/Nov/);
    expect(humanize("out_of_appetite")).toBe("Out of appetite");
    expect(humanize(null)).toBe("—");
    expect(isMoneyPath("locations[0].sov.stock")).toBe(true);
    expect(isMoneyPath("risk.year_built")).toBe(false);
    expect(displayValue("cover.sum_insured", 100000)).toBe("₹1,00,000");
    expect(displayValue("risk.year_built", 1999)).toBe("1999");
    expect(displayValue("x", null)).toBe("—");
  });
});

describe("utils", () => {
  it("tones and groups", () => {
    expect(confidenceTone(0.95)).toBe("ok");
    expect(confidenceTone(0.85)).toBe("warn");
    expect(confidenceTone(0.5)).toBe("danger");
    expect(confidenceTone(0.99, "conflict")).toBe("danger");
    expect(slaTone(-1)).toBe("danger");
    expect(slaTone(3600)).toBe("warn");
    expect(slaTone(null)).toBe("ok");
    expect(slaTone(100000)).toBe("ok");
    expect(fieldGroup("locations[2].sov.total")).toBe("Location 3");
    expect(fieldGroup("loss_history[0].year")).toBe("Loss history");
    expect(fieldGroup("sov.total")).toBe("Schedule totals");
    expect(fieldGroup("cover.deductible")).toBe("Cover");
    expect(fieldGroup("weird.x")).toBe("Other");
    expect(cn("px-2", "px-4")).toBe("px-4");
  });
});

describe("sse", () => {
  it("parses events and keeps partial chunks", () => {
    const { events, rest } = parseSse('event: ready\ndata: {}\n\n: keep-alive\n\nevent: submission.updated\ndata: {"id":"1"}\n\nevent: x\ndata: {bad\n\nevent: partial');
    expect(events).toEqual([{ event: "ready", data: {} }, { event: "submission.updated", data: { id: "1" } }]);
    expect(rest).toBe("event: partial");
  });
});

describe("api client", () => {
  it("sends bearer token and JSON, surfaces API errors", async () => {
    useSession.getState().setToken("tok", 900, { id: "u", email: "e", full_name: "n", region: "west", roles: ["underwriter"] });
    const fetchMock = vi.fn(async () => new Response(JSON.stringify({ detail: { code: "x", message: "Nope" } }), { status: 422 }));
    vi.stubGlobal("fetch", fetchMock);
    await expect(api("/api/v1/x", { method: "POST", json: { a: 1 } })).rejects.toMatchObject({ status: 422, message: "Nope" });
    const [, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(new Headers(init.headers).get("Authorization")).toBe("Bearer tok");
    expect(init.body).toBe('{"a":1}');
  });
  it("refreshes once on 401 then retries", async () => {
    document.cookie = "nsip_csrf=abc";
    const seq = [
      new Response("{}", { status: 401 }),
      new Response(JSON.stringify({ access_token: "new", expires_in: 900, user: { id: "u", email: "e", full_name: "n", region: "west", roles: ["cuo"] } })),
      new Response(JSON.stringify({ ok: 1 })),
    ];
    const fetchMock = vi.fn(async () => seq.shift()!);
    vi.stubGlobal("fetch", fetchMock);
    await expect(api("/api/v1/me")).resolves.toEqual({ ok: 1 });
    expect(useSession.getState().token).toBe("new");
    expect(useSession.getState().has("cuo")).toBe(true);
    const [, refreshInit] = fetchMock.mock.calls[1] as unknown as [string, RequestInit];
    expect((refreshInit.headers as Record<string, string>)["X-CSRF-Token"]).toBe("abc");
  });
  it("refresh failure clears session", async () => {
    await new Promise((r) => setTimeout(r, 5));
    vi.stubGlobal("fetch", vi.fn(async () => new Response("{}", { status: 401 })));
    await expect(refreshSession()).resolves.toBe(false);
    expect(useSession.getState().token).toBeNull();
    expect(new ApiError(1, "c", "m").code).toBe("c");
  });
});

describe("stores", () => {
  it("theme persists and applies", () => {
    useUi.getState().setTheme("dark");
    expect(document.documentElement.getAttribute("data-theme")).toBe("dark");
    applyTheme("light");
    expect(document.documentElement.getAttribute("data-theme")).toBe("light");
    useUi.getState().setPalette(true);
    expect(useUi.getState().paletteOpen).toBe(true);
    useUi.getState().setOnline(false);
    expect(useUi.getState().online).toBe(false);
  });
});

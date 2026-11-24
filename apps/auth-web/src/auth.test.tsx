import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { OtpInput } from "./components/OtpInput";
import { passwordProblems, workbenchUrl } from "./lib/api";
import { LoginPage } from "./pages/LoginPage";
import { ForgotPasswordPage, ResetPasswordPage } from "./pages/PasswordPages";

function mockFetch(routes: Record<string, { status?: number; body: unknown }>) {
  const fn = vi.fn(async (url: string) => {
    const r = routes[url] ?? { status: 404, body: {} };
    return new Response(JSON.stringify(r.body), { status: r.status ?? 200 });
  });
  vi.stubGlobal("fetch", fn);
  return fn;
}

afterEach(() => vi.unstubAllGlobals());

async function fillLogin(email = "a@b.co", pw = "x") {
  await userEvent.type(screen.getByLabelText("Work email"), email);
  await userEvent.type(screen.getByLabelText("Password"), pw);
  await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
}

describe("login", () => {
  it("validates inline and signs in without MFA", async () => {
    mockFetch({ "/auth/config": { body: { sso_enabled: true } }, "/auth/login": { body: { status: "authenticated" } } });
    const redirect = vi.fn();
    render(<MemoryRouter><LoginPage redirect={redirect} /></MemoryRouter>);
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByText("Enter your work email")).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText("Work email"), "dataentry@northstar.example");
    await userEvent.type(screen.getByLabelText("Password"), "Northstar@2026!");
    await userEvent.click(screen.getByRole("button", { name: "Show password" }));
    expect(screen.getByLabelText("Password")).toHaveAttribute("type", "text");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    await waitFor(() => expect(redirect).toHaveBeenCalledWith("/"));
    expect(await screen.findByText(/Continue with Microsoft/)).toBeInTheDocument();
  });

  it("runs the MFA step with auto-advance and auto-submit", async () => {
    mockFetch({
      "/auth/config": { body: { sso_enabled: false } },
      "/auth/login": { body: { status: "mfa_required", mfa_token: "tok-123456789" } },
      "/auth/mfa/verify": { body: { status: "authenticated" } },
    });
    const redirect = vi.fn();
    render(<MemoryRouter><LoginPage redirect={redirect} /></MemoryRouter>);
    await fillLogin("uw@northstar.example");
    expect(await screen.findByText("Two-step verification")).toBeInTheDocument();
    const boxes = await screen.findAllByLabelText(/Digit/, {}, { timeout: 3000 });
    for (const [i, d] of ["1", "2", "3", "4", "5", "6"].entries()) await userEvent.type(boxes[i], d);
    await waitFor(() => expect(redirect).toHaveBeenCalled());
  });

  it("shows lockout errors", async () => {
    mockFetch({ "/auth/config": { body: {} }, "/auth/login": { status: 423, body: { detail: { code: "account_locked", message: "x", retry_after: 120 } } } });
    render(<MemoryRouter><LoginPage redirect={vi.fn()} /></MemoryRouter>);
    await fillLogin();
    expect(await screen.findByRole("alert")).toHaveTextContent("2 minute");
  });

  it("shows enrollment key and handles a bad code", async () => {
    mockFetch({
      "/auth/config": { body: {} },
      "/auth/login": { body: { status: "mfa_enroll_required", mfa_token: "t-1234567890", otpauth_uri: "otpauth://x", secret: "ABCDEF" } },
      "/auth/mfa/verify": { status: 401, body: { detail: { code: "invalid_code", message: "The code is incorrect" } } },
    });
    render(<MemoryRouter><LoginPage redirect={vi.fn()} /></MemoryRouter>);
    await fillLogin();
    expect(await screen.findByLabelText("Setup key")).toHaveTextContent("ABCDEF");
    fireEvent.paste((await screen.findAllByLabelText(/Digit/, {}, { timeout: 3000 }))[0], { clipboardData: { getData: () => "123456" } });
    expect(await screen.findByText("The code is incorrect")).toBeInTheDocument();
    await userEvent.click(screen.getByText("Use a different account"));
    expect(await screen.findByRole("button", { name: "Sign in" }, { timeout: 3000 })).toBeInTheDocument();
  });
});

describe("otp input", () => {
  it("handles backspace and arrows", () => {
    const onChange = vi.fn();
    render(<OtpInput value="12" onChange={onChange} />);
    const boxes = screen.getAllByLabelText(/Digit/);
    fireEvent.keyDown(boxes[2], { key: "Backspace" });
    expect(onChange).toHaveBeenCalledWith("1");
    fireEvent.keyDown(boxes[0], { key: "ArrowRight" });
    expect(document.activeElement).toBe(boxes[1]);
    fireEvent.keyDown(boxes[1], { key: "ArrowLeft" });
    expect(document.activeElement).toBe(boxes[0]);
  });
});

describe("password flows", () => {
  it("forgot password always confirms", async () => {
    mockFetch({ "/auth/password/forgot": { status: 202, body: { status: "accepted" } } });
    render(<MemoryRouter><ForgotPasswordPage /></MemoryRouter>);
    await userEvent.type(screen.getByLabelText("Work email"), "a@b.co");
    await userEvent.click(screen.getByRole("button", { name: "Send reset link" }));
    expect(await screen.findByRole("status")).toHaveTextContent("reset link");
  });

  it("reset validates policy and submits", async () => {
    mockFetch({ "/auth/password/reset": { body: { status: "password_updated" } } });
    render(<MemoryRouter initialEntries={["/reset-password?token=abc.def"]}><ResetPasswordPage /></MemoryRouter>);
    await userEvent.type(screen.getByLabelText("New password"), "short");
    await userEvent.type(screen.getByLabelText("Confirm password"), "other");
    await userEvent.click(screen.getByRole("button", { name: "Update password" }));
    expect(await screen.findByText(/At least 12 characters/)).toBeInTheDocument();
    await userEvent.clear(screen.getByLabelText("New password"));
    await userEvent.type(screen.getByLabelText("New password"), "Brand#NewPass9");
    await userEvent.clear(screen.getByLabelText("Confirm password"));
    await userEvent.type(screen.getByLabelText("Confirm password"), "Brand#NewPass9");
    await userEvent.click(screen.getByRole("button", { name: "Update password" }));
    expect(await screen.findByText("Your password has been updated.")).toBeInTheDocument();
  });

  it("reset without token", () => {
    render(<MemoryRouter initialEntries={["/reset-password"]}><ResetPasswordPage /></MemoryRouter>);
    expect(screen.getByRole("alert")).toHaveTextContent("missing its token");
  });

  it("helpers", () => {
    expect(passwordProblems("abc")).toHaveLength(2);
    expect(passwordProblems("Abcdefgh#1234")).toHaveLength(0);
    window.history.pushState({}, "", "/login?next=//evil.example");
    expect(workbenchUrl()).toBe("/");
    window.history.pushState({}, "", "/login?next=/submissions/1");
    expect(workbenchUrl()).toBe("/submissions/1");
  });
});

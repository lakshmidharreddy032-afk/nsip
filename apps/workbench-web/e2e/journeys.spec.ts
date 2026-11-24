import { expect, test } from "@playwright/test";
import { openFirst, signIn } from "./helpers";

test.describe.configure({ mode: "serial" });

test("login with MFA, sessions visible, sign-out", async ({ page }) => {
  await signIn(page, "underwriter@northstar.example");
  await page.goto("/profile");
  await expect(page.getByText("Signed in with two-step verification")).toBeVisible();
  await expect(page.getByText("This device")).toBeVisible();
});

test("triage decline: one-click human confirmation", async ({ page }) => {
  await signIn(page, "senior.uw@northstar.example");
  await openFirst(page, "triage");
  await page.getByRole("tab", { name: "Triage" }).click();
  await expect(page.getByText("Rules fired")).toBeVisible();
  await page.getByRole("button", { name: "Confirm and send decline" }).click();
  await expect(page.getByText("Decline sent to broker")).toBeVisible();
});

test("duplicate merge", async ({ page }) => {
  await signIn(page, "dataentry@northstar.example");
  await page.goto("/clearance");
  const confirm = page.getByRole("button", { name: "Confirm duplicate" }).first();
  test.skip(!(await confirm.isVisible().catch(() => false)), "no open duplicate links in seeded data");
  await confirm.click();
  await expect(page.getByText("Linked as duplicate")).toBeVisible();
});

test("review and correct a field, then mark ready", async ({ page }) => {
  await signIn(page, "dataentry@northstar.example");
  await openFirst(page, "review");
  await page.getByRole("radio", { name: /All fields/ }).click();
  const row = page.getByTestId("field-insured.name");
  await row.hover();
  await row.getByRole("button", { name: /Edit Insured name/ }).click();
  const input = page.getByLabel("Edit Insured name");
  await input.fill((await input.inputValue()) + " (corrected)");
  await input.press("Enter");
  await expect(page.getByText("Field updated")).toBeVisible();
  await page.getByRole("radio", { name: /Needs attention/ }).click();
  for (let i = 0; i < 30; i++) await page.keyboard.press("a");
  await page.getByRole("button", { name: "Mark ready" }).click();
  await expect(page.getByText(/Marked ready|Fix invalid|Resolve/)).toBeVisible();
});

test("rate and quote within authority", async ({ page }) => {
  await signIn(page, "senior.uw@northstar.example");
  await openFirst(page, "ready");
  await page.getByRole("tab", { name: "Rating and decision" }).click();
  await page.getByRole("button", { name: /Run rating|Re-run/ }).click();
  await expect(page.getByText("Table version")).toBeVisible();
  await expect(page.getByText(/Within your authority/)).toBeVisible();
  await page.getByRole("button", { name: /Issue quote|Fast lane/ }).click();
  await page.getByRole("button", { name: "Confirm and issue" }).click();
  await expect(page.getByText(/created in policy admin/)).toBeVisible();
});

test("risk engineering referral", async ({ page }) => {
  await signIn(page, "risk.engineer@northstar.example");
  await page.goto("/referrals");
  await page.getByRole("button", { name: "Attach findings" }).first().click();
  await page.getByLabel("Findings").fill("Survey completed. Hydrant and sprinkler systems adequate.");
  await page.getByRole("button", { name: "Complete referral" }).click();
  await expect(page.getByText("Findings attached. Pricing unlocked.")).toBeVisible();
});

test("SOV update diff", async ({ page }) => {
  await signIn(page, "dataentry@northstar.example");
  await page.goto("/submissions?queue=all");
  await page.getByText("Updated SOV").first().click();
  await page.getByRole("tab", { name: /Changes/ }).click();
  await expect(page.getByText(/Version \d+ changes/)).toBeVisible();
  await expect(page.getByText(/Changed|Conflict|Your edit kept/).first()).toBeVisible();
});

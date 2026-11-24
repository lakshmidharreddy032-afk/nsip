import { expect, test } from "@playwright/test";
import { openFirst, signIn } from "./helpers";

/**
 * Simulated review time (spec section 15): a reviewer works through every field that needs attention
 * on a pre-filled submission using keyboard review (J/K/A/E) and marks it ready. The scripted pace
 * adds 20 s of reading time per attention field and 3 s per routine field to approximate a human.
 * Target: <= 15 minutes versus the 70-minute keying baseline. Results are appended to the report.
 */
const READ_ATTENTION_MS = 20_000;
const READ_ROUTINE_MS = 3_000;

test("pre-filled review completes within 15 minutes", async ({ page }, info) => {
  test.setTimeout(20 * 60_000);
  await signIn(page, "dataentry@northstar.example");
  await openFirst(page, "review");
  const label = await page.getByRole("radio", { name: /Needs attention/ }).textContent();
  const all = await page.getByRole("radio", { name: /All fields/ }).textContent();
  const attention = Number(label?.match(/\((\d+)\)/)?.[1] ?? 0);
  const total = Number(all?.match(/\((\d+)\)/)?.[1] ?? 0);
  const started = Date.now();
  for (let i = 0; i < attention; i++) await page.keyboard.press("a");
  await page.getByRole("button", { name: "Mark ready" }).click();
  const automation = Date.now() - started;
  const simulatedMs = automation + attention * READ_ATTENTION_MS + (total - attention) * READ_ROUTINE_MS;
  const minutes = simulatedMs / 60_000;
  info.annotations.push({ type: "review_minutes", description: minutes.toFixed(1) });
  console.log(`review fields=${total} attention=${attention} simulated=${minutes.toFixed(1)} min`);
  expect(minutes).toBeLessThanOrEqual(15);
});

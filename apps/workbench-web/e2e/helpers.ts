import { createHmac } from "node:crypto";
import { expect, type Page } from "@playwright/test";

export const PASSWORD = "Northstar@2026!";
const DEMO_TOTP = "JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP"; // demo-only secret seeded for MFA journeys

function base32(s: string): Buffer {
  const abc = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567";
  let bits = "";
  for (const c of s.replace(/=+$/, "")) bits += abc.indexOf(c).toString(2).padStart(5, "0");
  const bytes = bits.match(/.{8}/g) ?? [];
  return Buffer.from(bytes.map((b) => parseInt(b, 2)));
}

export function totp(secret = DEMO_TOTP, offset = 0): string {
  const counter = Math.floor(Date.now() / 1000 / 30) + offset;
  const msg = Buffer.alloc(8);
  msg.writeBigUInt64BE(BigInt(counter));
  const h = createHmac("sha1", base32(secret)).update(msg).digest();
  const o = h[h.length - 1] & 0xf;
  const code = ((h.readUInt32BE(o) & 0x7fffffff) % 1_000_000).toString();
  return code.padStart(6, "0");
}

let lastStep = 0;

/** Sign in through the separate login app, completing MFA when the role requires it. */
export async function signIn(page: Page, email: string) {
  await page.goto("/login/");
  await page.getByLabel("Work email").fill(email);
  await page.getByLabel("Password", { exact: true }).fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  const mfa = page.getByRole("group", { name: "Six-digit verification code" });
  if (await mfa.isVisible({ timeout: 3000 }).catch(() => false)) {
    // TOTP codes are single-use per 30 s step; wait for a fresh step if this one was used.
    let step = Math.floor(Date.now() / 30000);
    while (step <= lastStep) {
      await page.waitForTimeout(1000);
      step = Math.floor(Date.now() / 30000);
    }
    lastStep = step;
    await page.getByLabel("Digit 1").fill("");
    await page.keyboard.type(totp());
  }
  await expect(page).toHaveURL(/\/$|\/submissions/);
  await expect(page.getByRole("navigation", { name: "Primary" }).or(page.getByText("Signing you in"))).toBeVisible();
}

export async function openFirst(page: Page, queue: string) {
  await page.goto(`/submissions?queue=${queue}`);
  const row = page.getByRole("row", { name: /Open NSIP-/ }).first();
  await row.click();
  await expect(page.getByRole("tab", { name: "Fields" })).toBeVisible();
}

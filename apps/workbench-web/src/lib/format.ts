/** Indian number formatting (lakh/crore) and rupee display used throughout the workbench. */
const LAKH = 1_00_000;
const CRORE = 1_00_00_000;

export function groupIndian(n: number): string {
  const neg = n < 0;
  const [int, dec] = Math.abs(n).toFixed(0).split(".");
  const last3 = int.slice(-3);
  const rest = int.slice(0, -3).replace(/\B(?=(\d{2})+(?!\d))/g, ",");
  return (neg ? "-" : "") + (rest ? `${rest},${last3}` : last3) + (dec ? `.${dec}` : "");
}

export function inr(value: number | string | null | undefined, opts: { compact?: boolean } = {}): string {
  if (value === null || value === undefined || value === "") return "—";
  const n = typeof value === "string" ? Number(value) : value;
  if (!Number.isFinite(n)) return "—";
  if (opts.compact) {
    if (Math.abs(n) >= CRORE) return `₹${trim(n / CRORE)} Cr`;
    if (Math.abs(n) >= LAKH) return `₹${trim(n / LAKH)} L`;
  }
  return `₹${groupIndian(n)}`;
}

function trim(x: number): string {
  return x.toFixed(2).replace(/\.?0+$/, "");
}

export function parseInr(text: string): number | null {
  const s = text.trim().toLowerCase().replace(/₹|rs\.?|inr/g, "").trim();
  const m = s.match(/^([\d,]*\.?\d+)\s*(cr|crore|crores|l|lakh|lakhs|lac)?$/);
  if (!m) return null;
  const num = Number(m[1].replace(/,/g, ""));
  const unit = m[2] ?? "";
  if (unit.startsWith("c")) return Math.round(num * CRORE);
  if (unit.startsWith("l")) return Math.round(num * LAKH);
  return Math.round(num);
}

export function duration(seconds: number): string {
  const neg = seconds < 0;
  const s = Math.abs(Math.round(seconds));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const txt = h >= 24 ? `${Math.floor(h / 24)}d ${h % 24}h` : h > 0 ? `${h}h ${m}m` : `${m}m`;
  return neg ? `-${txt}` : txt;
}

export function pct(x: number | null | undefined, digits = 1): string {
  return x === null || x === undefined ? "—" : `${(x * 100).toFixed(digits)}%`;
}

export function dateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("en-IN", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
}

export function humanize(s: string | null | undefined): string {
  if (!s) return "—";
  return s.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());
}

export function isMoneyPath(path: string): boolean {
  return /(sum_insured|\.sov\.|^sov\.total|claims_amount|deductible|amount_paid|amount_outstanding)/.test(path);
}

export function displayValue(path: string, v: unknown): string {
  if (v === null || v === undefined || v === "") return "—";
  if (isMoneyPath(path) && typeof v === "number") return inr(v);
  return String(v);
}

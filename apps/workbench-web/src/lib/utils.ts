import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}

export function confidenceTone(c: number, status?: string): "ok" | "warn" | "danger" {
  if (status === "invalid" || status === "conflict") return "danger";
  if (c >= 0.9) return "ok";
  if (c >= 0.8) return "warn";
  return "danger";
}

export function slaTone(secondsLeft: number | null | undefined): "ok" | "warn" | "danger" {
  if (secondsLeft === null || secondsLeft === undefined) return "ok";
  if (secondsLeft <= 0) return "danger";
  if (secondsLeft < 8 * 3600) return "warn";
  return "ok";
}

export function fieldGroup(path: string): string {
  if (path.startsWith("locations[")) return `Location ${Number(path.match(/\[(\d+)\]/)?.[1] ?? 0) + 1}`;
  if (path.startsWith("loss_history[")) return "Loss history";
  if (path.startsWith("sov.")) return "Schedule totals";
  return ({ insured: "Insured", risk: "Risk", cover: "Cover", loss: "Claims summary", broker: "Broker" } as Record<string, string>)[path.split(".")[0]] ?? "Other";
}

import { motion, useReducedMotion } from "framer-motion";
import { ShieldCheck } from "lucide-react";
import type { ReactNode } from "react";
import { Brand } from "./ui";

/** Branded split layout with an animated gradient mesh (disabled for prefers-reduced-motion). */
export function Shell({ title, subtitle, children }: { title: string; subtitle?: string; children: ReactNode }) {
  const reduce = useReducedMotion();
  return (
    <div className="relative min-h-screen overflow-hidden bg-[#f4f6fc] dark:bg-ink-900">
      <div aria-hidden className="pointer-events-none absolute inset-0">
        <div className="absolute -left-40 -top-40 h-[38rem] w-[38rem] rounded-full bg-brand-400/30 blur-3xl animate-mesh motion-reduce:animate-none" />
        <div className="absolute -bottom-48 right-[-10rem] h-[42rem] w-[42rem] rounded-full bg-indigo-400/25 blur-3xl animate-mesh-slow motion-reduce:animate-none" />
        <div className="absolute left-1/3 top-1/2 h-80 w-80 rounded-full bg-cyan-300/20 blur-3xl animate-mesh motion-reduce:animate-none" />
        <svg className="absolute inset-0 h-full w-full opacity-[0.07] dark:opacity-[0.12]">
          <defs>
            <pattern id="grid" width="32" height="32" patternUnits="userSpaceOnUse">
              <path d="M32 0H0V32" fill="none" stroke="currentColor" strokeWidth="1" />
            </pattern>
          </defs>
          <rect width="100%" height="100%" fill="url(#grid)" className="text-ink-700 dark:text-white" />
        </svg>
      </div>
      <main className="relative mx-auto grid min-h-screen max-w-6xl items-center gap-10 px-4 py-10 lg:grid-cols-2">
        <section className="hidden lg:block" aria-hidden>
          <Brand />
          <h2 className="mt-10 max-w-md text-4xl font-semibold leading-tight tracking-tight text-ink-900 dark:text-white">
            Triage, clear and pre-fill every submission. Underwriters decide.
          </h2>
          <ul className="mt-8 space-y-3 text-sm text-ink-700 dark:text-ink-200">
            {["Appetite triage in minutes, not days", "Duplicate clearance before keying", "Every field traceable to its source"].map((t) => (
              <li key={t} className="flex items-center gap-2">
                <ShieldCheck className="h-4 w-4 text-brand-600" /> {t}
              </li>
            ))}
          </ul>
        </section>
        <motion.section
          initial={reduce ? false : { opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.35, ease: "easeOut" }}
          className="mx-auto w-full max-w-md rounded-3xl border border-white/60 bg-white/75 p-8 shadow-2xl shadow-ink-900/10 backdrop-blur-xl dark:border-ink-700 dark:bg-ink-800/60"
        >
          <div className="mb-6 lg:hidden">
            <Brand />
          </div>
          <h1 className="text-2xl font-semibold tracking-tight text-ink-900 dark:text-white">{title}</h1>
          {subtitle && <p className="mt-1 text-sm text-ink-400">{subtitle}</p>}
          <div className="mt-6">{children}</div>
          <p className="mt-8 text-center text-xs text-ink-400">Internal system for authorised Northstar staff. Activity is audited.</p>
        </motion.section>
      </main>
    </div>
  );
}

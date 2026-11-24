import { useQueryClient } from "@tanstack/react-query";
import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import {
  BarChart3, Command, Copy, FileSearch, Home, Inbox, LogOut, Moon, Settings, ShieldCheck, Stethoscope, Sun, User, WifiOff,
} from "lucide-react";
import { useEffect } from "react";
import { useTranslation } from "react-i18next";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import { toast } from "sonner";
import { Button, Kbd } from "@/components/ui/primitives";
import { logout } from "@/lib/api";
import { subscribe } from "@/lib/sse";
import { cn } from "@/lib/utils";
import { ROLE_LABEL, useSession } from "@/stores/session";
import { useUi } from "@/stores/ui";
import { CommandPalette } from "./CommandPalette";

export const NAV = [
  { to: "/", key: "home", icon: Home, roles: null },
  { to: "/submissions", key: "queue", icon: Inbox, roles: ["data_entry", "underwriter", "senior_underwriter", "risk_engineer", "cuo", "admin"] },
  { to: "/clearance", key: "clearance", icon: Copy, roles: ["data_entry", "underwriter", "senior_underwriter", "cuo", "admin"] },
  { to: "/referrals", key: "referrals", icon: Stethoscope, roles: ["risk_engineer", "underwriter", "senior_underwriter", "cuo", "admin"] },
  { to: "/dashboards", key: "dashboards", icon: BarChart3, roles: null },
  { to: "/audit", key: "audit", icon: FileSearch, roles: ["cuo", "admin", "underwriter", "senior_underwriter"] },
  { to: "/admin", key: "admin", icon: Settings, roles: ["admin", "cuo"] },
] as const;

export function Layout() {
  const { t } = useTranslation();
  const user = useSession((s) => s.user);
  const has = useSession((s) => s.has);
  const { theme, setTheme, setPalette, online } = useUi();
  const qc = useQueryClient();
  const location = useLocation();
  const reduce = useReducedMotion();

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setPalette(true);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [setPalette]);

  useEffect(() => {
    const ctl = new AbortController();
    subscribe((ev) => {
      if (ev.event === "submission.updated") {
        void qc.invalidateQueries({ queryKey: ["submissions"] });
        void qc.invalidateQueries({ queryKey: ["submission", ev.data.id] });
        if (ev.data.status === "in_review") toast.info(`${ev.data.reference} is ready for review`);
      }
    }, ctl.signal);
    return () => ctl.abort();
  }, [qc]);

  const nav = NAV.filter((n) => !n.roles || has(...n.roles));
  const dark = document.documentElement.getAttribute("data-theme") === "dark";

  return (
    <div className="flex h-full">
      <a href="#main" className="skip-link">Skip to content</a>
      <aside className="hidden w-60 shrink-0 flex-col border-r border-border bg-surface md:flex" aria-label="Primary">
        <div className="flex items-center gap-2 px-5 py-4">
          <svg aria-hidden viewBox="0 0 32 32" className="h-7 w-7"><path d="M16 2l3.5 10.5L30 16l-10.5 3.5L16 30l-3.5-10.5L2 16l10.5-3.5z" className="fill-brand" /></svg>
          <div className="leading-tight">
            <div className="text-sm font-semibold">Northstar NSIP</div>
            <div className="text-[11px] text-subtle">Underwriting workbench</div>
          </div>
        </div>
        <nav className="flex-1 space-y-0.5 px-3">
          {nav.map((n) => (
            <NavLink key={n.to} to={n.to} end={n.to === "/"}
              className={({ isActive }) => cn("flex items-center gap-3 rounded-lg px-3 py-2 text-sm transition", isActive ? "bg-brand-soft font-medium text-brand" : "text-subtle hover:bg-muted hover:text-fg")}>
              <n.icon className="h-4 w-4" aria-hidden /> {t(`nav.${n.key}`)}
            </NavLink>
          ))}
        </nav>
        <div className="m-3 rounded-lg border border-border p-3 text-xs text-subtle">
          <p className="flex items-center gap-1.5 font-medium text-fg"><ShieldCheck className="h-3.5 w-3.5 text-ok" aria-hidden /> Human-only quoting</p>
          <p className="mt-1">AI pre-fills and flags. Pricing comes only from filed rates; every quote needs an underwriter.</p>
        </div>
      </aside>
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-14 items-center justify-between gap-3 border-b border-border bg-surface/80 px-4 backdrop-blur">
          <button onClick={() => setPalette(true)} className="flex h-9 w-full max-w-md items-center gap-2 rounded-lg border border-border bg-bg px-3 text-sm text-subtle hover:border-brand/50" aria-label="Open command palette">
            <Command className="h-4 w-4" aria-hidden /> Search submissions or jump to…
            <span className="ml-auto flex gap-1"><Kbd>Ctrl</Kbd><Kbd>K</Kbd></span>
          </button>
          <div className="flex items-center gap-1">
            <Button variant="ghost" size="icon" aria-label={dark ? "Switch to light theme" : "Switch to dark theme"} onClick={() => setTheme(dark ? "light" : theme === "light" ? "dark" : "dark")}>
              {dark ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
            </Button>
            <NavLink to="/profile" className="flex items-center gap-2 rounded-lg px-2 py-1.5 text-sm hover:bg-muted">
              <span className="grid h-7 w-7 place-items-center rounded-full bg-brand-soft text-xs font-semibold text-brand"><User className="h-3.5 w-3.5" aria-hidden /></span>
              <span className="hidden text-left leading-tight sm:block">
                <span className="block font-medium">{user?.full_name}</span>
                <span className="block text-[11px] text-subtle">{user?.roles.map((r) => ROLE_LABEL[r] ?? r).join(", ")} · {user?.region}</span>
              </span>
            </NavLink>
            <Button variant="ghost" size="icon" aria-label="Sign out" onClick={() => void logout()}><LogOut className="h-4 w-4" /></Button>
          </div>
        </header>
        {!online && (
          <div role="status" className="flex items-center gap-2 bg-warn/15 px-4 py-2 text-sm text-warn"><WifiOff className="h-4 w-4" aria-hidden /> {t("common.offline")}</div>
        )}
        <main id="main" className="min-h-0 flex-1 overflow-auto p-4 md:p-6" tabIndex={-1}>
          <AnimatePresence mode="wait" initial={false}>
            <motion.div key={location.pathname} initial={reduce ? false : { opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }}
              exit={reduce ? undefined : { opacity: 0 }} transition={{ duration: 0.18 }} className="h-full">
              <Outlet />
            </motion.div>
          </AnimatePresence>
        </main>
      </div>
      <CommandPalette />
    </div>
  );
}

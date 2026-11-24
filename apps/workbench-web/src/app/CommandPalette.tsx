import * as DialogPrimitive from "@radix-ui/react-dialog";
import { useQuery } from "@tanstack/react-query";
import { Command } from "cmdk";
import { FileText } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { api } from "@/lib/api";
import { useSession } from "@/stores/session";
import { useUi } from "@/stores/ui";
import type { Page, SubmissionSummary } from "@/types/api";
import { NAV } from "./Layout";

export function CommandPalette() {
  const { t } = useTranslation();
  const open = useUi((s) => s.paletteOpen);
  const setOpen = useUi((s) => s.setPalette);
  const has = useSession((s) => s.has);
  const [q, setQ] = useState("");
  const navigate = useNavigate();
  const canSearch = has("data_entry", "underwriter", "senior_underwriter", "risk_engineer", "cuo", "admin");
  const results = useQuery({
    queryKey: ["palette", q],
    queryFn: () => api<Page<SubmissionSummary>>(`/api/v1/submissions?page_size=8&sort=received&q=${encodeURIComponent(q)}`),
    enabled: open && canSearch && q.length >= 2,
  });
  const go = (to: string) => {
    setOpen(false);
    setQ("");
    navigate(to);
  };
  return (
    <DialogPrimitive.Root open={open} onOpenChange={setOpen}>
      <DialogPrimitive.Portal>
        <DialogPrimitive.Overlay className="fixed inset-0 z-40 bg-black/40 backdrop-blur-sm" />
        <DialogPrimitive.Content className="fixed left-1/2 top-[15%] z-50 w-[calc(100vw-2rem)] max-w-xl -translate-x-1/2 overflow-hidden rounded-xl border border-border bg-surface shadow-2xl">
          <DialogPrimitive.Title className="sr-only">Command palette</DialogPrimitive.Title>
          <DialogPrimitive.Description className="sr-only">Search submissions or navigate</DialogPrimitive.Description>
          <Command shouldFilter={false} label="Command palette">
            <Command.Input value={q} onValueChange={setQ} placeholder="Search by insured or reference, or type a page…"
              className="w-full border-b border-border bg-transparent px-4 py-3 text-sm outline-none" />
            <Command.List className="max-h-80 overflow-auto p-2">
              <Command.Empty className="px-3 py-6 text-center text-sm text-subtle">No results</Command.Empty>
              {results.data?.items.length ? (
                <Command.Group heading="Submissions" className="text-xs text-subtle [&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:py-1">
                  {results.data.items.map((s) => (
                    <Command.Item key={s.id} value={s.id} onSelect={() => go(`/submissions/${s.id}`)}
                      className="flex cursor-pointer items-center gap-2 rounded-lg px-3 py-2 text-sm text-fg data-[selected=true]:bg-brand-soft">
                      <FileText className="h-4 w-4 text-subtle" aria-hidden />
                      <span className="font-mono text-xs text-subtle">{s.reference}</span> {s.insured_name}
                    </Command.Item>
                  ))}
                </Command.Group>
              ) : null}
              <Command.Group heading="Go to" className="text-xs text-subtle [&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:py-1">
                {NAV.filter((n) => (!n.roles || has(...n.roles)) && t(`nav.${n.key}`).toLowerCase().includes(q.toLowerCase())).map((n) => (
                  <Command.Item key={n.to} value={n.to} onSelect={() => go(n.to)}
                    className="flex cursor-pointer items-center gap-2 rounded-lg px-3 py-2 text-sm text-fg data-[selected=true]:bg-brand-soft">
                    <n.icon className="h-4 w-4 text-subtle" aria-hidden /> {t(`nav.${n.key}`)}
                  </Command.Item>
                ))}
              </Command.Group>
            </Command.List>
          </Command>
        </DialogPrimitive.Content>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  );
}

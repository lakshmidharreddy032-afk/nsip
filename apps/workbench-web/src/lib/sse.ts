import { useSession } from "@/stores/session";

export type ServerEvent = { event: string; data: Record<string, unknown> };

/** Parses a text/event-stream chunk buffer into events; returns the unconsumed remainder. */
export function parseSse(buffer: string): { events: ServerEvent[]; rest: string } {
  const events: ServerEvent[] = [];
  const blocks = buffer.split("\n\n");
  const rest = blocks.pop() ?? "";
  for (const block of blocks) {
    let event = "message";
    const data: string[] = [];
    for (const line of block.split("\n")) {
      if (line.startsWith(":")) continue;
      if (line.startsWith("event:")) event = line.slice(6).trim();
      else if (line.startsWith("data:")) data.push(line.slice(5).trim());
    }
    if (data.length) {
      try {
        events.push({ event, data: JSON.parse(data.join("\n")) });
      } catch {
        /* ignore malformed */
      }
    }
  }
  return { events, rest };
}

/** Fetch-based SSE so the bearer token goes in a header (EventSource cannot set headers). */
export function subscribe(onEvent: (e: ServerEvent) => void, signal: AbortSignal): void {
  const run = async (attempt: number) => {
    try {
      const token = useSession.getState().token;
      const res = await fetch("/api/v1/events", { headers: token ? { Authorization: `Bearer ${token}` } : {}, signal });
      if (!res.ok || !res.body) throw new Error(String(res.status));
      const reader = res.body.getReader();
      const dec = new TextDecoder();
      let buf = "";
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        const parsed = parseSse(buf + dec.decode(value, { stream: true }));
        buf = parsed.rest;
        parsed.events.forEach(onEvent);
      }
      if (!signal.aborted) setTimeout(() => run(0), 1000);
    } catch {
      if (!signal.aborted) setTimeout(() => run(attempt + 1), Math.min(30000, 1000 * 2 ** attempt));
    }
  };
  void run(0);
}

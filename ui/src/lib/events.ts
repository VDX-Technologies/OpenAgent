/** One shared Server-Sent Events connection for live updates (notifications, automations). */
import { API_BASE, type Note } from "#lib/api";

export type ServerEvent =
  | { type: "notification"; item: Note }
  | { type: "notifications_read" }
  | { type: "automations" };

type Handler = (e: ServerEvent) => void;
const handlers = new Set<Handler>();
let source: EventSource | null = null;

function connect() {
  if (source || typeof EventSource === "undefined") return;
  source = new EventSource(`${API_BASE}/api/events`);
  source.onmessage = (m) => {
    let e: ServerEvent;
    try { e = JSON.parse(m.data); } catch { return; }
    handlers.forEach((h) => { try { h(e); } catch { /* one bad listener mustn't stop the others */ } });
  };
  // EventSource reconnects on its own (the server sets retry: 3000)
}

/** Listen to server events; returns the unsubscribe function. */
export function onServerEvent(h: Handler): () => void {
  handlers.add(h);
  connect();
  return () => handlers.delete(h);
}

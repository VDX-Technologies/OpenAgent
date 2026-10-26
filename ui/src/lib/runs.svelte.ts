/** Chat runs that outlive the chat page: streams keep going while the user browses elsewhere. */
import { notifyConversations, streamChat, type Usage } from "#lib/api";

export type Run = { text: string; stream: string; tool: string | null; ctrl: AbortController };
export type RunEnd = { id: number | null; reply?: string; usage?: Usage; partial: string; error?: string };

/** Active runs keyed by conversation id (0 = a new chat whose id is not known yet). */
export const runs = $state<Record<number, Run>>({});

/** Start a turn; `onStart` gets the conversation id once the server has created it. */
export async function startRun(text: string, model: string, convId: number | null, onStart?: (id: number) => void) {
  const run: Run = { text, stream: "", tool: null, ctrl: new AbortController() };
  let key = convId ?? 0;
  runs[key] = run;
  const end: RunEnd = { id: convId, partial: "" };
  try {
    await streamChat(text, (e) => {
      const r = runs[key];
      if (e.type === "start" && e.conversation_id !== null && e.conversation_id !== key) {
        delete runs[key];
        key = e.conversation_id; end.id = key;
        runs[key] = r;
        notifyConversations();
        onStart?.(key);
      } else if (e.type === "token") { r.stream += e.text; r.tool = null; }
      else if (e.type === "tool") { r.stream = ""; r.tool = e.name; }
      else if (e.type === "error") throw new Error(e.detail);
      else if (e.type === "done") { end.reply = e.reply; end.usage = e.usage; }
    }, model, convId, run.ctrl.signal);
  } catch (err) {
    end.partial = runs[key]?.stream ?? "";
    if (!(err instanceof DOMException && err.name === "AbortError")) end.error = err instanceof Error ? err.message : "Request failed";
  } finally {
    delete runs[key];
    notifyConversations();
    window.dispatchEvent(new CustomEvent<RunEnd>("vdx:run-end", { detail: end }));
  }
}

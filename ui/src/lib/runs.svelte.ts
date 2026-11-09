/** Chat runs that outlive the chat page: streams keep going while the user browses elsewhere. */
import { notifyConversations, stopChat, streamChat, type Approval, type Attachments, type TurnOptions, type Usage } from "#lib/api";

/** One step of the agent: a tool call (with its result), or text the model wrote before calling tools. */
export type Step = { name?: string; args?: Record<string, unknown>; ok?: boolean; preview?: string; note?: string };

export type Run = {
  text: string;
  stream: string;
  thinking: string;
  tool: string | null;
  status: string;
  steps: Step[];
  approval: Approval | null;
  stopping: boolean;
  ctrl: AbortController;
};
export type RunEnd = { id: number | null; reply?: string; usage?: Usage; partial: string; error?: string; stopped?: boolean };

/** Active runs keyed by conversation id (0 = a new chat whose id is not known yet). */
export const runs = $state<Record<number, Run>>({});

/** Start a turn; `onStart` gets the conversation id once the server has created it. */
export async function startRun(
  text: string, model: string, convId: number | null, onStart?: (id: number) => void,
  attachments?: Attachments, opts?: TurnOptions,
): Promise<RunEnd> {
  const run: Run = {
    text, stream: "", thinking: "", tool: null, status: "", steps: [], approval: null, stopping: false,
    ctrl: new AbortController(),
  };
  let key = convId ?? 0;
  runs[key] = run;
  const end: RunEnd = { id: convId, partial: "" };

  // Tokens arrive far faster than the screen refreshes: buffer them and re-render the
  // markdown once per frame instead of once per token.
  let tokens = "", thoughts = "", frame = 0;
  const flush = () => {
    frame = 0;
    const r = runs[key];
    if (!r) return;
    if (tokens) { r.stream += tokens; tokens = ""; }
    if (thoughts) { r.thinking += thoughts; thoughts = ""; }
  };
  const later = () => { if (!frame) frame = requestAnimationFrame(flush); };

  try {
    await streamChat(text, (e) => {
      const r = runs[key];
      if (!r) return;
      if (e.type === "start" && e.conversation_id !== null && e.conversation_id !== key) {
        delete runs[key];
        key = e.conversation_id; end.id = key;
        runs[key] = r;
        notifyConversations();
        onStart?.(key);
      } else if (e.type === "status") r.status = e.text;
      else if (e.type === "token") { tokens += e.text; r.tool = null; r.status = ""; later(); }
      else if (e.type === "thinking") { thoughts += e.text; r.status = ""; later(); }
      else if (e.type === "tool_round") {
        flush();
        if (r.stream.trim()) r.steps.push({ note: r.stream.trim() });
        r.stream = "";
      } else if (e.type === "tool") { flush(); r.steps.push({ name: e.name, args: e.args }); r.tool = e.name; }
      else if (e.type === "tool_result") {
        const s = r.steps.findLast((x) => x.name === e.name && x.ok === undefined);
        if (s) { s.ok = e.ok; s.preview = e.preview; }
      } else if (e.type === "approval") r.approval = { id: e.id, name: e.name, label: e.label, args: e.args };
      else if (e.type === "approval_done") r.approval = null;
      else if (e.type === "error") throw new Error(e.detail);
      else if (e.type === "done") { end.reply = e.reply; end.usage = e.usage; end.stopped = e.stopped; }
    }, model, convId, run.ctrl.signal, attachments, opts);
  } catch (err) {
    flush();
    end.partial = runs[key]?.stream ?? "";
    if (!(err instanceof DOMException && err.name === "AbortError")) end.error = err instanceof Error ? err.message : "Request failed";
  } finally {
    if (frame) cancelAnimationFrame(frame);
    delete runs[key];
    notifyConversations();
    window.dispatchEvent(new CustomEvent<RunEnd>("vdx:run-end", { detail: end }));
  }
  return end;
}

/** Stop a run: the server ends the answer and keeps what was written so far. */
export async function stopRun(convId: number | null) {
  const r = runs[convId ?? 0];
  if (!r || r.stopping) return;
  r.stopping = true;
  try { await stopChat(convId); } catch { r.ctrl.abort(); }
}

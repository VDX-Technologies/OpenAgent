/**
 * Client for the VDX OpenAgent FastAPI backend (default :8741).
 */

// Dev (`pnpm dev` on :3000) talks to the API on :8741; the packaged app is
// served by the API itself, so production builds use same-origin requests.
const API_BASE: string =
  (import.meta.env.VITE_API_URL as string | undefined)?.replace(/\/$/, "") ??
  (import.meta.env.DEV ? "http://127.0.0.1:8741" : "");

export type AgentStatus = {
  ollama_online: boolean;
  model: string;
  base_url: string;
  temperature: number;
  short_term_messages: number;
  facts: number;
  gmail_configured: boolean;
  discord_configured: boolean;
};

export type ChatMessage = {
  role: "user" | "assistant";
  content: string;
  created_at?: string;
};

export type SettingsPayload = {
  ollama_base_url: string;
  ollama_model: string;
  ollama_temperature: number;
  ollama_timeout: number;
  gmail_address: string;
  gmail_app_password: string;
  discord_bot_token: string;
  discord_prefix: string;
  discord_allowed_users: string;
  whatsapp_token: string;
  whatsapp_phone_id: string;
  github_token: string;
  code_workspace: string;
};

export type Connector = {
  id: string;
  name: string;
  description: string;
  enabled: boolean;
  configured: boolean;
  setup_hint: string;
  tools: string[];
};

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers || {}),
    },
    cache: "no-store",
  });

  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail || JSON.stringify(body);
    } catch {
      /* ignore */
    }
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }

  return res.json() as Promise<T>;
}

export function getStatus() {
  return request<AgentStatus>("/api/status");
}

export function getModels() {
  return request<{ models: string[] }>("/api/models");
}

export function getHistory(limit = 50) {
  return request<{ messages: ChatMessage[] }>(`/api/history?limit=${limit}&source=web`);
}

export type Usage = {
  prompt_tokens: number;
  completion_tokens: number;
  duration_ms: number;
  tool_calls: number;
  llm_calls?: number;
  model?: string;
};

export function sendChat(message: string, model?: string, conversationId?: number | null) {
  return request<{ reply: string; conversation_id: number | null; usage: Usage }>("/api/chat", {
    method: "POST",
    body: JSON.stringify({ message, source: "web", model: model || null, conversation_id: conversationId ?? null }),
  });
}

export type StreamEvent =
  | { type: "start"; conversation_id: number | null }
  | { type: "token"; text: string }
  | { type: "tool"; name: string }
  | { type: "done"; reply: string; conversation_id: number | null; usage: Usage }
  | { type: "error"; detail: string };

/** Stream a chat turn (SSE): tokens as they are generated, tool calls, then the final reply. */
export async function streamChat(
  message: string,
  onEvent: (e: StreamEvent) => void,
  model?: string,
  conversationId?: number | null,
  signal?: AbortSignal,
) {
  const res = await fetch(`${API_BASE}/api/chat/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message, source: "web", model: model || null, conversation_id: conversationId ?? null }),
    signal,
  });
  if (!res.ok || !res.body) throw new Error(res.statusText || "Stream failed");
  const reader = res.body.pipeThrough(new TextDecoderStream()).getReader();
  let buf = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += value;
    let i;
    while ((i = buf.indexOf("\n\n")) >= 0) {
      const line = buf.slice(0, i).replace(/^data: /, "");
      buf = buf.slice(i + 2);
      if (line) onEvent(JSON.parse(line));
    }
  }
}

export type Conversation = {
  id: number;
  title: string;
  pinned: number;
  created_at: string;
  updated_at: string;
  message_count?: number;
};

export function listConversations(q = "") {
  return request<{ conversations: Conversation[] }>(`/api/conversations?q=${encodeURIComponent(q)}`);
}

export function getConversation(id: number) {
  return request<Conversation & { messages: ChatMessage[] }>(`/api/conversations/${id}`);
}

export function updateConversation(id: number, patch: { title?: string; pinned?: boolean }) {
  return request<Conversation>(`/api/conversations/${id}`, { method: "PATCH", body: JSON.stringify(patch) });
}

export function deleteConversation(id: number) {
  return request<{ status: string }>(`/api/conversations/${id}`, { method: "DELETE" });
}

/** Tell the sidebar to reload its conversation list. */
export function notifyConversations() {
  if (typeof window !== "undefined") window.dispatchEvent(new Event("vdx:conversations"));
}

type UsageAgg = Usage & { requests: number };

export type UsageReport = {
  days: number;
  totals: UsageAgg;
  by_model: (UsageAgg & { model: string })[];
  by_day: (UsageAgg & { day: string })[];
  recent: (Usage & { id: number; model: string; source: string; created_at: string; conversation_title: string | null })[];
  conversations: number;
};

export function getUsage(days = 30) {
  return request<UsageReport>(`/api/usage?days=${days}`);
}

export type SystemProfile = {
  os: string;
  machine: string;
  model: string;
  chip: string;
  apple_silicon: boolean;
  cpu_cores: number;
  perf_cores: number | null;
  efficiency_cores: number | null;
  ram_gb: number;
  disk_free_gb: number;
  disk_total_gb: number;
};

export type Recommendation = {
  name: string;
  size_gb: number;
  min_ram: number;
  tags: string[];
  desc: string;
  fit: "great" | "ok" | "too_big";
  installed: boolean;
  recommended: boolean;
};

export function getSystem() {
  return request<{ profile: SystemProfile; recommendations: Recommendation[] }>("/api/system");
}

export type InstalledModel = {
  name: string;
  size: number;
  modified_at: string;
  family: string;
  parameter_size: string;
  quantization: string;
};

export function getModelsDetailed() {
  return request<{ models: InstalledModel[]; running: { name: string; size_vram?: number; expires_at?: string }[] }>(
    "/api/models/detailed",
  );
}

export type PullState = { name: string; state: "pulling" | "done" | "error"; status: string; completed: number; total: number };

export function pullModel(name: string) {
  return request<PullState>("/api/models/pull", { method: "POST", body: JSON.stringify({ name }) });
}

export function getPulls() {
  return request<{ pulls: PullState[] }>("/api/models/pulls");
}

export function deleteModel(name: string) {
  return request<{ status: string }>(`/api/models/${name}`, { method: "DELETE" });
}

export function getConnectors() {
  return request<{ connectors: Connector[] }>("/api/connectors");
}

export function setConnector(id: string, enabled: boolean) {
  return request<{ connectors: Connector[] }>(`/api/connectors/${id}`, {
    method: "PUT",
    body: JSON.stringify({ enabled }),
  });
}

export function clearChat() {
  return request<{ status: string }>("/api/chat/clear", { method: "POST" });
}

export function getSettings() {
  return request<SettingsPayload>("/api/settings");
}

export function saveSettings(payload: SettingsPayload) {
  return request<{ status: string }>("/api/settings", {
    method: "PUT",
    body: JSON.stringify(payload),
  });
}

export { API_BASE };

// ── Automations ──────────────────────────────────────────────────────

export type AutomationKind = "interval" | "daily" | "once";

export interface Automation {
  id: number;
  name: string;
  prompt: string;
  kind: AutomationKind;
  every_minutes: number | null;
  time: string | null;
  weekdays: string | null;
  run_at: string | null;
  model: string | null;
  notify: boolean;
  enabled: boolean;
  conversation_id: number | null;
  last_run: string | null;
  last_status: string | null;
  last_result: string | null;
  next_run: string | null;
  runs: number;
}

export type AutomationInput = Partial<Omit<Automation, "id" | "conversation_id" | "last_run" | "last_status" | "last_result" | "next_run" | "runs">>;

export function getAutomations() {
  return request<{ automations: Automation[] }>("/api/automations");
}

export function createAutomation(body: AutomationInput) {
  return request<Automation>("/api/automations", { method: "POST", body: JSON.stringify(body) });
}

export function updateAutomation(id: number, body: AutomationInput) {
  return request<Automation>(`/api/automations/${id}`, { method: "PATCH", body: JSON.stringify(body) });
}

export function deleteAutomation(id: number) {
  return request<{ status: string }>(`/api/automations/${id}`, { method: "DELETE" });
}

export function runAutomation(id: number) {
  return request<Automation>(`/api/automations/${id}/run`, { method: "POST" });
}

export type TraceSpan =
  | { kind: "llm"; start: number; ms: number; load_ms: number; prompt_ms: number; eval_ms: number; prompt_tokens: number; completion_tokens: number }
  | { kind: "tool"; name: string; start: number; ms: number; ok: boolean };

export type Phases = { load_ms: number; prompt_ms: number; eval_ms: number; tool_ms: number; overhead_ms: number };

export type TraceRow = Phases & {
  id: number;
  model: string;
  source: string;
  total_ms: number;
  first_ms: number;
  prompt_tokens: number;
  completion_tokens: number;
  llm_calls: number;
  tool_calls: number;
  context_messages: number;
  tools: number;
  spans: TraceSpan[];
  created_at: string;
};

export type TelemetryReport = {
  days: number;
  summary: {
    requests: number; errors: number; p50_ms: number; p95_ms: number; first_p50_ms: number;
    decode_tps: number; prefill_tps: number; avg_llm_calls: number; avg_prompt_tokens: number; cold_loads: number;
  };
  phases: Phases;
  by_model: { model: string; requests: number; p50_ms: number; p95_ms: number; decode_tps: number; prefill_tps: number; cold_loads: number; avg_prompt_tokens: number }[];
  tools: { name: string; calls: number; errors: number; avg_ms: number; p95_ms: number }[];
  recent: TraceRow[];
  tips: { level: "high" | "medium" | "low" | "ok"; title: string; body: string }[];
  loaded: { name: string; size_vram: number; expires_at: string }[];
  default_model: string;
};

export function getTelemetry(days = 7) {
  return request<TelemetryReport>(`/api/telemetry?days=${days}`);
}

export function clearTelemetry() {
  return request<{ ok: boolean }>(`/api/telemetry`, { method: "DELETE" });
}

export type TelemetryConsent = {
  consent: boolean | null;
  configured: boolean;
  install_id: string;
  pending: number;
  preview?: Record<string, string | number>;
};

export function getTelemetryConsent() {
  return request<TelemetryConsent>(`/api/telemetry/consent`);
}

export function setTelemetryConsent(allow: boolean) {
  return request<TelemetryConsent>(`/api/telemetry/consent`, { method: "PUT", body: JSON.stringify({ allow }) });
}

export type Note = { id: number; title: string; text: string; conversation_id: number | null };

/** In-app notifications (automation results) newer than `after`. */
export const getNotifications = (after = 0) => request<{ items: Note[] }>(`/api/notifications?after=${after}`);

/** Shared formatting + client-side preference helpers. */

export const fmtNum = (v: number | undefined) => { const n = v ?? 0; return n >= 1e6 ? `${(n / 1e6).toFixed(1)}M` : n >= 1e3 ? `${(n / 1e3).toFixed(1)}k` : String(n); };

export function fmtBytes(b: number) {
  if (!b) return "—";
  const u = ["B", "KB", "MB", "GB", "TB"];
  const i = Math.min(u.length - 1, Math.floor(Math.log(b) / Math.log(1024)));
  return `${(b / 1024 ** i).toFixed(i >= 3 ? 1 : 0)} ${u[i]}`;
}

const MODEL_KEY = "vdx.model";
export function storedModel(): string {
  try { return localStorage.getItem(MODEL_KEY) ?? ""; } catch { return ""; }
}
export function storeModel(m: string) {
  try { localStorage.setItem(MODEL_KEY, m); } catch { /* private mode */ }
}

const COOKIE = "vdx_onboarded";
export const isOnboarded = () => document.cookie.split("; ").some((c) => c === `${COOKIE}=1`);
export function markOnboarded() {
  document.cookie = `${COOKIE}=1; max-age=${60 * 60 * 24 * 365 * 5}; path=/; SameSite=Lax`;
}
export function resetOnboarding() {
  document.cookie = `${COOKIE}=; max-age=0; path=/; SameSite=Lax`;
  location.reload();
}

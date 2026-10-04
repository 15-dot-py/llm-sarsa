export class ApiError extends Error {
  constructor(message: string, public status: number) { super(message); }
}
let sessionPromise: Promise<string> | null = null;
const KEY = 'shenmou-session-v1';
export async function session(): Promise<string> {
  const existing = localStorage.getItem(KEY);
  if (existing) return existing;
  if (!sessionPromise) sessionPromise = fetch('/api/session', { method: 'POST' }).then(async response => {
    if (!response.ok) throw new ApiError('服务连接失败，请确认后端已启动', response.status);
    const data = await response.json(); localStorage.setItem(KEY, data.session_id); return data.session_id;
  }).finally(() => { sessionPromise = null; });
  return sessionPromise;
}
export async function api<T>(path: string, options: RequestInit = {}, retry = true): Promise<T> {
  const sid = await session();
  const headers = new Headers(options.headers); headers.set('X-Session-Id', sid);
  if (options.body && !(options.body instanceof FormData)) headers.set('Content-Type', 'application/json');
  const response = await fetch(`/api${path}`, { ...options, headers });
  if (response.status === 401 && retry) { localStorage.removeItem(KEY); return api<T>(path, options, false); }
  if (!response.ok) {
    let message = `请求失败 (${response.status})`;
    try { const body = await response.json(); message = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail); } catch {}
    throw new ApiError(message, response.status);
  }
  return response.json();
}
export function post<T>(path: string, body: unknown = {}) { return api<T>(path, { method: 'POST', body: JSON.stringify(body) }); }
export async function downloadHistory() {
  const sid = await session(); const response = await fetch('/api/export/history.json', { headers: { 'X-Session-Id': sid } });
  if (!response.ok) throw new ApiError('导出失败', response.status);
  const url = URL.createObjectURL(await response.blob()); const a = document.createElement('a');
  a.href = url; a.download = '营销决策历史.json'; a.click(); URL.revokeObjectURL(url);
}

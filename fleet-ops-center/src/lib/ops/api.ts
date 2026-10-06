/**
 * 整備中心後端 API client（/api/ops、/api/auth、/api/demo）。
 * 與舊 frontend-admin 相同的呼叫介面，另加指揮中心用的 cases / stations / location。
 */
import type {
  Audience, AuthUser, CaseDetailResp, CaseListResp, Drafts, FleetResp, Health, Insights, MyTask, TaskAction,
  TaskPhoto, NotificationLogEntry, OpsEvent, Person, StationsResp, Summary, Task, TaskDetail, LocationResp,
} from "./types";

export class ApiError extends Error {
  status: number;
  constructor(s: number, m: string) {
    super(m);
    this.status = s;
  }
}

async function call<T>(path: string, init: RequestInit = {}): Promise<T> {
  const r = await fetch(path, {
    ...init,
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", ...(init.headers || {}) },
  });
  let body: unknown = null;
  try {
    body = await r.json();
  } catch {
    /* empty */
  }
  if (!r.ok) {
    if (r.status === 401 && !path.endsWith("/login")) window.dispatchEvent(new Event("ops:unauthorized"));
    const d = (body as { detail?: unknown } | null)?.detail;
    throw new ApiError(r.status, typeof d === "string" ? d : `HTTP ${r.status}`);
  }
  return body as T;
}

const q = (o: Record<string, string | number | boolean | undefined | null>) => {
  const s = Object.entries(o)
    .filter(([, v]) => v !== undefined && v !== null && v !== "")
    .map(([k, v]) => `${k}=${encodeURIComponent(String(v))}`)
    .join("&");
  return s ? `?${s}` : "";
};

export const api = {
  login: (username: string, password: string) => call<{ user: AuthUser }>("/api/auth/login", { method: "POST", body: JSON.stringify({ username, password }) }),
  logout: () => call<{ ok: boolean }>("/api/auth/logout", { method: "POST" }),
  me: () => call<{ user: AuthUser }>("/api/auth/me"),
  health: () => call<Health>("/api/ops/health"),
  summary: () => call<Summary>("/api/ops/summary"),
  tasks: (f: { status?: string; task_type?: string; priority?: string; assignee_id?: number; overdue?: boolean } = {}) =>
    call<{ tasks: Task[]; server_time: string; sla: Record<string, number> }>("/api/ops/tasks" + q(f)),
  task: (id: number) => call<TaskDetail>(`/api/ops/tasks/${id}`),
  patchTask: (id: number, body: { status?: string; action?: TaskAction; assignee_id?: number | null; note?: string; expected_assignee_id?: number | null }) =>
    call<TaskDetail>(`/api/ops/tasks/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  retryNotify: (id: number) => call<TaskDetail>(`/api/ops/tasks/${id}/notify`, { method: "POST" }),
  events: (f: { since?: number; priority?: string; unread?: boolean; types?: string; limit?: number } = {}) =>
    call<{ events: OpsEvent[]; unread: number; server_time: string }>("/api/ops/events" + q(f)),
  markRead: (ids: number[] | null) => call<{ ok: boolean; unread: number }>("/api/ops/events/read", { method: "POST", body: JSON.stringify({ ids }) }),
  people: (all = false) => call<{ people: Person[] }>("/api/ops/people" + q({ all })),
  addPerson: (group_name: string, name: string) => call<Person>("/api/ops/people", { method: "POST", body: JSON.stringify({ group_name, name }) }),
  patchPerson: (id: number, body: { group_name?: string; name?: string; active?: boolean }) =>
    call<Person>(`/api/ops/people/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  settings: () => call<{ settings: Record<string, string>; sla: Record<string, number> }>("/api/ops/settings"),
  putSettings: (v: Record<string, string | number>) =>
    call<{ settings: Record<string, string>; sla: Record<string, number> }>("/api/ops/settings", { method: "PUT", body: JSON.stringify(v) }),
  caseDrafts: (caseId: string) => call<{ case_id: string; drafts: Drafts }>(`/api/ops/cases/${encodeURIComponent(caseId)}/drafts`),
  generateDrafts: (caseId: string, force = false) =>
    call<{ case_id: string; drafts: Drafts; cached: boolean }>(`/api/ops/cases/${encodeURIComponent(caseId)}/drafts` + q({ force }), { method: "POST" }),
  putDraft: (caseId: string, audience: Audience, content: Record<string, unknown>) =>
    call<Drafts[Audience]>(`/api/ops/cases/${encodeURIComponent(caseId)}/drafts/${audience}`, { method: "PUT", body: JSON.stringify({ content }) }),
  sendDraft: (taskId: number, audience: Audience, channel: string) =>
    call<TaskDetail & { ok: boolean; entry: NotificationLogEntry }>(`/api/ops/tasks/${taskId}/send`, { method: "POST", body: JSON.stringify({ audience, channel }) }),
  testWebhook: () => call<{ ok: boolean; status: string; detail: string }>("/api/ops/settings/test", { method: "POST" }),
  fleet: (f: { q?: string; status?: string } = {}) => call<FleetResp>("/api/ops/fleet" + q(f)),
  lockCar: (car: string, locked: boolean, reason?: string) =>
    call<FleetResp & { lock: unknown }>(`/api/ops/fleet/${encodeURIComponent(car)}`, { method: "PATCH", body: JSON.stringify({ locked, reason }) }),
  setLocation: (car: string, station_id: string | null) =>
    call<LocationResp>(`/api/ops/fleet/${encodeURIComponent(car)}/location`, { method: "PATCH", body: JSON.stringify({ station_id }) }),
  stations: () => call<StationsResp>("/api/ops/stations"),
  cases: (f: { car?: string; status?: string; levels?: string } = {}) => call<CaseListResp>("/api/ops/cases" + q(f)),
  caseDetail: (caseId: string) => call<CaseDetailResp>(`/api/ops/cases/${encodeURIComponent(caseId)}`),
  decideCase: (caseId: string, decision: "confirm" | "reject" | "retake", note?: string) =>
    call<{ ok: boolean; task: Task | null; case: CaseListResp["cases"][number] }>(`/api/ops/cases/${encodeURIComponent(caseId)}/decision`, { method: "POST", body: JSON.stringify({ decision, note }) }),
  undoCase: (caseId: string) => call<{ ok: boolean; case: CaseListResp["cases"][number] }>(`/api/ops/cases/${encodeURIComponent(caseId)}/decision`, { method: "DELETE" }),
  insights: () => call<Insights>("/api/ops/insights"),
  baseline: (car: string) => call<{ car: string; photos: TaskPhoto[] }>(`/api/ops/cars/${encodeURIComponent(car)}/baseline`),
  myTasks: () => call<{ tasks: MyTask[]; reader: string; server_time: string }>("/api/ops/my-tasks"),
  uploadPhoto: async (taskId: number, file: File) => {
    const fd = new FormData();
    fd.append("photo", file);
    const r = await fetch(`/api/ops/tasks/${taskId}/photos`, { method: "POST", body: fd, credentials: "same-origin" });
    const j = await r.json().catch(() => null);
    if (!r.ok) throw new ApiError(r.status, (j as { detail?: string } | null)?.detail || `HTTP ${r.status}`);
    return j as { ok: boolean; photo: TaskPhoto; photos: TaskPhoto[]; task: Task };
  },
  demoHealth: () => call<Record<string, unknown>>("/api/demo/health"),
  demoReset: () => call<Record<string, unknown>>("/api/demo/reset", { method: "POST" }),
};

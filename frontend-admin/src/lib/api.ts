import type { Audience, Drafts, FleetResp, Health, Insights, MyTask, TaskPhoto, NotificationLogEntry, OpsEvent, Person, Summary, Task, TaskDetail } from './types'
import { getReader } from './reader'

export class ApiError extends Error { status: number; constructor(s: number, m: string) { super(m); this.status = s } }

async function call<T>(path: string, init: RequestInit = {}): Promise<T> {
  const r = await fetch(path, {
    ...init,
    headers: { 'Content-Type': 'application/json', 'X-Ops-Reader': encodeURIComponent(getReader() || 'anonymous'), ...(init.headers || {}) },
  })
  let body: unknown = null
  try { body = await r.json() } catch { /* empty */ }
  if (!r.ok) {
    const d = (body as { detail?: unknown } | null)?.detail
    throw new ApiError(r.status, typeof d === 'string' ? d : `HTTP ${r.status}`)
  }
  return body as T
}

const q = (o: Record<string, string | number | boolean | undefined | null>) => {
  const s = Object.entries(o).filter(([, v]) => v !== undefined && v !== null && v !== '')
    .map(([k, v]) => `${k}=${encodeURIComponent(String(v))}`).join('&')
  return s ? `?${s}` : ''
}

export const api = {
  health: () => call<Health>('/api/ops/health'),
  summary: () => call<Summary>('/api/ops/summary'),
  tasks: (f: { status?: string; task_type?: string; priority?: string; assignee?: string; overdue?: boolean } = {}) =>
    call<{ tasks: Task[]; server_time: string; sla: Record<string, number> }>('/api/ops/tasks' + q(f)),
  task: (id: number) => call<TaskDetail>(`/api/ops/tasks/${id}`),
  patchTask: (id: number, body: { status?: string; assignee?: string; note?: string }) =>
    call<TaskDetail>(`/api/ops/tasks/${id}`, { method: 'PATCH', body: JSON.stringify(body) }),
  retryNotify: (id: number) => call<TaskDetail>(`/api/ops/tasks/${id}/notify`, { method: 'POST' }),
  events: (f: { since?: number; priority?: string; unread?: boolean; types?: string; limit?: number } = {}) =>
    call<{ events: OpsEvent[]; unread: number; server_time: string }>('/api/ops/events' + q(f)),
  markRead: (ids: number[] | null) =>
    call<{ ok: boolean; unread: number }>('/api/ops/events/read', { method: 'POST', body: JSON.stringify({ ids }) }),
  people: (all = false) => call<{ people: Person[] }>('/api/ops/people' + q({ all })),
  addPerson: (group_name: string, name: string) =>
    call<Person>('/api/ops/people', { method: 'POST', body: JSON.stringify({ group_name, name }) }),
  patchPerson: (id: number, body: { group_name?: string; name?: string; active?: boolean }) =>
    call<Person>(`/api/ops/people/${id}`, { method: 'PATCH', body: JSON.stringify(body) }),
  settings: () => call<{ settings: Record<string, string>; sla: Record<string, number> }>('/api/ops/settings'),
  putSettings: (v: Record<string, string | number>) =>
    call<{ settings: Record<string, string>; sla: Record<string, number> }>('/api/ops/settings', { method: 'PUT', body: JSON.stringify(v) }),
  caseDrafts: (caseId: string) => call<{ case_id: string; drafts: Drafts }>(`/api/ops/cases/${encodeURIComponent(caseId)}/drafts`),
  generateDrafts: (caseId: string, force = false) =>
    call<{ case_id: string; drafts: Drafts; cached: boolean }>(`/api/ops/cases/${encodeURIComponent(caseId)}/drafts` + q({ force }), { method: 'POST' }),
  putDraft: (caseId: string, audience: Audience, content: Record<string, unknown>) =>
    call<Drafts[Audience]>(`/api/ops/cases/${encodeURIComponent(caseId)}/drafts/${audience}`, { method: 'PUT', body: JSON.stringify({ content }) }),
  sendDraft: (taskId: number, audience: Audience, channel: string) =>
    call<TaskDetail & { ok: boolean; entry: NotificationLogEntry }>(`/api/ops/tasks/${taskId}/send`, { method: 'POST', body: JSON.stringify({ audience, channel }) }),
  testWebhook: () => call<{ ok: boolean; status: string; detail: string }>('/api/ops/settings/test', { method: 'POST' }),
  fleet: (f: { q?: string; status?: string } = {}) => call<FleetResp>('/api/ops/fleet' + q(f)),
  lockCar: (car: string, locked: boolean, reason?: string) =>
    call<FleetResp & { lock: unknown }>(`/api/ops/fleet/${encodeURIComponent(car)}`, { method: 'PATCH', body: JSON.stringify({ locked, reason }) }),
  insights: () => call<Insights>('/api/ops/insights'),
  myTasks: () => call<{ tasks: MyTask[]; reader: string; server_time: string }>('/api/ops/my-tasks'),
  uploadPhoto: async (taskId: number, file: File) => {
    const fd = new FormData(); fd.append('photo', file)
    const r = await fetch(`/api/ops/tasks/${taskId}/photos`, { method: 'POST', body: fd, headers: { 'X-Ops-Reader': encodeURIComponent(getReader() || 'anonymous') } })
    const j = await r.json().catch(() => null)
    if (!r.ok) throw new ApiError(r.status, (j as { detail?: string } | null)?.detail || `HTTP ${r.status}`)
    return j as { ok: boolean; photo: TaskPhoto; photos: TaskPhoto[] }
  },
  demoHealth: () => call<Record<string, unknown>>('/api/demo/health'),
  demoReset: () => call<Record<string, unknown>>('/api/demo/reset', { method: 'POST' }),
}

import type { Health, OpsEvent, Person, Summary, Task, TaskDetail } from './types'
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
  demoHealth: () => call<Record<string, unknown>>('/api/demo/health'),
  demoReset: () => call<Record<string, unknown>>('/api/demo/reset', { method: 'POST' }),
}

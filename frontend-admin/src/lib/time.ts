// 時間工具。server_time 與瀏覽器時間差以 offset 校正（SLA 倒數不受本機時鐘影響）。
let offsetMs = 0
export function syncClock(serverIso: string | undefined) {
  if (!serverIso) return
  const s = Date.parse(serverIso)
  if (!Number.isNaN(s)) offsetMs = s - Date.now()
}
export const now = () => Date.now() + offsetMs

export function fmt(iso: string | null | undefined): string {
  if (!iso) return '—'
  return iso.replace('T', ' ').slice(0, 16)
}
export function rel(iso: string | null | undefined): string {
  if (!iso) return ''
  const d = (now() - Date.parse(iso)) / 1000
  if (d < 45) return '剛剛'
  if (d < 3600) return `${Math.round(d / 60)} 分鐘前`
  if (d < 86400) return `${Math.round(d / 3600)} 小時前`
  return `${Math.round(d / 86400)} 天前`
}
export function dur(sec: number): string {
  const s = Math.abs(Math.round(sec))
  if (s < 60) return `${s} 秒`
  if (s < 3600) return `${Math.floor(s / 60)} 分`
  if (s < 86400) return `${Math.floor(s / 3600)} 時 ${Math.floor((s % 3600) / 60)} 分`
  return `${Math.floor(s / 86400)} 天`
}
/** SLA 分級由 Backend 決定；前端只以 due_at 計算持續更新的顯示文字。 */
export function slaState(t: { sla_due_at: string; sla_status: 'normal' | 'approaching' | 'overdue' | 'inactive' }) {
  if (t.sla_status === 'inactive') return { kind: 'none' as const, label: '' }
  const remain = (Date.parse(t.sla_due_at) - now()) / 1000
  if (t.sla_status === 'overdue') return { kind: 'over' as const, label: `逾時 ${dur(remain)}` }
  if (t.sla_status === 'approaching') return { kind: 'soon' as const, label: `剩 ${dur(remain)}` }
  return { kind: 'ok' as const, label: `剩 ${dur(remain)}` }
}

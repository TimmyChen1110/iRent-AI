// 無登入前提下的「我是誰」：前端自選身分，只用於事件已讀與歷程署名（介面標明未驗證）。
const KEY = 'ops.reader'
export function getReader(): string {
  try { return localStorage.getItem(KEY) || '' } catch { return '' }
}
export function setReader(v: string) {
  try { localStorage.setItem(KEY, v) } catch { /* ignore */ }
}
export function initials(name: string | null | undefined): string {
  if (!name) return '—'
  const m = name.match(/[A-Za-z0-9]+$/)
  return m ? m[0].slice(0, 2).toUpperCase() : name.slice(-1)
}

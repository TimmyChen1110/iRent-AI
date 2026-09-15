export function initials(name: string | null | undefined): string {
  if (!name) return '—'
  const match = name.match(/[A-Za-z0-9]+$/)
  return match ? match[0].slice(0, 2).toUpperCase() : name.slice(-1)
}

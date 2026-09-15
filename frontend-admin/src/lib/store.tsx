import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react'
import { api } from './api'
import type { Health, Person, Summary } from './types'
import { syncClock } from './time'
import type { OpsEvent } from './types'
import { StoreContext, type Store } from './store-context'

/** 全站共享狀態：健檢、摘要（側欄計數）、人員名單、連線狀態、身分。5 秒輪詢。 */
export const POLL_MS = 5000

export function StoreProvider({ children, station = false }: { children: ReactNode; station?: boolean }) {
  const [health, setHealth] = useState<Health | null>(null)
  const [summary, setSummary] = useState<Summary | null>(null)
  const [people, setPeople] = useState<Person[]>([])
  const [conn, setConn] = useState<Store['conn']>('polling')
  const [tick, setTick] = useState(0)
  const [lastEvent, setLastEvent] = useState<OpsEvent | null>(null)
  const fails = useRef(0)
  const live = useRef(false)

  const refresh = useCallback(async () => {
    try {
      if (station) { setConn('polling'); setTick(x => x + 1); return }
      const [s, p] = await Promise.all([api.summary(), api.people()])
      syncClock(s.server_time)
      setSummary(s); setPeople(p.people); fails.current = 0; setConn(live.current ? 'live' : 'polling')
      setTick(x => x + 1)
    } catch {
      fails.current += 1
      if (fails.current >= 2) setConn('offline')
    }
  }, [station])

  useEffect(() => {
    api.health().then(h => { setHealth(h); syncClock(h.server_time) }).catch(() => setConn('offline'))
    const first = setTimeout(refresh, 0)
    const id = setInterval(refresh, POLL_MS)
    return () => { clearTimeout(first); clearInterval(id) }
  }, [refresh])

  // SSE：新事件即時到；斷線時退回輪詢並每 10 秒重連（輪詢本來就一直在跑）
  useEffect(() => {
    let es: EventSource | null = null
    let retry: ReturnType<typeof setTimeout> | null = null
    let closed = false
    const connect = () => {
      if (station) return
      if (closed) return
      es = new EventSource('/api/ops/events/stream')
      es.addEventListener('hello', () => { live.current = true; setConn('live') })
      es.addEventListener('ops', (m) => {
        try { setLastEvent(JSON.parse((m as MessageEvent).data)) } catch { /* ignore */ }
        refresh()
      })
      es.onerror = () => {
        live.current = false; setConn('polling')
        es?.close(); es = null
        retry = setTimeout(connect, 10000)
      }
    }
    connect()
    return () => { closed = true; live.current = false; es?.close(); if (retry) clearTimeout(retry) }
  }, [refresh, station])

  return <StoreContext.Provider value={{ health, summary, people, conn, refresh, tick, lastEvent }}>{children}</StoreContext.Provider>
}

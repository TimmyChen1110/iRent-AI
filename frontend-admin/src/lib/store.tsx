import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from 'react'
import { api } from './api'
import type { Health, Person, Summary } from './types'
import { getReader, setReader as persistReader } from './reader'
import { syncClock } from './time'
import type { OpsEvent } from './types'

/** 全站共享狀態：健檢、摘要（側欄計數）、人員名單、連線狀態、身分。5 秒輪詢。 */
interface Store {
  health: Health | null
  summary: Summary | null
  people: Person[]
  conn: 'live' | 'polling' | 'offline'
  reader: string
  setReader: (v: string) => void
  refresh: () => Promise<void>
  tick: number   // 每次輪詢／SSE 事件 +1，頁面可據此重抓
  lastEvent: OpsEvent | null   // SSE 最新事件（頁面可用來提示）
}
const Ctx = createContext<Store>(null as unknown as Store)
export const useStore = () => useContext(Ctx)

export const POLL_MS = 5000

export function StoreProvider({ children }: { children: ReactNode }) {
  const [health, setHealth] = useState<Health | null>(null)
  const [summary, setSummary] = useState<Summary | null>(null)
  const [people, setPeople] = useState<Person[]>([])
  const [conn, setConn] = useState<Store['conn']>('polling')
  const [reader, setReaderState] = useState(getReader())
  const [tick, setTick] = useState(0)
  const [lastEvent, setLastEvent] = useState<OpsEvent | null>(null)
  const fails = useRef(0)
  const live = useRef(false)

  const refresh = useCallback(async () => {
    try {
      const [s, p] = await Promise.all([api.summary(), api.people()])
      syncClock(s.server_time)
      setSummary(s); setPeople(p.people); fails.current = 0; setConn(live.current ? 'live' : 'polling')
      setTick(x => x + 1)
    } catch {
      fails.current += 1
      if (fails.current >= 2) setConn('offline')
    }
  }, [])

  useEffect(() => {
    api.health().then(h => { setHealth(h); syncClock(h.server_time) }).catch(() => setConn('offline'))
    refresh()
    const id = setInterval(refresh, POLL_MS)
    return () => clearInterval(id)
  }, [refresh])

  // SSE：新事件即時到；斷線時退回輪詢並每 10 秒重連（輪詢本來就一直在跑）
  useEffect(() => {
    let es: EventSource | null = null
    let retry: ReturnType<typeof setTimeout> | null = null
    let closed = false
    const connect = () => {
      if (closed) return
      es = new EventSource(`/api/ops/events/stream?reader=${encodeURIComponent(reader || 'anonymous')}`)
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
  }, [reader, refresh])

  const setReader = (v: string) => { persistReader(v); setReaderState(v); refresh() }
  return <Ctx.Provider value={{ health, summary, people, conn, reader, setReader, refresh, tick, lastEvent }}>{children}</Ctx.Provider>
}

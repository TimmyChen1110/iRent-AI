import { createContext, useContext } from 'react'
import type { Health, OpsEvent, Person, Summary } from './types'

export interface Store {
  health: Health | null
  summary: Summary | null
  people: Person[]
  conn: 'live' | 'polling' | 'offline'
  refresh: () => Promise<void>
  tick: number
  lastEvent: OpsEvent | null
}

export const StoreContext = createContext<Store>(null as unknown as Store)
export const useStore = () => useContext(StoreContext)

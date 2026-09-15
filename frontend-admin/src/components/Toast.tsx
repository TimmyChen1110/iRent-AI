import { useCallback, useState, type ReactNode } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import { ToastContext } from './toast-context'

type Toast = { id: number; text: string; kind?: 'ok' | 'warn' }
export function ToastProvider({ children }: { children: ReactNode }) {
  const [list, setList] = useState<Toast[]>([])
  const push = useCallback((text: string, kind?: 'ok' | 'warn') => {
    const id = Date.now() + Math.random()
    setList(l => [...l, { id, text, kind }])
    setTimeout(() => setList(l => l.filter(t => t.id !== id)), 3200)
  }, [])
  return (
    <ToastContext.Provider value={push}>
      {children}
      <div className="toasts" aria-live="polite">
        <AnimatePresence>
          {list.map(t => (
            <motion.div key={t.id} className={`toast ${t.kind || ''}`}
              initial={{ opacity: 0, y: 16, scale: .96 }} animate={{ opacity: 1, y: 0, scale: 1 }} exit={{ opacity: 0, y: 8 }}
              transition={{ type: 'spring', stiffness: 420, damping: 30 }}>{t.text}</motion.div>
          ))}
        </AnimatePresence>
      </div>
    </ToastContext.Provider>
  )
}

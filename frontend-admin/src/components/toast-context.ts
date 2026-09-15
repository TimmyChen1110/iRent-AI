import { createContext, useContext } from 'react'

export const ToastContext = createContext<(text: string, kind?: 'ok' | 'warn') => void>(() => {})
export const useToast = () => useContext(ToastContext)

import type { TaskStatus } from './types'

export const STATUS_TXT: Record<TaskStatus, string> = { pending: '待處理', in_progress: '處理中', completed: '已完成', cancelled: '已取消' }
export const zhStatus = (s: string) => s.replace(/pending/g, '待處理').replace(/in_progress/g, '處理中').replace(/completed/g, '已完成').replace(/cancelled/g, '已取消')

import type { EventType, NotifyStatus, TaskStatus, TaskType } from './types'

export const STATUS_TXT: Record<TaskStatus, string> = { pending: '待處理', in_progress: '處理中', completed: '已完成', cancelled: '已取消' }
export const TYPE_TXT: Record<TaskType, string> = { repair: '維修', cleaning: '清潔' }
export const NOTIFY_TXT: Record<NotifyStatus, string> = { not_sent: '通知未發送', sent: '通知已送出', failed: '通知失敗', skipped: '通知管道未設定' }
export const EVENT_TXT: Record<EventType, string> = {
  task_created: '新任務', task_status: '狀態變更', task_assigned: '指派', notify_sent: '通知已送出',
  notify_failed: '通知失敗', notify_skipped: '通知未設定', sla_overdue: 'SLA 逾時', note: '備註',
}
export const zhStatus = (s: string) => s.replace(/pending/g, '待處理').replace(/in_progress/g, '處理中').replace(/completed/g, '已完成').replace(/cancelled/g, '已取消')

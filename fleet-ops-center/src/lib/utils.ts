import type { Priority, Severity, VehicleStatus } from "@/types";

export function cn(...classes: Array<string | false | null | undefined>) {
  return classes.filter(Boolean).join(" ");
}

export function pct(value: number) {
  return `${Math.round(value * 100)}%`;
}

export function formatNumber(value: number) {
  return new Intl.NumberFormat("en-US").format(value);
}

export const statusMeta: Record<
  VehicleStatus,
  { label: string; dot: string; text: string; bg: string; ring: string }
> = {
  healthy: {
    label: "正常",
    dot: "bg-emerald-400",
    text: "text-emerald-300",
    bg: "bg-emerald-400/10",
    ring: "ring-emerald-400/20",
  },
  damage: {
    label: "車損警示",
    dot: "bg-rose-400",
    text: "text-rose-300",
    bg: "bg-rose-400/10",
    ring: "ring-rose-400/25",
  },
  cleaning: {
    label: "待清潔",
    dot: "bg-amber-400",
    text: "text-amber-300",
    bg: "bg-amber-400/10",
    ring: "ring-amber-400/20",
  },
  maintenance: {
    label: "維修中",
    dot: "bg-sky-400",
    text: "text-sky-300",
    bg: "bg-sky-400/10",
    ring: "ring-sky-400/20",
  },
  "pending-review": {
    label: "待人工審核",
    dot: "bg-violet-400",
    text: "text-violet-300",
    bg: "bg-violet-400/10",
    ring: "ring-violet-400/20",
  },
  ready: {
    label: "整備完成",
    dot: "bg-teal-300",
    text: "text-teal-200",
    bg: "bg-teal-400/10",
    ring: "ring-teal-400/20",
  },
  unavailable: {
    label: "暫停營運",
    dot: "bg-zinc-400",
    text: "text-zinc-300",
    bg: "bg-zinc-400/10",
    ring: "ring-zinc-400/20",
  },
};

export const severityMeta: Record<Severity, { label: string; text: string; bg: string }> = {
  low: { label: "輕微", text: "text-emerald-300", bg: "bg-emerald-400/10" },
  medium: { label: "中度", text: "text-amber-300", bg: "bg-amber-400/10" },
  high: { label: "嚴重", text: "text-rose-300", bg: "bg-rose-400/10" },
};

export const priorityMeta: Record<Priority, { label: string; text: string; bg: string; dot: string }> = {
  low: { label: "低", text: "text-emerald-300", bg: "bg-emerald-400/10", dot: "bg-emerald-400" },
  medium: { label: "中", text: "text-amber-300", bg: "bg-amber-400/10", dot: "bg-amber-400" },
  high: { label: "高", text: "text-rose-300", bg: "bg-rose-400/10", dot: "bg-rose-400" },
};

export function nowTime() {
  const d = new Date();
  return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

let counter = 100;
export function nextId(prefix: string) {
  counter += 1;
  return `${prefix}-${counter}`;
}

/** Adds minutes to an "HH:MM" string (demo-deterministic timeline stamps). */
export function addMinutes(hhmm: string, minutes: number) {
  const [h, m] = hhmm.split(":").map(Number);
  const total = (h * 60 + m + minutes + 24 * 60) % (24 * 60);
  return `${String(Math.floor(total / 60)).padStart(2, "0")}:${String(total % 60).padStart(2, "0")}`;
}

export const cleanlinessLabel: Record<"Clean" | "Acceptable" | "Dirty", string> = { Clean: "乾淨", Acceptable: "尚可", Dirty: "髒污" };
export const batteryLabel: Record<"Healthy" | "Low" | "Charging", string> = { Healthy: "正常", Low: "偏低", Charging: "充電中" };
export const taskStatusLabel: Record<"assigned" | "in-progress" | "scheduled" | "completed", string> = {
  assigned: "已指派",
  "in-progress": "處理中",
  scheduled: "已排程",
  completed: "已完成",
};
export const taskTypeLabel: Record<"inspection" | "cleaning" | "maintenance", string> = { inspection: "維修檢查", cleaning: "清潔", maintenance: "維修" };

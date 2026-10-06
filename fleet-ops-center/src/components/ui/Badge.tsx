import { cn, priorityMeta, severityMeta, statusMeta } from "@/lib/utils";
import type { Priority, Severity, VehicleStatus } from "@/types";

export function Badge({
  children,
  className,
  tone = "neutral",
}: {
  children: React.ReactNode;
  className?: string;
  tone?: "neutral" | "danger" | "warning" | "success" | "info" | "violet";
}) {
  const tones = {
    neutral: "bg-white/[0.06] text-white/70",
    danger: "bg-rose-400/10 text-rose-300",
    warning: "bg-amber-400/10 text-amber-300",
    success: "bg-emerald-400/10 text-emerald-300",
    info: "bg-sky-400/10 text-sky-300",
    violet: "bg-violet-400/10 text-violet-300",
  };
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-md px-2 py-0.5 text-[11px] font-medium whitespace-nowrap",
        tones[tone],
        className,
      )}
    >
      {children}
    </span>
  );
}

export function StatusPill({ status, className, pulse }: { status: VehicleStatus; className?: string; pulse?: boolean }) {
  const m = statusMeta[status];
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[11px] font-medium ring-1 whitespace-nowrap",
        m.bg,
        m.text,
        m.ring,
        className,
      )}
    >
      <span className={cn("h-1.5 w-1.5 rounded-full", m.dot, pulse && "soft-pulse")} />
      {m.label}
    </span>
  );
}

export function SeverityBadge({ severity }: { severity: Severity }) {
  const m = severityMeta[severity];
  return <span className={cn("rounded-md px-2 py-0.5 text-[11px] font-medium", m.bg, m.text)}>{m.label}</span>;
}

export function PriorityBadge({ priority, className }: { priority: Priority; className?: string }) {
  const m = priorityMeta[priority];
  return (
    <span className={cn("inline-flex items-center gap-1.5 rounded-md px-2 py-0.5 text-[11px] font-medium", m.bg, m.text, className)}>
      <span className={cn("h-1.5 w-1.5 rounded-full", m.dot)} />
      {m.label}
    </span>
  );
}

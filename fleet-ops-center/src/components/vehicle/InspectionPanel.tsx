"use client";

import { motion } from "framer-motion";
import { Car, Armchair, AlertTriangle, CheckCircle2, Sparkles } from "lucide-react";
import type { Vehicle } from "@/types";
import { GlassPanel, SectionHeader } from "@/components/ui/GlassPanel";
import { ConfidenceBar } from "@/components/ui/ConfidenceBar";
import { SeverityBadge, Badge } from "@/components/ui/Badge";
import { cn, cleanlinessLabel } from "@/lib/utils";

export function InspectionPanel({
  vehicle,
  activeKind,
  onFocus,
  className,
}: {
  vehicle: Vehicle;
  activeKind?: "damage" | "cleaning" | null;
  onFocus?: (kind: "damage" | "cleaning") => void;
  className?: string;
}) {
  const ext = vehicle.exterior;
  const int = vehicle.interior;
  return (
    <GlassPanel className={className}>
      <SectionHeader
        title="AI 檢測結果"
        subtitle="還車照片分析 · iRent Vision v2.4"
        action={
          <Badge tone="info">
            <Sparkles className="h-3 w-3" /> {vehicle.lastInspection}
          </Badge>
        }
      />
      <div className="grid gap-4 md:grid-cols-2">
        <Section
          icon={<Car className="h-4 w-4" />}
          title="車外檢測"
          flagged={ext.flagged}
          active={activeKind === "damage"}
          onClick={ext.flagged && onFocus ? () => onFocus("damage") : undefined}
        >
          <KV label="AI 判定" value={ext.result} tone={ext.flagged ? "warn" : "ok"} />
          {ext.location && <KV label="位置" value={ext.location} />}
          {ext.type && <KV label="類型" value={ext.type} />}
          <div className="mt-3">
            <ConfidenceBar value={ext.confidence} tone={ext.flagged ? undefined : "success"} />
          </div>
          {ext.severity && (
            <div className="mt-3 flex items-center justify-between">
              <span className="label-xs">嚴重程度</span>
              <SeverityBadge severity={ext.severity} />
            </div>
          )}
        </Section>

        <Section
          icon={<Armchair className="h-4 w-4" />}
          title="車內檢測"
          flagged={int.flagged}
          active={activeKind === "cleaning"}
          onClick={int.flagged && onFocus ? () => onFocus("cleaning") : undefined}
        >
          <KV label="整潔程度" value={cleanlinessLabel[int.cleanliness]} tone={int.flagged ? "warn" : "ok"} />
          <div className="mt-3">
            <ConfidenceBar value={int.confidence} tone={int.flagged ? "warning" : "success"} />
          </div>
          {int.detected.length > 0 && (
            <div className="mt-3">
              <div className="label-xs mb-1.5">偵測項目</div>
              <div className="flex flex-wrap gap-1.5">
                {int.detected.map((d) => (
                  <Badge key={d} tone="warning">
                    {d}
                  </Badge>
                ))}
              </div>
            </div>
          )}
          <div className="mt-3 flex items-start justify-between gap-3">
            <span className="label-xs shrink-0">建議</span>
            <span className={cn("text-right text-[12.5px] font-medium", int.flagged ? "text-amber-200" : "text-emerald-300")}>{int.recommendation}</span>
          </div>
        </Section>
      </div>
    </GlassPanel>
  );
}

function Section({
  icon,
  title,
  flagged,
  active,
  onClick,
  children,
}: {
  icon: React.ReactNode;
  title: string;
  flagged: boolean;
  active?: boolean;
  onClick?: () => void;
  children: React.ReactNode;
}) {
  return (
    <motion.div
      whileHover={onClick ? { y: -1 } : undefined}
      onClick={onClick}
      className={cn(
        "rounded-xl border bg-white/[0.02] p-4 transition-colors",
        active ? "border-white/20 bg-white/[0.04]" : "border-white/[0.06]",
        onClick && "cursor-pointer hover:border-white/15",
      )}
    >
      <div className="mb-3 flex items-center justify-between">
        <div className="flex items-center gap-2 text-[13px] font-semibold text-white/90">
          <span className="text-white/50">{icon}</span>
          {title}
        </div>
        {flagged ? (
          <span className="flex items-center gap-1 text-[11px] font-medium text-amber-300">
            <AlertTriangle className="h-3 w-3" /> 已標記
          </span>
        ) : (
          <span className="flex items-center gap-1 text-[11px] font-medium text-emerald-300">
            <CheckCircle2 className="h-3 w-3" /> 通過
          </span>
        )}
      </div>
      {children}
    </motion.div>
  );
}

function KV({ label, value, tone }: { label: string; value: string; tone?: "ok" | "warn" }) {
  return (
    <div className="flex items-center justify-between py-1 text-[13px]">
      <span className="label-xs">{label}</span>
      <span className={cn("font-medium", tone === "warn" ? "text-amber-200" : tone === "ok" ? "text-emerald-300" : "text-white/90")}>{value}</span>
    </div>
  );
}

"use client";

import { motion } from "framer-motion";
import { X, Image as ImageIcon } from "lucide-react";
import type { DamageHotspot, Vehicle } from "@/types";
import { Button } from "@/components/ui/Button";
import { cn, pct, severityMeta, cleanlinessLabel } from "@/lib/utils";

/**
 * Floating annotation shown next to the 3D twin for the selected hotspot.
 * Exterior: damage details. Interior: cabin condition summary with the focused item.
 */
export function DigitalTwinAnnotation({
  hotspot,
  vehicle,
  onClose,
  onViewEvidence,
}: {
  hotspot: DamageHotspot;
  vehicle: Vehicle;
  onClose: () => void;
  onViewEvidence?: (hotspot: DamageHotspot) => void;
}) {
  const interior = hotspot.mode === "interior";
  const damage = hotspot.kind === "damage";
  const dot = damage ? "bg-rose-400" : "bg-amber-400";

  return (
    <motion.div
      key={hotspot.id}
      initial={{ opacity: 0, y: 12, scale: 0.98 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      exit={{ opacity: 0, y: 8, scale: 0.98 }}
      transition={{ duration: 0.28, ease: [0.22, 1, 0.36, 1] }}
      className={cn("glass-strong absolute bottom-4 left-4 w-[296px] rounded-2xl p-4", damage && "warning-ring")}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span className={cn("h-2 w-2 rounded-full", dot, "soft-pulse")} />
            <span className="label-xs !text-white/65">{interior ? "車內" : hotspot.label}</span>
          </div>
          <div className={cn("mt-1 text-[15px] font-semibold tracking-tight", damage ? "text-rose-100" : "text-amber-100")}>
            {interior ? "需要清潔" : "新增車損"}
          </div>
          {!interior && <div className="mt-0.5 text-[12.5px] text-white/70">{hotspot.title} · {TYPE_LABEL[hotspot.type]}</div>}
        </div>
        <button onClick={onClose} className="text-white/40 hover:text-white">
          <X className="h-4 w-4" />
        </button>
      </div>

      {interior ? (
        <>
          <div className="mt-3 grid grid-cols-2 gap-3">
            <Metric label="整潔程度" value={cleanlinessLabel[vehicle.interior.cleanliness]} tone="warn" />
            <Metric label="AI 信心度" value={pct(vehicle.interior.confidence)} />
          </div>
          <div className="mt-3">
            <div className="label-xs mb-1.5">偵測到 {vehicle.interior.detected.length} 項問題</div>
            <ul className="space-y-1">
              {vehicle.hotspots
                .filter((h) => h.mode === "interior")
                .map((h) => (
                  <li key={h.id} className={cn("flex items-center justify-between rounded-md px-2 py-1 text-[12px]", h.id === hotspot.id ? "bg-amber-400/12 text-amber-100" : "text-white/65")}>
                    <span>{h.label}</span>
                    <span className="text-white/80">{h.title}</span>
                  </li>
                ))}
            </ul>
          </div>
        </>
      ) : (
        <>
          <div className="mt-3 grid grid-cols-2 gap-3">
            <Metric label="AI 信心度" value={pct(hotspot.confidence)} />
            <div>
              <div className="label-xs">嚴重程度</div>
              <div className={cn("mt-1 inline-block rounded-md px-2 py-0.5 text-[12px] font-semibold tracking-wide", severityMeta[hotspot.severity].bg, severityMeta[hotspot.severity].text)}>
                {severityMeta[hotspot.severity].label}
              </div>
            </div>
          </div>
          <p className="mt-3 text-[12px] leading-relaxed text-muted">{hotspot.description}</p>
        </>
      )}

      {onViewEvidence && (
        <Button size="sm" variant="primary" block className="mt-3" icon={<ImageIcon />} onClick={() => onViewEvidence(hotspot)}>
          查看證據
        </Button>
      )}
    </motion.div>
  );
}

function Metric({ label, value, tone }: { label: string; value: string; tone?: "warn" }) {
  return (
    <div>
      <div className="label-xs">{label}</div>
      <div className={cn("tabular mt-0.5 text-lg font-semibold", tone === "warn" ? "text-amber-200" : "text-white")}>{value}</div>
    </div>
  );
}

const TYPE_LABEL: Record<DamageHotspot["type"], string> = { scratch: "刮痕", dent: "凹陷", crack: "裂痕", paint: "漆面轉印", stain: "污漬", debris: "雜物" };

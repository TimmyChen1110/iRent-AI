"use client";

import { AnimatePresence, motion } from "framer-motion";
import { CheckCircle2, Info, AlertTriangle, X } from "lucide-react";
import { useOps } from "@/store/OpsStore";
import { cn } from "@/lib/utils";

export function Toasts() {
  const { toasts, dismissToast } = useOps();
  const icons = {
    success: <CheckCircle2 className="h-4 w-4 text-emerald-300" />,
    info: <Info className="h-4 w-4 text-sky-300" />,
    warning: <AlertTriangle className="h-4 w-4 text-amber-300" />,
  };
  return (
    <div className="pointer-events-none fixed bottom-6 right-6 z-[70] flex w-80 flex-col gap-2">
      <AnimatePresence>
        {toasts.map((t) => (
          <motion.div
            key={t.id}
            initial={{ opacity: 0, y: 12, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 8, scale: 0.98 }}
            className={cn("glass-strong pointer-events-auto flex items-start gap-3 rounded-xl p-3.5")}
          >
            <span className="mt-0.5">{icons[t.tone]}</span>
            <div className="min-w-0 flex-1">
              <div className="text-[13px] font-medium text-white/90">{t.title}</div>
              {t.detail && <div className="mt-0.5 text-[12px] text-muted">{t.detail}</div>}
            </div>
            <button onClick={() => dismissToast(t.id)} className="text-white/40 hover:text-white/80">
              <X className="h-3.5 w-3.5" />
            </button>
          </motion.div>
        ))}
      </AnimatePresence>
    </div>
  );
}

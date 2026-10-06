"use client";

import { Sparkles } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { cn } from "@/lib/utils";

/** Compact AI insight block reused by both the Taiwan and Taipei layers. */
export function AIMapInsight({ title, lines, recommendation, action, onAction, className }: { title: string; lines: string[]; recommendation: string; action?: string; onAction?: () => void; className?: string }) {
  return (
    <div className={cn("rounded-xl border border-sky-400/15 bg-sky-400/[0.05] p-4", className)}>
      <div className="flex items-center gap-1.5 text-[10.5px] font-semibold tracking-[0.08em] text-sky-200">
        <Sparkles className="h-3.5 w-3.5" />
        AI 營運洞察
      </div>
      <div className="mt-2 text-[13.5px] font-semibold text-white/95">{title}</div>
      <ul className="mt-2 space-y-0.5 text-[12px] text-white/70">
        {lines.map((l) => (
          <li key={l} className="flex items-center gap-2">
            <span className="h-1 w-1 rounded-full bg-white/40" />
            {l}
          </li>
        ))}
      </ul>
      <div className="mt-3 text-[12px]">
        <span className="text-white/50">建議：</span>
        <span className="font-medium text-amber-100">{recommendation}</span>
      </div>
      {action && onAction && (
        <Button variant="primary" size="sm" block className="mt-3" onClick={onAction}>
          {action}
        </Button>
      )}
    </div>
  );
}

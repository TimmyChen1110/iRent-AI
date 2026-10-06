"use client";

import { ChevronRight, Globe2, Building2, Car } from "lucide-react";
import { cn } from "@/lib/utils";

export interface Crumb {
  id: string;
  label: string;
  icon?: "taiwan" | "city" | "vehicle";
  onClick?: () => void;
}

const ICONS = { taiwan: Globe2, city: Building2, vehicle: Car };

export function CommandBreadcrumb({ crumbs }: { crumbs: Crumb[] }) {
  return (
    <nav className="flex items-center gap-1 text-[13px]">
      {crumbs.map((c, i) => {
        const last = i === crumbs.length - 1;
        const Icon = c.icon ? ICONS[c.icon] : null;
        return (
          <span key={c.id} className="flex items-center gap-1">
            <button
              onClick={c.onClick}
              disabled={last || !c.onClick}
              className={cn(
                "flex items-center gap-1.5 rounded-lg px-2 py-1 transition",
                last ? "font-semibold text-white" : "text-white/55 hover:bg-white/[0.06] hover:text-white",
                c.icon === "vehicle" && "font-mono",
              )}
            >
              {Icon && <Icon className="h-3.5 w-3.5" />}
              {c.label}
            </button>
            {!last && <ChevronRight className="h-3.5 w-3.5 text-white/25" />}
          </span>
        );
      })}
    </nav>
  );
}

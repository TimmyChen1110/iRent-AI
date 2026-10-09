"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { motion } from "framer-motion";
import { LayoutDashboard, Car, AlertTriangle, SprayCan, Wrench, Sparkles, PanelLeftClose, PanelLeftOpen, Hexagon, Radar, Bell, Users, Settings, Smartphone, ClipboardCheck, FlaskConical } from "lucide-react";
import { cn } from "@/lib/utils";
import { useOps } from "@/store/OpsStore";

const NAV = [
  { href: "/command", label: "指揮中心", icon: Radar },
  { href: "/", label: "總覽", icon: LayoutDashboard },
  { href: "/inbox", label: "通知中心", icon: Bell, badge: "unread" as const },
  { href: "/incidents", label: "事件中心", icon: AlertTriangle, badge: "cases" as const },
  { href: "/inspections", label: "檢查紀錄", icon: ClipboardCheck },
  { href: "/fleet", label: "車隊", icon: Car },
  { href: "/demo-vehicles", label: "Demo 測試車輛", icon: FlaskConical },
  { href: "/cleaning", label: "清潔", icon: SprayCan },
  { href: "/maintenance", label: "維修", icon: Wrench },
  { href: "/insights", label: "AI 洞察", icon: Sparkles },
  { href: "/people", label: "人員與組別", icon: Users },
  { href: "/settings", label: "通知設定", icon: Settings },
];

export function Sidebar({ collapsed, onToggle }: { collapsed: boolean; onToggle: () => void }) {
  const pathname = usePathname();
  const { incidents, summary, health } = useOps();
  const counts = { unread: summary?.unread ?? 0, cases: incidents.filter((i) => i.status === "open").length };

  return (
    <aside className={cn("fixed inset-y-0 left-0 z-40 flex flex-col border-r border-white/[0.06] surface-shell backdrop-blur-xl transition-[width] duration-300", collapsed ? "w-[72px]" : "w-[232px]")}>
      <div className={cn("flex h-16 items-center gap-3 px-4", collapsed && "justify-center px-0")}>
        <div className="relative grid h-9 w-9 shrink-0 place-items-center rounded-xl bg-gradient-to-br from-sky-400/30 to-violet-500/20 ring-1 ring-white/10"><Hexagon className="h-4.5 w-4.5 text-sky-200" strokeWidth={1.8} /><span className="absolute inset-0 rounded-xl bg-sky-400/10 blur-md" /></div>
        {!collapsed && <div className="min-w-0 leading-tight"><div className="truncate text-[13px] font-semibold text-white/90">iRent 整備中心</div><div className="truncate text-[10.5px] text-dim">AI 車隊營運中心</div></div>}
      </div>
      <nav className="mt-2 flex flex-1 flex-col gap-1 px-3">
        {NAV.map(({ href, label, icon: Icon, badge }) => {
          const active = href === "/" ? pathname === "/" : pathname.startsWith(href);
          const n = badge ? counts[badge] : 0;
          return (
            <Link key={href} href={href} title={collapsed ? label : undefined} className={cn("group relative flex h-10 items-center gap-3 rounded-xl px-3 text-[13px] font-medium transition-colors", active ? "text-white" : "text-white/55 hover:bg-white/[0.04] hover:text-white/85", collapsed && "justify-center px-0")}>
              {active && <motion.span layoutId="nav-active" className="absolute inset-0 rounded-xl bg-white/[0.07] ring-1 ring-white/[0.08]" transition={{ type: "spring", stiffness: 400, damping: 36 }} />}
              <Icon className={cn("relative h-4.5 w-4.5 shrink-0", active ? "text-sky-200" : "")} strokeWidth={1.8} />
              {!collapsed && <span className="relative flex-1 truncate">{label}</span>}
              {!collapsed && n > 0 && <span className="relative rounded-full bg-rose-400/15 px-1.5 py-0.5 text-[10px] font-semibold text-rose-300">{n}</span>}
              {collapsed && n > 0 && <span className="absolute right-3 top-2 h-1.5 w-1.5 rounded-full bg-rose-400" />}
            </Link>
          );
        })}
      </nav>
      <div className="border-t border-white/[0.06] p-3 text-[12px]">
        {!collapsed && (
          <div className="mb-2 space-y-1 px-1">
            {health?.demo_mode && <div className="text-[10.5px] text-amber-300/80">DEMO 模式（只影響排序與示範入口）</div>}
            <Link href="/m" className="flex items-center gap-2 text-white/50 hover:text-white"><Smartphone className="h-3.5 w-3.5" />站點人員手機版</Link>
          </div>
        )}
        <button onClick={onToggle} className={cn("flex h-9 w-full items-center gap-3 rounded-xl px-3 text-white/50 transition-colors hover:bg-white/[0.04] hover:text-white/80", collapsed && "justify-center px-0")}>
          {collapsed ? <PanelLeftOpen className="h-4 w-4" /> : <PanelLeftClose className="h-4 w-4" />}
          {!collapsed && <span>收合側欄</span>}
        </button>
      </div>
    </aside>
  );
}

"use client";

import { useState } from "react";
import Link from "next/link";
import { Search, ChevronDown, Command, RotateCcw, LogOut, Wifi, WifiOff, Sun, Moon } from "lucide-react";
import { AnimatePresence, motion } from "framer-motion";
import { useOps } from "@/store/OpsStore";
import { useAuth } from "@/store/AuthStore";
import { useTheme } from "@/store/ThemeStore";
import { cn } from "@/lib/utils";

export function Topbar() {
  const { fleet, conn, health, resetDemo } = useOps();
  const { user, logout } = useAuth();
  const { theme, toggle } = useTheme();
  const [query, setQuery] = useState("");
  const [showMenu, setShowMenu] = useState(false);
  const matches = query.trim() ? fleet.filter((r) => r.rental_fleet && (r.car.toLowerCase().includes(query.toLowerCase()) || (r.location?.station || "").includes(query))).slice(0, 6) : [];
  const connLabel = conn === "live" ? "即時連線" : conn === "offline" ? "離線" : "輪詢中";

  return (
    <header className="sticky top-0 z-30 flex h-16 items-center justify-between border-b border-white/[0.06] surface-shell px-6 backdrop-blur-xl lg:px-8">
      <div className="flex items-center gap-3">
        <h1 className="text-[15px] font-semibold tracking-tight text-white/90">iRent AI 租還車管理後台</h1>
        <span className={cn("hidden items-center gap-1.5 rounded-full px-2 py-0.5 text-[10.5px] font-medium ring-1 md:inline-flex", conn === "offline" ? "bg-rose-400/10 text-rose-300 ring-rose-400/20" : "bg-emerald-400/10 text-emerald-300 ring-emerald-400/20")} title="任務與事件存於後端資料庫，全隊共享">
          {conn === "offline" ? <WifiOff className="h-3 w-3" /> : <Wifi className="h-3 w-3" />}{connLabel}
        </span>
      </div>
      <div className="flex items-center gap-3">
        <div className="relative">
          <div className="flex h-9 w-72 items-center gap-2 rounded-xl border border-white/[0.08] bg-white/[0.04] px-3 text-sm text-white/70 focus-within:border-white/20 focus-within:bg-white/[0.06]">
            <Search className="h-4 w-4 text-white/40" />
            <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="搜尋車牌、位置" className="w-full bg-transparent text-[13px] placeholder:text-white/30 focus:outline-none" />
            <kbd className="hidden items-center gap-0.5 rounded-md border border-white/10 px-1.5 py-0.5 text-[10px] text-white/40 md:inline-flex"><Command className="h-2.5 w-2.5" />K</kbd>
          </div>
          <AnimatePresence>
            {matches.length > 0 && (
              <motion.div initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: 6 }} className="glass-strong absolute right-0 top-11 w-80 overflow-hidden rounded-xl p-1.5">
                {matches.map((r) => <Link key={r.car} href={`/fleet?car=${encodeURIComponent(r.car)}`} onClick={() => setQuery("")} className="flex items-center justify-between rounded-lg px-3 py-2 text-[13px] hover:bg-white/[0.06]"><span className="font-mono font-medium text-white/90">{r.car}</span><span className="text-xs text-muted">{r.location?.station ?? ""}</span></Link>)}
              </motion.div>
            )}
          </AnimatePresence>
        </div>
        <button onClick={toggle} title={theme === "dark" ? "切換為淺色主題" : "切換為深色主題"} aria-label="切換主題" className="grid h-9 w-9 place-items-center rounded-xl border border-white/[0.08] bg-white/[0.04] text-white/70 transition hover:bg-white/[0.08]">
          {theme === "dark" ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
        </button>
        <div className="relative">
          <button onClick={() => setShowMenu((m) => !m)} className="flex h-9 items-center gap-2 rounded-xl border border-white/[0.08] bg-white/[0.04] pl-1 pr-2.5 text-left transition hover:bg-white/[0.08]">
            <span className="grid h-7 w-7 place-items-center rounded-lg bg-gradient-to-br from-sky-400/40 to-violet-500/40 text-[11px] font-semibold text-white">{(user?.name || "?").slice(0, 2)}</span>
            <span className="hidden leading-tight md:block"><span className="block text-[12px] font-medium text-white/90">{user?.name}</span><span className="block text-[10px] text-dim">{user?.role === "admin" ? "管理者" : "站點人員"}</span></span>
            <ChevronDown className={cn("h-3.5 w-3.5 text-white/40 transition", showMenu && "rotate-180")} />
          </button>
          <AnimatePresence>
            {showMenu && (
              <motion.div initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: 6 }} className="glass-strong absolute right-0 top-11 w-60 rounded-xl p-1.5">
                {health?.demo_mode && (
                  <>
                    <div className="px-3 py-2 label-xs">Demo 控制</div>
                    <button onClick={() => { setShowMenu(false); resetDemo(); }} className="flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-left text-[13px] text-white/85 hover:bg-white/[0.06]"><RotateCcw className="h-3.5 w-3.5 text-white/50" />重置 Demo 案例</button>
                  </>
                )}
                <button onClick={() => { setShowMenu(false); logout(); }} className="flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-left text-[13px] text-white/85 hover:bg-white/[0.06]"><LogOut className="h-3.5 w-3.5 text-white/50" />登出</button>
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      </div>
    </header>
  );
}

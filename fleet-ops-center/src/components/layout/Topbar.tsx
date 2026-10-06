"use client";

import { useState } from "react";
import Link from "next/link";
import { Bell, Search, ChevronDown, Command, RotateCcw, LogOut, Wifi, WifiOff, Sun, Moon } from "lucide-react";
import { AnimatePresence, motion } from "framer-motion";
import { useOps } from "@/store/OpsStore";
import { useAuth } from "@/store/AuthStore";
import { useTheme } from "@/store/ThemeStore";
import { EVENT_TXT } from "@/lib/ops/labels";
import { rel } from "@/lib/ops/time";
import { cn } from "@/lib/utils";

export function Topbar() {
  const { vehicles, events, summary, conn, health, resetDemo, markRead, openTask } = useOps();
  const { user, logout } = useAuth();
  const { theme, toggle } = useTheme();
  const [query, setQuery] = useState("");
  const [showNotif, setShowNotif] = useState(false);
  const [showMenu, setShowMenu] = useState(false);
  const unread = events.filter((e) => !e.is_read).slice(0, 8);
  const matches = query.trim() ? vehicles.filter((v) => v.plate.toLowerCase().includes(query.toLowerCase()) || (v.station || "").includes(query)).slice(0, 6) : [];
  const connLabel = conn === "live" ? "即時連線" : conn === "offline" ? "離線" : "輪詢中";

  return (
    <header className="sticky top-0 z-30 flex h-16 items-center justify-between border-b border-white/[0.06] surface-shell px-6 backdrop-blur-xl lg:px-8">
      <div className="flex items-center gap-3">
        <h1 className="text-[15px] font-semibold tracking-tight text-white/90">AI 車隊營運中心</h1>
        <span className={cn("hidden items-center gap-1.5 rounded-full px-2 py-0.5 text-[10.5px] font-medium ring-1 md:inline-flex", conn === "offline" ? "bg-rose-400/10 text-rose-300 ring-rose-400/20" : "bg-emerald-400/10 text-emerald-300 ring-emerald-400/20")} title="任務與事件存於後端資料庫，全隊共享">
          {conn === "offline" ? <WifiOff className="h-3 w-3" /> : <Wifi className="h-3 w-3" />}{connLabel}
        </span>
      </div>
      <div className="flex items-center gap-3">
        <div className="relative">
          <div className="flex h-9 w-72 items-center gap-2 rounded-xl border border-white/[0.08] bg-white/[0.04] px-3 text-sm text-white/70 focus-within:border-white/20 focus-within:bg-white/[0.06]">
            <Search className="h-4 w-4 text-white/40" />
            <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="搜尋車牌、站點" className="w-full bg-transparent text-[13px] placeholder:text-white/30 focus:outline-none" />
            <kbd className="hidden items-center gap-0.5 rounded-md border border-white/10 px-1.5 py-0.5 text-[10px] text-white/40 md:inline-flex"><Command className="h-2.5 w-2.5" />K</kbd>
          </div>
          <AnimatePresence>
            {matches.length > 0 && (
              <motion.div initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: 6 }} className="glass-strong absolute right-0 top-11 w-80 overflow-hidden rounded-xl p-1.5">
                {matches.map((v) => <Link key={v.id} href={`/vehicle?car=${encodeURIComponent(v.id)}`} onClick={() => setQuery("")} className="flex items-center justify-between rounded-lg px-3 py-2 text-[13px] hover:bg-white/[0.06]"><span className="font-mono font-medium text-white/90">{v.plate}</span><span className="text-xs text-muted">{v.station} · {v.aiStatus}</span></Link>)}
              </motion.div>
            )}
          </AnimatePresence>
        </div>
        <button onClick={toggle} title={theme === "dark" ? "切換為淺色主題" : "切換為深色主題"} aria-label="切換主題" className="grid h-9 w-9 place-items-center rounded-xl border border-white/[0.08] bg-white/[0.04] text-white/70 transition hover:bg-white/[0.08]">
          {theme === "dark" ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
        </button>
        <div className="relative">
          <button onClick={() => setShowNotif((s) => !s)} className="relative grid h-9 w-9 place-items-center rounded-xl border border-white/[0.08] bg-white/[0.04] text-white/70 transition hover:bg-white/[0.08]">
            <Bell className="h-4 w-4" />
            {(summary?.unread ?? 0) > 0 && <span className="absolute -right-0.5 -top-0.5 grid h-4 min-w-4 place-items-center rounded-full bg-rose-400 px-1 text-[9.5px] font-bold text-black">{summary?.unread}</span>}
          </button>
          <AnimatePresence>
            {showNotif && (
              <motion.div initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: 6 }} className="glass-strong absolute right-0 top-11 w-80 rounded-xl p-1.5">
                <div className="flex items-center justify-between px-3 py-2"><span className="label-xs">未讀事件</span><Link href="/inbox" onClick={() => setShowNotif(false)} className="text-[11px] text-sky-300 hover:underline">通知中心</Link></div>
                {unread.length === 0 && <div className="px-3 py-3 text-[12px] text-muted">沒有未讀事件</div>}
                {unread.map((e) => (
                  <button key={e.id} onClick={() => { setShowNotif(false); markRead([e.id]); if (e.task_id) openTask(e.task_id); }} className="flex w-full items-center gap-3 rounded-lg px-3 py-2 text-left hover:bg-white/[0.06]">
                    <span className={cn("h-2 w-2 shrink-0 rounded-full", e.priority === "P1" ? "bg-rose-400" : e.priority === "P2" ? "bg-amber-400" : "bg-white/40")} />
                    <span className="min-w-0 flex-1"><span className="block truncate text-[13px] text-white/90">{EVENT_TXT[e.type] || e.type} · {e.car || ""}</span><span className="block truncate text-[11px] text-muted">{e.title || e.detail} · {rel(e.at)}</span></span>
                  </button>
                ))}
              </motion.div>
            )}
          </AnimatePresence>
        </div>
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

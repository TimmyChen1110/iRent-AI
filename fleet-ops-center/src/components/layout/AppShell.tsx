"use client";

import { useState } from "react";
import { usePathname } from "next/navigation";
import { Sidebar } from "./Sidebar";
import { Topbar } from "./Topbar";
import { Toasts } from "./Toasts";
import { LoginPage } from "./LoginPage";
import { TaskDrawer } from "@/components/incident/TaskDrawer";
import { useAuth } from "@/store/AuthStore";
import { cn } from "@/lib/utils";

/**
 * 登入閘門 + 版面。站點人員（station）只看 /m 手機版；管理者看完整後台。
 */
export function AppShell({ children }: { children: React.ReactNode }) {
  const [collapsed, setCollapsed] = useState(false);
  const { user, loading } = useAuth();
  const pathname = usePathname();
  const mobile = pathname === "/m" || pathname.startsWith("/m/");

  if (loading) return <div className="grid min-h-screen place-items-center text-[13px] text-muted">確認登入狀態…</div>;
  if (!user) return <><LoginPage /><Toasts /></>;
  if (user.role === "station" || mobile) {
    return (
      <div className="min-h-screen">
        {children}
        <Toasts />
      </div>
    );
  }
  return (
    <div className="flex min-h-screen">
      <Sidebar collapsed={collapsed} onToggle={() => setCollapsed((c) => !c)} />
      <div className={cn("flex min-w-0 flex-1 flex-col transition-[padding] duration-300", collapsed ? "pl-[72px]" : "pl-[232px]")}>
        <Topbar />
        <main className="mx-auto w-full max-w-[1600px] flex-1 px-6 pb-12 pt-5 lg:px-8">{children}</main>
      </div>
      <TaskDrawer />
      <Toasts />
    </div>
  );
}

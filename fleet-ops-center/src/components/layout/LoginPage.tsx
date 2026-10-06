"use client";

import { useEffect, useState } from "react";
import { Hexagon, LogIn } from "lucide-react";
import { api } from "@/lib/ops/api";
import type { DemoCredential } from "@/lib/ops/types";
import { useAuth } from "@/store/AuthStore";
import { Button } from "@/components/ui/Button";

export function LoginPage() {
  const { login } = useAuth();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [demo, setDemo] = useState<DemoCredential[]>([]);
  useEffect(() => { api.health().then((h) => setDemo(h.demo_credentials || [])).catch(() => {}); }, []);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault(); setBusy(true); setError("");
    try { await login(username.trim(), password); } catch (err) { setError((err as Error).message || "登入失敗"); } finally { setBusy(false); }
  };
  const input = "w-full rounded-xl border border-white/[0.08] bg-white/[0.04] px-3 py-2.5 text-[13px] text-white/90 placeholder:text-white/30 focus:border-white/25 focus:outline-none";

  return (
    <main className="grid min-h-screen place-items-center p-6">
      <form onSubmit={submit} className="glass-strong w-full max-w-[420px] rounded-2xl p-7">
        <div className="flex items-center gap-3">
          <div className="grid h-10 w-10 place-items-center rounded-xl bg-gradient-to-br from-sky-400/30 to-violet-500/20 ring-1 ring-white/10"><Hexagon className="h-5 w-5 text-sky-200" strokeWidth={1.8} /></div>
          <div><div className="text-[15px] font-semibold text-white/95">iRent 整備中心</div><div className="text-[11px] text-dim">AI 車隊營運中心 · 環節三</div></div>
        </div>
        <h1 className="mt-6 text-[20px] font-semibold tracking-tight text-white">登入</h1>
        <p className="mt-1 text-[12.5px] text-muted">管理者進入營運後台；站點人員只會看到自己的整備任務。</p>
        {demo.length > 0 && (
          <div className="mt-5 rounded-xl border border-sky-400/15 bg-sky-400/[0.05] p-3">
            <div className="label-xs mb-2">Demo 快速登入</div>
            <div className="flex flex-wrap gap-2">
              {demo.map((c) => <Button key={c.username} type="button" size="sm" onClick={() => { setUsername(c.username); setPassword(c.password); setError(""); }}>{c.label} · {c.username}</Button>)}
            </div>
          </div>
        )}
        <label className="mt-5 block"><span className="label-xs">帳號</span><input className={`${input} mt-1.5`} autoComplete="username" value={username} onChange={(e) => setUsername(e.target.value)} required /></label>
        <label className="mt-3 block"><span className="label-xs">密碼</span><input className={`${input} mt-1.5`} type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} required /></label>
        {error && <div className="mt-3 rounded-lg border border-rose-400/20 bg-rose-400/[0.08] px-3 py-2 text-[12.5px] text-rose-100" role="alert">{error}</div>}
        <Button type="submit" variant="primary" size="lg" block className="mt-5" icon={<LogIn />} disabled={busy}>{busy ? "登入中…" : "登入"}</Button>
        <div className="mt-3 text-center text-[11px] text-dim">非 Demo 環境不會顯示或啟用預設帳密。</div>
      </form>
    </main>
  );
}

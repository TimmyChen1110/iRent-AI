"use client";

import { Suspense, useMemo, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { motion } from "framer-motion";
import { Lock, LockOpen, MapPin, Wrench } from "lucide-react";
import { useOps } from "@/store/OpsStore";
import { GlassPanel, SectionHeader } from "@/components/ui/GlassPanel";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { fadeUp, stagger } from "@/components/ui/motion";
import { DemoVehicleMap, type MapVehicle } from "@/components/demo/DemoVehicleMap";
import type { FleetRow } from "@/lib/ops/types";
import { cn } from "@/lib/utils";

type Filter = "all" | "available" | "rented" | "maintenance";
const FILTERS: { id: Filter; label: string }[] = [
  { id: "all", label: "全部" }, { id: "available", label: "可租用" }, { id: "rented", label: "租用中" }, { id: "maintenance", label: "整備中" },
];

/** 車隊列的顯示狀態：租用中 > 整備中（未完成整備任務／人工鎖定）> 可租用（含待審核：依既有規則不鎖派單）。 */
function displayStatus(r: FleetRow): { key: Exclude<Filter, "all">; label: string; tone: "success" | "info" | "warning" } {
  if (r.status === "rented") return { key: "rented", label: "租用中", tone: "info" };
  if (r.status === "locked" || !r.rentable) return { key: "maintenance", label: "整備中", tone: "warning" };
  return { key: "available", label: "可租用", tone: "success" };
}

const SESSION_LABEL: Record<string, string> = {
  PICKUP_INSPECTION: "取車檢查中", RENTED: "租用中", RETURN_INITIATED: "還車中", PHOTO_INSPECTION: "還車拍攝／AI 檢測中",
  INSPECTION_COMPLETED: "檢測完成・待確認還車", INSPECTION_FAILED: "AI 檢測失敗",
};

export default function FleetPage() { return <Suspense><FleetView /></Suspense>; }

/**
 * 車輛管理：只列 App 可租車隊（後端 /api/ops/fleet 的 rental_fleet 列），座標與 App 地圖相同（demo_vehicles.lat/lng）。
 * 狀態、可否出租與 App 共用 rental_sessions.availability()；整備任務與人工鎖定沿用既有任務抽屜與鎖定 API。
 */
function FleetView() {
  const { fleet, loaded, lockCar, openTask } = useOps();
  const params = useSearchParams();
  const initial = (params.get("filter") as Filter | null) ?? "all";
  const [filter, setFilter] = useState<Filter>(FILTERS.some((f) => f.id === initial) ? initial : "all");
  const [selected, setSelected] = useState<string | null>(params.get("car"));
  const [busy, setBusy] = useState(false);
  const [focus, setFocus] = useState<{ lat: number; lng: number; token: number } | null>(null);

  const rows = useMemo(() => fleet.filter((r) => r.rental_fleet), [fleet]);
  const list = useMemo(() => rows.filter((r) => filter === "all" || displayStatus(r).key === filter), [rows, filter]);
  const counts = useMemo(() => Object.fromEntries(FILTERS.map((f) => [f.id, rows.filter((r) => f.id === "all" || displayStatus(r).key === f.id).length])), [rows]);
  const mapVehicles = useMemo<MapVehicle[]>(() => rows.filter((r) => r.location).map((r) => {
    const st = displayStatus(r).key;
    return { vehicle_id: r.car, plate: r.car, location: { lat: r.location!.lat, lng: r.location!.lng },
             status: st === "rented" ? "RENTED" : st === "maintenance" ? "MAINTENANCE" : "AVAILABLE", is_demo: Boolean(r.rental_state?.is_demo) };
  }), [rows]);
  const sel = rows.find((r) => r.car === selected) ?? null;

  const toggleLock = async (r: FleetRow) => {
    const reason = r.manual_lock ? undefined : window.prompt(`鎖定 ${r.car}（暫停出租）的原因：`, "車況檢查") ?? null;
    if (reason === null) return;
    setBusy(true);
    try { await lockCar(r.car, !r.manual_lock, reason || undefined); } catch { /* toast shown */ } finally { setBusy(false); }
  };

  return (
    <motion.div variants={stagger} initial="hidden" animate="show" className="space-y-5">
      <motion.div variants={fadeUp}>
        <h2 className="text-[22px] font-semibold tracking-tight text-white">車輛管理</h2>
        <p className="mt-1 text-[13px] text-muted">App 可租車隊。位置就是 App 租車地圖上的位置；整備任務未完成或人工鎖定的車輛，App 會顯示「整備中」且不能租。</p>
      </motion.div>

      <motion.div variants={fadeUp} className="flex flex-wrap gap-2">
        {FILTERS.map((f) => (
          <button key={f.id} onClick={() => setFilter(f.id)} data-testid={`filter-${f.id}`} className={cn("flex items-center gap-2 rounded-full border px-3.5 py-1.5 text-[12.5px] font-medium transition", filter === f.id ? "border-white/25 bg-white/[0.1] text-white" : "border-white/[0.08] text-white/60 hover:bg-white/[0.05] hover:text-white")}>
            {f.label}<span className="tabular text-white/40">{counts[f.id]}</span>
          </button>
        ))}
      </motion.div>

      <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_380px]">
        <GlassPanel variants={fadeUp} padded={false} className="h-[420px] overflow-hidden">
          <DemoVehicleMap vehicles={mapVehicles} selectedId={selected} readOnly onSelect={setSelected}
            focus={focus} />
        </GlassPanel>

        <GlassPanel variants={fadeUp} data-testid="vehicle-panel">
          {!sel ? (
            <div className="grid h-full place-items-center py-10 text-center text-[13px] text-muted">點選地圖標記或下方清單查看車輛</div>
          ) : (() => {
            const st = displayStatus(sel);
            const rs = sel.rental_state;
            return (
              <div className="space-y-4 text-[13px]">
                <SectionHeader title={sel.car} subtitle={sel.model ?? "—"} action={<Badge tone={st.tone}>{st.label}</Badge>} />
                <div className="grid grid-cols-2 gap-3 text-white/75">
                  <div><div className="label-xs">位置</div>{sel.location?.station ?? "—"}</div>
                  <div><div className="label-xs">座標</div><span className="font-mono text-[12px]">{sel.location ? `${sel.location.lat.toFixed(5)}, ${sel.location.lng.toFixed(5)}` : "—"}</span></div>
                  <div><div className="label-xs">可否出租</div>{sel.rentable ? <span className="text-emerald-300">可出租</span> : <span className="text-amber-300">暫停出租</span>}</div>
                  <div><div className="label-xs">類型</div>{rs?.is_fixture ? "固定劇本車（AI 結果為劇本）" : rs?.admin_created ? "Demo 測試車（後台建立）" : rs?.is_demo ? "Demo 測試車（內建）" : "模擬車輛"}</div>
                  <div><div className="label-xs">App 地圖</div>{rs?.visibility === "internal" ? <span className="text-white/55">不顯示（內部車輛）</span> : "顯示"}</div>
                </div>
                {rs?.session_id && (
                  <div className="rounded-xl border border-sky-400/20 bg-sky-400/[0.06] px-3 py-2">
                    <div className="label-xs">目前租約</div>
                    <Link href={`/rentals?session=${encodeURIComponent(rs.session_id)}`} className="text-sky-200 hover:underline">{rs.session_id}</Link>
                    <span className="ml-2 text-white/60">{SESSION_LABEL[rs.session_state ?? ""] ?? rs.session_state}</span>
                  </div>
                )}
                <div>
                  <div className="label-xs mb-1.5">整備任務（完成後車輛自動恢復可租用）</div>
                  {sel.open_tasks.length === 0 ? <div className="text-[12px] text-muted">沒有未完成的整備任務。</div> : sel.open_tasks.map((t) => (
                    <button key={t.id} onClick={() => openTask(t.id)} data-testid={`task-${t.id}`} className="mb-1.5 flex w-full items-center justify-between rounded-lg border border-white/[0.08] bg-white/[0.02] px-3 py-2 text-left hover:border-white/20">
                      <span className="flex items-center gap-2"><Wrench className="h-3.5 w-3.5 text-amber-300" />#{t.id} {t.task_type === "cleaning" ? "清潔" : "維修"}・{t.title}</span>
                      <span className="text-[11px] text-white/55">{t.status === "pending" ? "待處理" : "處理中"}</span>
                    </button>
                  ))}
                </div>
                <div className="border-t border-white/[0.06] pt-3">
                  <Button size="sm" variant={sel.manual_lock ? "secondary" : "warning"} disabled={busy} icon={sel.manual_lock ? <LockOpen className="h-3.5 w-3.5" /> : <Lock className="h-3.5 w-3.5" />} onClick={() => toggleLock(sel)}>
                    {sel.manual_lock ? "解除鎖定（恢復出租）" : "人工鎖定（暫停出租）"}
                  </Button>
                  {sel.manual_lock && sel.lock_reason && <div className="mt-1.5 text-[12px] text-muted">鎖定原因：{sel.lock_reason}</div>}
                </div>
              </div>
            );
          })()}
        </GlassPanel>
      </div>

      <GlassPanel variants={fadeUp} padded={false} className="overflow-hidden">
        <table className="w-full text-left text-[13px]" data-testid="fleet-table">
          <thead><tr className="border-b border-white/[0.06] text-[10.5px] uppercase tracking-wider text-white/40">
            <th className="px-5 py-3 font-medium">車牌</th><th className="px-4 py-3 font-medium">車型</th><th className="px-4 py-3 font-medium">位置</th><th className="px-4 py-3 font-medium">狀態</th><th className="px-4 py-3 font-medium">可否出租</th><th className="px-4 py-3 font-medium">整備</th>
          </tr></thead>
          <tbody>
            {list.map((r) => {
              const st = displayStatus(r);
              return (
                <tr key={r.car} data-testid={`fleet-row-${r.car}`} onClick={() => { setSelected(r.car); if (r.location) setFocus({ lat: r.location.lat, lng: r.location.lng, token: Date.now() }); }} className={cn("cursor-pointer border-b border-white/[0.04] transition hover:bg-white/[0.03]", selected === r.car && "bg-white/[0.04]")}>
                  <td className="px-5 py-3 font-mono font-medium text-white/90">{r.car}{r.manual_lock && <Lock className="ml-2 inline h-3 w-3 text-white/40" />}{r.rental_state?.is_fixture ? <span className="ml-2"><Badge tone="violet">固定劇本</Badge></span> : r.rental_state?.is_demo && <span className="ml-2"><Badge tone="warning">DEMO</Badge></span>}{r.rental_state?.visibility === "internal" && <span className="ml-1.5 text-[11px] text-white/40">App 不顯示</span>}</td>
                  <td className="px-4 py-3 text-white/70">{r.model ?? "—"}</td>
                  <td className="px-4 py-3 text-white/70"><span className="flex items-center gap-1.5"><MapPin className="h-3 w-3 text-white/30" />{r.location?.station ?? "—"}</span></td>
                  <td className="px-4 py-3"><Badge tone={st.tone}>{st.label}</Badge></td>
                  <td className="px-4 py-3">{r.rentable ? <span className="text-emerald-300">可出租</span> : <span className="text-white/45">否</span>}</td>
                  <td className="px-4 py-3 text-white/60">{r.open_tasks.length ? `${r.open_tasks.length} 項未完成` : "—"}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
        {list.length === 0 && <div className="p-10 text-center text-[13px] text-muted">{loaded ? "沒有符合的車輛。" : "載入中…"}</div>}
      </GlassPanel>
    </motion.div>
  );
}

"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { motion } from "framer-motion";
import { FlaskConical, MapPin, Plus, Trash2, Pencil, Check, X, Crosshair } from "lucide-react";
import { GlassPanel, SectionHeader } from "@/components/ui/GlassPanel";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { fadeUp, stagger } from "@/components/ui/motion";
import { DemoVehicleMap, type LatLng } from "@/components/demo/DemoVehicleMap";
import { api, ApiError } from "@/lib/ops/api";
import type { DevVehicle } from "@/lib/ops/types";
import { useOps } from "@/store/OpsStore";
import { cn } from "@/lib/utils";

const STATUS_LABEL: Record<DevVehicle["status"], { text: string; tone: "success" | "info" | "warning" }> = {
  AVAILABLE: { text: "可租用", tone: "success" },
  RENTED: { text: "租用中", tone: "info" },
  MAINTENANCE: { text: "整備中", tone: "warning" },
  PARKED: { text: "停放（車牌讓出）", tone: "info" },
};

type Notice = { tone: "success" | "info" | "warning"; title: string; detail?: string } | null;
const NOTICE_TONE = { success: "border-emerald-400/25 bg-emerald-500/10 text-emerald-200", info: "border-sky-400/25 bg-sky-500/10 text-sky-200", warning: "border-amber-400/25 bg-amber-500/10 text-amber-200" };

const errText = (e: unknown) => (e instanceof ApiError ? e.message : "操作失敗，請稍後再試");

/**
 * Demo 測試車輛管理（僅管理者）：在地圖上點選位置建立車輛、拖曳標記改位置、編輯車牌、刪除未租用的車輛。
 * 資料直接寫入後端 demo_vehicles（category=demo、admin_created），App 租車地圖與車隊清單即時讀同一份資料與座標。
 */
export default function DemoVehiclesPage() {
  const { refresh } = useOps();
  // 本頁操作回饋顯示在頁首下方（全站提示框固定在右下角，會蓋住表格右側的操作按鈕）
  const [notice, setNotice] = useState<Notice>(null);
  useEffect(() => {
    if (!notice) return;
    const t = setTimeout(() => setNotice(null), 4800);
    return () => clearTimeout(t);
  }, [notice]);
  const [vehicles, setVehicles] = useState<DevVehicle[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [draft, setDraft] = useState<LatLng | null>(null);
  const [focus, setFocus] = useState<(LatLng & { token: number }) | null>(null);
  const [form, setForm] = useState({ plate: "", model: "", locationName: "" });
  const [busy, setBusy] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [editing, setEditing] = useState<{ id: string; plate: string } | null>(null);

  const load = useCallback(async () => {
    try {
      const r = await api.devVehicles();
      setVehicles(r.vehicles);
      setLoadError(null);
    } catch (e) {
      setLoadError(errText(e));
    }
  }, []);
  useEffect(() => {
    let alive = true;
    api.devVehicles().then((r) => { if (alive) { setVehicles(r.vehicles); setLoadError(null); } }).catch((e) => { if (alive) setLoadError(errText(e)); });
    return () => { alive = false; };
  }, []);

  const afterChange = useCallback(async () => { await load(); void refresh(); }, [load, refresh]);
  const selected = useMemo(() => vehicles.find((v) => v.vehicle_id === selectedId) ?? null, [vehicles, selectedId]);
  const plateKey = (p: string) => p.toUpperCase().replace(/[^A-Z0-9]/g, "");
  const fixtureForPlate = useMemo(
    () => (form.plate.trim() ? vehicles.find((v) => v.is_fixture && v.status !== "PARKED" && plateKey(v.plate) === plateKey(form.plate)) ?? null : null),
    [vehicles, form.plate],
  );

  const create = async () => {
    if (!draft) { setFormError("請先在地圖上點選車輛位置"); return; }
    setBusy(true);
    setFormError(null);
    try {
      const v = await api.createDemoVehicle({ plate: form.plate, lat: draft.lat, lng: draft.lng, model: form.model || undefined, location_name: form.locationName || undefined });
      setNotice({ title: `已建立 Demo 車輛 ${v.plate}`, detail: "App 租車地圖與車隊清單已可看到這台車", tone: "success" });
      setForm({ plate: "", model: "", locationName: "" });
      setDraft(null);
      setSelectedId(v.vehicle_id);
      await afterChange();
    } catch (e) {
      setFormError(errText(e));
    } finally {
      setBusy(false);
    }
  };

  const move = async (id: string, p: LatLng) => {
    const v = vehicles.find((x) => x.vehicle_id === id);
    try {
      await api.setVehicleLocation(id, { ...p, location_name: v?.admin_created ? "後台指定位置（Demo）" : undefined });
      setNotice({ title: `${v?.plate ?? id} 位置已更新`, detail: `${p.lat.toFixed(5)}, ${p.lng.toFixed(5)}`, tone: "success" });
    } catch (e) {
      setNotice({ title: "位置更新失敗", detail: errText(e), tone: "warning" });
    }
    await afterChange();
  };

  const savePlate = async () => {
    if (!editing) return;
    try {
      await api.patchDemoVehicle(editing.id, { plate: editing.plate });
      setNotice({ title: "車牌已更新", tone: "success" });
      setEditing(null);
      await afterChange();
    } catch (e) {
      setNotice({ title: "車牌更新失敗", detail: errText(e), tone: "warning" });
    }
  };

  const remove = async (v: DevVehicle) => {
    if (!window.confirm(`刪除 Demo 車輛 ${v.plate}？過去的租約與檢查紀錄會保留。`)) return;
    try {
      await api.deleteDemoVehicle(v.vehicle_id);
      setNotice({ title: `已刪除 ${v.plate}`, tone: "info" });
      if (selectedId === v.vehicle_id) setSelectedId(null);
      await afterChange();
    } catch (e) {
      setNotice({ title: "無法刪除", detail: errText(e), tone: "warning" });
    }
  };

  const setDraftField = (k: "lat" | "lng", value: string) => {
    const n = Number(value);
    if (!Number.isFinite(n)) return;
    setDraft((d) => ({ lat: d?.lat ?? 25.0174, lng: d?.lng ?? 121.5397, [k]: n }));
  };

  return (
    <motion.div variants={stagger} initial="hidden" animate="show" className="space-y-5">
      <motion.div variants={fadeUp} className="flex items-end justify-between gap-4">
        <div>
          <h2 className="flex items-center gap-2 text-[22px] font-semibold tracking-tight text-white"><FlaskConical className="h-5 w-5 text-amber-300" />Demo 測試車輛</h2>
          <p className="mt-1 text-[13px] text-muted">在地圖上點選位置建立測試車輛；拖曳選取中車輛的標記即可改位置。座標就是 App 租車地圖顯示的位置。</p>
        </div>
        <Badge tone="warning">僅供展示 · 非正式車隊</Badge>
      </motion.div>
      {notice && (
        <div role="status" data-testid="page-notice" className={cn("flex items-start justify-between gap-3 rounded-xl border px-4 py-2.5 text-[13px]", NOTICE_TONE[notice.tone])}>
          <span><span className="font-medium">{notice.title}</span>{notice.detail && <span className="ml-2 opacity-80">{notice.detail}</span>}</span>
          <button aria-label="關閉提示" onClick={() => setNotice(null)} className="opacity-70 hover:opacity-100"><X className="h-3.5 w-3.5" /></button>
        </div>
      )}

      <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_400px]">
        <GlassPanel variants={fadeUp} padded={false} className="h-[620px] overflow-hidden">
          <DemoVehicleMap
            vehicles={vehicles}
            selectedId={selectedId}
            draft={draft}
            focus={focus}
            onMapClick={(p) => { setDraft(p); setSelectedId(null); setFormError(null); }}
            onSelect={(id) => { setSelectedId(id); setDraft(null); }}
            onDraftMove={setDraft}
            onVehicleMove={move}
          />
        </GlassPanel>

        <div className="space-y-5">
          <GlassPanel variants={fadeUp} data-testid="create-panel">
            <SectionHeader title="新增 Demo 車輛" subtitle="建立後預設可租用，App 立即可見" />
            <div className="space-y-3 text-[13px]">
              <label className="block"><span className="label-xs">車牌號碼 *</span>
                <input data-testid="plate-input" className="mt-1 h-9 w-full rounded-lg border border-white/[0.1] bg-white/[0.04] px-3 font-mono uppercase text-white focus:outline-none" placeholder="ABC-1234" value={form.plate} onChange={(e) => setForm({ ...form, plate: e.target.value })} />
              </label>
              <label className="block"><span className="label-xs">車型（選填）</span>
                <input className="mt-1 h-9 w-full rounded-lg border border-white/[0.1] bg-white/[0.04] px-3 text-white focus:outline-none" placeholder="Demo 測試車輛" value={form.model} onChange={(e) => setForm({ ...form, model: e.target.value })} />
              </label>
              <label className="block"><span className="label-xs">位置名稱（選填）</span>
                <input className="mt-1 h-9 w-full rounded-lg border border-white/[0.1] bg-white/[0.04] px-3 text-white focus:outline-none" placeholder="例如：二活前停車格" value={form.locationName} onChange={(e) => setForm({ ...form, locationName: e.target.value })} />
              </label>
              <div>
                <span className="label-xs flex items-center gap-1"><MapPin className="h-3 w-3" />位置 {draft ? "（可拖曳黃色標記微調）" : "— 請在地圖上點選"}</span>
                <div className="mt-1 grid grid-cols-2 gap-2">
                  <input data-testid="lat-input" aria-label="緯度" className="h-9 rounded-lg border border-white/[0.1] bg-white/[0.04] px-3 font-mono text-white focus:outline-none" placeholder="緯度" value={draft?.lat ?? ""} onChange={(e) => setDraftField("lat", e.target.value)} />
                  <input data-testid="lng-input" aria-label="經度" className="h-9 rounded-lg border border-white/[0.1] bg-white/[0.04] px-3 font-mono text-white focus:outline-none" placeholder="經度" value={draft?.lng ?? ""} onChange={(e) => setDraftField("lng", e.target.value)} />
                </div>
              </div>
              {fixtureForPlate && (
                <div data-testid="fixture-hint" className="rounded-lg bg-sky-500/10 px-3 py-2 text-[12.5px] text-sky-200">
                  {form.plate.trim().toUpperCase()} 是固定劇本車的劇本車牌（非實際車輛）。建立後固定劇本車會暫停使用，刪除這台 Demo 車或改用其他車牌即恢復。
                </div>
              )}
              {formError && <div data-testid="form-error" className="rounded-lg bg-rose-500/10 px-3 py-2 text-rose-200">{formError}</div>}
              <Button data-testid="create-btn" variant="primary" block icon={<Plus className="h-4 w-4" />} disabled={busy || !form.plate.trim()} onClick={create}>
                {busy ? "建立中…" : "建立 Demo 車輛"}
              </Button>
            </div>
          </GlassPanel>

          {selected && (
            <GlassPanel variants={fadeUp} data-testid="selected-panel">
              <SectionHeader title={`選取中：${selected.plate}`} subtitle={selected.status === "RENTED" ? "租用中：不可拖曳、改車牌或刪除" : "拖曳地圖上的標記即可更新位置"} />
              <div className="grid grid-cols-2 gap-2 text-[12.5px] text-white/75">
                <div><div className="label-xs">緯度</div><div className="font-mono" data-testid="selected-lat">{selected.location.lat.toFixed(6)}</div></div>
                <div><div className="label-xs">經度</div><div className="font-mono" data-testid="selected-lng">{selected.location.lng.toFixed(6)}</div></div>
                <div className="col-span-2"><div className="label-xs">位置名稱</div>{selected.location.name ?? "—"}</div>
              </div>
            </GlassPanel>
          )}
        </div>
      </div>

      <GlassPanel variants={fadeUp} padded={false} className="overflow-hidden">
        <div className="flex items-center justify-between px-5 pt-4"><SectionHeader title="可租車輛" subtitle={`${vehicles.length} 台 · App 與車隊清單共用這份資料`} /></div>
        {loadError && <div className="px-5 pb-3 text-[13px] text-rose-300">{loadError}</div>}
        <table className="w-full text-left text-[13px]" data-testid="vehicle-table">
          <thead><tr className="border-b border-white/[0.06] text-[10.5px] uppercase tracking-wider text-white/40"><th className="px-5 py-3 font-medium">車牌</th><th className="px-4 py-3 font-medium">類型</th><th className="px-4 py-3 font-medium">車型</th><th className="px-4 py-3 font-medium">座標</th><th className="px-4 py-3 font-medium">狀態</th><th className="px-4 py-3" /></tr></thead>
          <tbody>
            {vehicles.map((v) => {
              const isEditing = editing?.id === v.vehicle_id;
              const locked = v.status === "RENTED";
              return (
                <tr key={v.vehicle_id} data-testid={`row-${v.plate}`} className={cn("border-b border-white/[0.04]", selectedId === v.vehicle_id && "bg-white/[0.04]")}>
                  <td className="px-5 py-3 font-mono font-medium text-white/90">
                    {isEditing ? (
                      <span className="flex items-center gap-1">
                        <input autoFocus data-testid="edit-plate-input" className="h-8 w-28 rounded-md border border-white/[0.15] bg-white/[0.05] px-2 uppercase text-white focus:outline-none" value={editing.plate} onChange={(e) => setEditing({ id: v.vehicle_id, plate: e.target.value })} onKeyDown={(e) => e.key === "Enter" && savePlate()} />
                        <button aria-label="儲存車牌" data-testid="save-plate" onClick={savePlate} className="rounded p-1 text-emerald-300 hover:bg-white/[0.06]"><Check className="h-4 w-4" /></button>
                        <button aria-label="取消" onClick={() => setEditing(null)} className="rounded p-1 text-white/50 hover:bg-white/[0.06]"><X className="h-4 w-4" /></button>
                      </span>
                    ) : v.plate}
                  </td>
                  <td className="px-4 py-3">
                    {v.admin_created ? <Badge tone="warning">DEMO · 後台建立</Badge> : v.is_fixture ? <Badge tone="violet">固定劇本車</Badge> : v.is_demo ? <Badge tone="violet">DEMO · 內建</Badge> : <Badge>模擬車輛</Badge>}
                  </td>
                  <td className="px-4 py-3 text-white/70">{v.model}</td>
                  <td className="px-4 py-3 font-mono text-[12px] text-white/60">{v.location.lat.toFixed(5)}, {v.location.lng.toFixed(5)}</td>
                  <td className="px-4 py-3"><Badge tone={STATUS_LABEL[v.status].tone}>{STATUS_LABEL[v.status].text}</Badge></td>
                  <td className="px-4 py-3">
                    <span className="flex justify-end gap-1">
                      <Button size="sm" variant="ghost" disabled={v.status === "PARKED"} icon={<Crosshair className="h-3.5 w-3.5" />} onClick={() => { setSelectedId(v.vehicle_id); setDraft(null); setFocus({ ...v.location, token: Date.now() }); }}>定位</Button>
                      {v.admin_created && (
                        <>
                          <Button size="sm" variant="ghost" data-testid={`edit-${v.plate}`} disabled={locked} title={locked ? "租用中不可改車牌" : undefined} icon={<Pencil className="h-3.5 w-3.5" />} onClick={() => setEditing({ id: v.vehicle_id, plate: v.plate })}>車牌</Button>
                          <Button size="sm" variant="danger" data-testid={`delete-${v.plate}`} disabled={locked} title={locked ? "租用中不可刪除" : undefined} icon={<Trash2 className="h-3.5 w-3.5" />} onClick={() => remove(v)}>刪除</Button>
                        </>
                      )}
                    </span>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </GlassPanel>
    </motion.div>
  );
}

"use client";

/**
 * 全站資料層：直接接整備中心後端（/api/ops）。
 * - 5 秒輪詢 + SSE 即時刷新；所有 view model 由後端事實推導（adapters.ts），前端不另存一套狀態。
 * - 行動都走後端：裁決（confirm/reject/retake）→ 自動建單；任務動作只送後端允許的 allowed_actions。
 */
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { api } from "@/lib/ops/api";
import type { FleetRow, Health, OpsCase, OpsEvent, Person, Station, City, Summary, Task as RawTask, TaskAction } from "@/lib/ops/types";
import { syncClock } from "@/lib/ops/time";
import { toIncident, toVehicle, toViewTask, PRIORITY_MAP } from "@/lib/ops/adapters";
import type { Incident, KPI, Task, Vehicle } from "@/types";
import { useAuth } from "./AuthStore";

export interface Toast {
  id: string;
  title: string;
  detail?: string;
  tone: "success" | "info" | "warning";
}

/** AI 建議方案：這台車所有未裁決的 P1/P2 案件 → 逐一 confirm → 後端自動建單。 */
export interface RecommendedPlan {
  vehicleId: string;
  suspend: boolean;
  reasons: { label: string; confidence: number; kind: "damage" | "cleaning" }[];
  steps: { id: string; label: string; type?: "inspection" | "cleaning"; team?: string }[];
  caseIds: string[];
  estimatedReady: string;
  maintenanceTeam?: string;
  cleaningTeam?: string;
}

export const POLL_MS = 5000;

interface OpsContextValue {
  // raw backend data
  health: Health | null;
  summary: Summary | null;
  people: Person[];
  stations: Station[];
  cities: City[];
  fleet: FleetRow[];
  cases: OpsCase[];
  rawTasks: RawTask[];
  events: OpsEvent[];
  conn: "live" | "polling" | "offline";
  tick: number;
  lastEvent: OpsEvent | null;
  loaded: boolean;
  refresh: () => Promise<void>;
  // view models
  vehicles: Vehicle[];
  incidents: Incident[];
  tasks: Task[];
  kpis: KPI[];
  demoVehicleId: string | null;
  getVehicle: (id: string) => Vehicle | undefined;
  getIncident: (id: string) => Incident | undefined;
  getPlan: (vehicleId: string) => RecommendedPlan | null;
  // drawers
  drawerIncidentId: string | null;
  drawerTaskId: number | null;
  openIncident: (caseId: string) => void;
  openTask: (taskId: number) => void;
  closeDrawer: () => void;
  // actions
  decideCase: (caseId: string, decision: "confirm" | "reject" | "retake", note?: string) => Promise<void>;
  undoCase: (caseId: string) => Promise<void>;
  executePlan: (vehicleId: string) => Promise<string[]>;
  taskAction: (taskId: number, action: TaskAction) => Promise<void>;
  assignTask: (taskId: number, personId: number | null) => Promise<void>;
  lockCar: (car: string, locked: boolean, reason?: string) => Promise<void>;
  relocateCar: (car: string, stationId: string | null) => Promise<void>;
  markRead: (ids: number[] | null) => Promise<void>;
  resetDemo: () => Promise<void>;
  // toasts
  toasts: Toast[];
  pushToast: (toast: Omit<Toast, "id">) => void;
  dismissToast: (id: string) => void;
}

const OpsContext = createContext<OpsContextValue | null>(null);

export function OpsProvider({ children }: { children: ReactNode }) {
  const { user } = useAuth();
  const station = user?.role === "station";
  const [health, setHealth] = useState<Health | null>(null);
  const [summary, setSummary] = useState<Summary | null>(null);
  const [people, setPeople] = useState<Person[]>([]);
  const [stations, setStations] = useState<Station[]>([]);
  const [cities, setCities] = useState<City[]>([]);
  const [fleet, setFleet] = useState<FleetRow[]>([]);
  const [cases, setCases] = useState<OpsCase[]>([]);
  const [rawTasks, setRawTasks] = useState<RawTask[]>([]);
  const [events, setEvents] = useState<OpsEvent[]>([]);
  const [conn, setConn] = useState<OpsContextValue["conn"]>("polling");
  const [tick, setTick] = useState(0);
  const [loaded, setLoaded] = useState(false);
  const [lastEvent, setLastEvent] = useState<OpsEvent | null>(null);
  const [toasts, setToasts] = useState<Toast[]>([]);
  const [drawerIncidentId, setDrawerIncidentId] = useState<string | null>(null);
  const [drawerTaskId, setDrawerTaskId] = useState<number | null>(null);
  const fails = useRef(0);
  const live = useRef(false);

  const pushToast = useCallback((toast: Omit<Toast, "id">) => {
    const id = `toast-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`;
    setToasts((l) => [...l, { ...toast, id }].slice(-3));
    setTimeout(() => setToasts((l) => l.filter((t) => t.id !== id)), 4800);
  }, []);

  const refresh = useCallback(async () => {
    if (!user || station) return;
    try {
      const [s, p, f, c, t, e] = await Promise.all([api.summary(), api.people(), api.fleet(), api.cases(), api.tasks(), api.events({ limit: 200 })]);
      syncClock(s.server_time);
      setSummary(s); setPeople(p.people); setFleet(f.fleet); setCases(c.cases); setRawTasks(t.tasks); setEvents(e.events);
      fails.current = 0;
      setConn(live.current ? "live" : "polling");
      setLoaded(true);
      setTick((x) => x + 1);
    } catch {
      fails.current += 1;
      if (fails.current >= 2) setConn("offline");
    }
  }, [user, station]);

  useEffect(() => {
    if (!user) return;
    api.health().then((h) => { setHealth(h); syncClock(h.server_time); }).catch(() => setConn("offline"));
    api.stations().then((r) => { setStations(r.stations); setCities(r.cities); }).catch(() => {});
    if (station) return;
    const first = setTimeout(refresh, 0);
    const id = setInterval(refresh, POLL_MS);
    return () => { clearTimeout(first); clearInterval(id); };
  }, [refresh, user, station]);

  // SSE：新事件即時到；斷線退回輪詢並每 10 秒重連
  useEffect(() => {
    if (!user || station) return;
    let es: EventSource | null = null;
    let retry: ReturnType<typeof setTimeout> | null = null;
    let closed = false;
    const connect = () => {
      if (closed) return;
      es = new EventSource("/api/ops/events/stream");
      es.addEventListener("hello", () => { live.current = true; setConn("live"); });
      es.addEventListener("ops", (m) => {
        try { setLastEvent(JSON.parse((m as MessageEvent).data)); } catch { /* ignore */ }
        refresh();
      });
      es.onerror = () => {
        live.current = false; setConn("polling");
        es?.close(); es = null;
        retry = setTimeout(connect, 10000);
      };
    };
    connect();
    return () => { closed = true; live.current = false; es?.close(); if (retry) clearTimeout(retry); };
  }, [refresh, user, station]);

  /* ---------- view models ---------- */
  const vehicles = useMemo<Vehicle[]>(() => {
    const cars = new Set<string>([...fleet.map((r) => r.car), ...cases.map((c) => c.car), ...rawTasks.map((t) => t.car || "").filter(Boolean)]);
    const byCar = (car: string) => ({ row: fleet.find((r) => r.car === car), cs: cases.filter((c) => c.car === car), ts: rawTasks.filter((t) => t.car === car) });
    const list = [...cars].map((car) => { const { row, cs, ts } = byCar(car); return toVehicle(car, row, cs, ts); });
    const rank: Record<string, number> = { damage: 0, cleaning: 1, unavailable: 2, "pending-review": 3, ready: 4, healthy: 5 };
    return list.sort((a, b) => (rank[a.status] ?? 9) - (rank[b.status] ?? 9) || a.plate.localeCompare(b.plate));
  }, [fleet, cases, rawTasks]);

  const incidents = useMemo<Incident[]>(() => cases.map(toIncident).filter((x): x is Incident => x !== null), [cases]);
  const tasks = useMemo<Task[]>(() => rawTasks.map(toViewTask), [rawTasks]);

  const kpis = useMemo<KPI[]>(() => {
    const count = (s: Vehicle["status"]) => vehicles.filter((v) => v.status === s).length;
    return [
      { id: "total", label: "車輛總數", value: vehicles.length, trend: 0, trendLabel: "資料集＋現場車輛", tone: "neutral" },
      { id: "healthy", label: "正常車輛", value: count("healthy") + count("ready"), trend: 0, trendLabel: "無待辦整備", tone: "positive" },
      { id: "cleaning", label: "待清潔", value: count("cleaning") + rawTasks.filter((t) => t.task_type === "cleaning" && t.status !== "completed" && t.status !== "cancelled").length, trend: 0, trendLabel: "AI 標記＋清潔任務", tone: "warning" },
      { id: "damage", label: "車損警示", value: count("damage"), trend: summary?.p1_not_started ?? 0, trendLabel: "P1 未開工", tone: "danger" },
      { id: "pending", label: "待人工審核", value: cases.filter((c) => c.review_status === "unreviewed").length, trend: summary?.overdue ?? 0, trendLabel: "SLA 逾時任務", tone: "info" },
    ];
  }, [vehicles, rawTasks, cases, summary]);

  const demoVehicleId = useMemo(() => {
    const demo = health?.demo_cases?.damage;
    const car = demo ? cases.find((c) => c.case_id === demo)?.car : undefined;
    return car ?? vehicles.find((v) => v.status === "damage")?.id ?? vehicles[0]?.id ?? null;
  }, [health, cases, vehicles]);

  const getPlan = useCallback((vehicleId: string): RecommendedPlan | null => {
    const open = cases.filter((c) => c.car === vehicleId && c.review_status === "unreviewed" && (c.ai_level === "P1" || c.ai_level === "P2"));
    if (open.length === 0) return null;
    const damage = open.filter((c) => c.mode === "pair");
    const cleaning = open.filter((c) => c.mode === "interior");
    const team = (type: "repair" | "cleaning") => {
      const want = type === "repair" ? /維修/ : /清潔/;
      return people.find((p) => p.active && want.test(p.group_name))?.name;
    };
    const steps: RecommendedPlan["steps"] = [{ id: "suspend", label: "暫停車輛派單（整備中不可派）" }];
    if (damage.length) steps.push({ id: "maintenance", label: `確認 ${damage.length} 件車損 → 建立維修任務`, type: "inspection", team: team("repair") });
    if (cleaning.length) steps.push({ id: "cleaning", label: `確認 ${cleaning.length} 件車內髒污 → 建立清潔任務`, type: "cleaning", team: team("cleaning") });
    const top = open[0];
    const sla = top.ai_level === "P1" ? "5 分鐘內開工" : top.ai_level === "P2" ? "4 小時內開工" : "當日開工";
    return {
      vehicleId, suspend: true, caseIds: open.map((c) => c.case_id),
      reasons: open.map((c) => ({ label: c.mode === "interior" ? `車內髒污 · ${c.issues.slice(0, 2).join("、") || c.cleanliness}` : `${c.damages[0]?.location || c.angle} · ${c.damages[0]?.type || "疑似車損"}`, confidence: c.ai_conf ?? 0, kind: c.mode === "interior" ? "cleaning" : "damage" })),
      steps, estimatedReady: `SLA ${sla}`, maintenanceTeam: team("repair"), cleaningTeam: team("cleaning"),
    };
  }, [cases, people]);

  /* ---------- actions ---------- */
  const wrap = useCallback(async (fn: () => Promise<unknown>, ok?: string) => {
    try {
      await fn();
      await refresh();
      if (ok) pushToast({ tone: "success", title: ok });
    } catch (e) {
      pushToast({ tone: "warning", title: (e as Error).message || "操作失敗" });
      throw e;
    }
  }, [refresh, pushToast]);

  const decideCase = useCallback<OpsContextValue["decideCase"]>((caseId, decision, note) =>
    wrap(() => api.decideCase(caseId, decision, note), decision === "confirm" ? `已確認 ${caseId}，整備任務已建立` : decision === "reject" ? `已駁回 ${caseId}` : `已要求 ${caseId} 補件`), [wrap]);
  const undoCase = useCallback<OpsContextValue["undoCase"]>((caseId) => wrap(() => api.undoCase(caseId), `已復原 ${caseId} 的裁決`), [wrap]);

  const executePlan = useCallback<OpsContextValue["executePlan"]>(async (vehicleId) => {
    const plan = getPlan(vehicleId);
    if (!plan) return [];
    const created: string[] = [];
    try {
      for (const cid of plan.caseIds) {
        const r = await api.decideCase(cid, "confirm");
        if (r.task) created.push(`#${r.task.id}`);
      }
    } finally {
      await refresh();
    }
    return created;
  }, [getPlan, refresh]);

  const taskAction = useCallback<OpsContextValue["taskAction"]>((taskId, action) => wrap(() => api.patchTask(taskId, { action })), [wrap]);
  const assignTask = useCallback<OpsContextValue["assignTask"]>((taskId, personId) => wrap(() => api.patchTask(taskId, { action: "assign", assignee_id: personId }), "已更新負責人"), [wrap]);
  const lockCar = useCallback<OpsContextValue["lockCar"]>((car, locked, reason) => wrap(() => api.lockCar(car, locked, reason), locked ? `已鎖定 ${car}` : `已解除鎖定 ${car}`), [wrap]);
  const relocateCar = useCallback<OpsContextValue["relocateCar"]>((car, stationId) => wrap(() => api.setLocation(car, stationId), "已更新站點"), [wrap]);
  const markRead = useCallback<OpsContextValue["markRead"]>((ids) => wrap(() => api.markRead(ids)), [wrap]);
  const resetDemo = useCallback(() => wrap(() => api.demoReset(), "Demo 已重置：示範案例回到「AI 已判定、尚未人工確認」"), [wrap]);

  const value = useMemo<OpsContextValue>(() => ({
    health, summary, people, stations, cities, fleet, cases, rawTasks, events, conn, tick, lastEvent, loaded, refresh,
    vehicles, incidents, tasks, kpis, demoVehicleId,
    getVehicle: (id) => vehicles.find((v) => v.id === id),
    getIncident: (id) => incidents.find((i) => i.id === id),
    getPlan,
    drawerIncidentId, drawerTaskId,
    openIncident: (caseId) => { setDrawerTaskId(null); setDrawerIncidentId(caseId); },
    openTask: (taskId) => { setDrawerIncidentId(null); setDrawerTaskId(taskId); },
    closeDrawer: () => { setDrawerIncidentId(null); setDrawerTaskId(null); },
    decideCase, undoCase, executePlan, taskAction, assignTask, lockCar, relocateCar, markRead, resetDemo,
    toasts, pushToast, dismissToast: (id) => setToasts((l) => l.filter((t) => t.id !== id)),
  }), [health, summary, people, stations, cities, fleet, cases, rawTasks, events, conn, tick, lastEvent, loaded, refresh, vehicles, incidents, tasks, kpis, demoVehicleId, getPlan, drawerIncidentId, drawerTaskId, decideCase, undoCase, executePlan, taskAction, assignTask, lockCar, relocateCar, markRead, resetDemo, toasts, pushToast]);

  return <OpsContext.Provider value={value}>{children}</OpsContext.Provider>;
}

export function useOps() {
  const ctx = useContext(OpsContext);
  if (!ctx) throw new Error("useOps must be used within OpsProvider");
  return ctx;
}

export { PRIORITY_MAP };

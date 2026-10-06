"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { Layers3 } from "lucide-react";
import type { CityNode } from "@/data/fleetMapData";
import { useOps } from "@/store/OpsStore";
import { useFleetMap } from "./useFleetMap";
import { TaiwanFleetMap } from "./TaiwanFleetMap";
import { TaipeiFleetMap } from "./TaipeiFleetMap";
import { NetworkPanel, TaipeiOperationsPanel } from "./MapOperationsPanel";
import { CommandBreadcrumb, type Crumb } from "./CommandBreadcrumb";
import { VehicleWorkspace } from "@/components/workspace/VehicleWorkspace";
import { StatusPill } from "@/components/ui/Badge";
import { fadeUp } from "@/components/ui/motion";
import { cn } from "@/lib/utils";

type Level = "taiwan" | "taipei" | "vehicle";

/**
 * Multi-scale orchestrator: Taiwan (R3F) → Taipei (MapLibre) → Vehicle (existing Digital Twin).
 * Level transitions are timed so the camera flies first, then the next layer crossfades in.
 */
export function FleetCommandCenter() {
  const model = useFleetMap();
  const { incidents, getVehicle, demoVehicleId } = useOps();
  const [level, setLevel] = useState<Level>("taiwan");
  const [focusCity, setFocusCity] = useState<CityNode["id"] | null>(null);
  const [selectedPointId, setSelectedPointId] = useState<string | null>(null);
  const [flyToken, setFlyToken] = useState(0);
  const [vehicleId, setVehicleId] = useState<string | null>(null);
  const [veil, setVeil] = useState(false);
  /** Marker "focus" phase during the city → vehicle hand-off (popup fades, halo intensifies). */
  const [focusing, setFocusing] = useState(false);
  /** Bumped when returning from the vehicle twin so the (still mounted) city map eases back out. */
  const [returnToken, setReturnToken] = useState(0);
  const timers = useRef<ReturnType<typeof setTimeout>[]>([]);
  const later = (fn: () => void, ms: number) => timers.current.push(setTimeout(fn, ms));
  useEffect(() => () => timers.current.forEach(clearTimeout), []);

  /* Taiwan → Taipei: fly to node (~900ms) then crossfade. */
  const enterCity = useCallback((id: CityNode["id"]) => {
    if (id !== "taipei") return;
    setFocusCity("taipei");
    later(() => setVeil(true), 750);
    later(() => { setLevel("taipei"); setVeil(false); setFocusCity(null); }, 1150);
  }, []);

  /* Taipei: select + fly to a vehicle marker. */
  const investigate = useCallback((vid: string) => {
    setSelectedPointId(vid);
    setFlyToken((n) => n + 1);
  }, []);

  /* Preload the vehicle twin chunk while the user is on the city map so the hand-off never shows a loader. */
  useEffect(() => {
    if (level === "taipei") void import("@/components/vehicle/VehicleScene");
  }, [level]);

  /*
   * Taipei → Vehicle choreography (~1.3 s):
   * 0 ms      select + flyTo marker (pitch up)      450 ms  popup fades, halo intensifies
   * 700 ms    radial veil fades in                   1000 ms scene switch, veil fades out
   * 1000 ms+  twin camera already on the right rear door; hotspot + annotation animate in
   */
  const openTwin = useCallback((vid: string) => {
    setVehicleId(vid);
    setSelectedPointId(vid);
    setFlyToken((n) => n + 1);
    later(() => setFocusing(true), 450);
    later(() => setVeil(true), 700);
    later(() => { setLevel("vehicle"); setVeil(false); setFocusing(false); }, 1000);
  }, []);

  const goTaiwan = () => { setLevel("taiwan"); setSelectedPointId(null); setFocusCity(null); };
  /*
   * Vehicle → Taipei (~850 ms): twin fades under the veil, the city map (kept mounted, so no reload
   * and no lost camera) reappears, then the camera eases back from the vehicle to the city view.
   */
  const goTaipei = () => {
    if (level === "vehicle") {
      setVeil(true);
      later(() => { setLevel("taipei"); setSelectedPointId(null); }, 320);
      later(() => { setVeil(false); setReturnToken((n) => n + 1); }, 520);
    } else {
      setLevel("taipei");
      setSelectedPointId(null);
    }
  };

  const vehicle = vehicleId ? getVehicle(vehicleId) : undefined;
  const districtName = vehicle?.district ?? undefined;
  const crumbs: Crumb[] = [
    { id: "taiwan", label: "台灣", icon: "taiwan", onClick: level !== "taiwan" ? goTaiwan : undefined },
    ...(level !== "taiwan" ? [{ id: "taipei", label: "台北", icon: "city" as const, onClick: level === "vehicle" ? goTaipei : undefined }] : []),
    ...(level === "vehicle" && districtName ? [{ id: "district", label: districtName, onClick: goTaipei }] : []),
    ...(level === "vehicle" && vehicle ? [{ id: "vehicle", label: vehicle.plate, icon: "vehicle" as const }] : []),
  ];

  return (
    <div className="space-y-4">
      <motion.div variants={fadeUp} initial="hidden" animate="show" className="flex items-end justify-between gap-4">
        <div>
          <div className="flex items-center gap-3">
            <h2 className="text-[22px] font-semibold tracking-tight text-white">車隊指揮中心</h2>
            <span className="hidden items-center gap-1.5 rounded-full border border-white/10 bg-white/[0.04] px-2.5 py-1 text-[10.5px] font-medium tracking-[0.08em] text-white/60 md:inline-flex">
              <Layers3 className="h-3 w-3 text-sky-300" />
              MULTI-SCALE DIGITAL TWIN · 全國 → 城市 → 車輛
            </span>
          </div>
          <div className="mt-1.5"><CommandBreadcrumb crumbs={crumbs} /></div>
        </div>
        <div className="text-right text-[11.5px] text-dim">
          <div>AI 驅動的車隊可視化</div>
          <div className="text-white/50">從城市尺度到車輛細節</div>
        </div>
      </motion.div>

      <div className="relative">
        {/* City layer stays mounted while the vehicle twin is open (hidden, not unmounted): no map reload, camera preserved. */}
        {level !== "taiwan" && (
          <motion.div
            key="taipei"
            initial={{ opacity: 0, scale: 0.995 }}
            animate={{ opacity: level === "taipei" ? 1 : 0, scale: 1 }}
            transition={{ duration: 0.35 }}
            className={cn("grid gap-4 lg:grid-cols-[minmax(0,1fr)_340px]", level !== "taipei" && "pointer-events-none invisible absolute inset-0")}
            aria-hidden={level !== "taipei"}
          >
            <div className="h-[640px]">
              <TaipeiFleetMap
                points={model.points}
                districts={model.districtSummaries}
                vehicleById={model.storeVehicleById}
                selectedId={selectedPointId}
                onSelect={setSelectedPointId}
                flyToken={flyToken}
                onOpenTwin={openTwin}
                focusing={focusing}
                returnToken={returnToken}
                heroId={demoVehicleId}
              />
            </div>
            <TaipeiOperationsPanel model={model} incidents={incidents} onInvestigate={investigate} selectedVehicleId={selectedPointId} heroId={demoVehicleId} />
          </motion.div>
        )}
        <AnimatePresence mode="wait" initial={false}>
          {level === "taiwan" && (
            <motion.div key="taiwan" initial={{ opacity: 0, scale: 0.995 }} animate={{ opacity: 1, scale: 1 }} exit={{ opacity: 0, scale: 1.01 }} transition={{ duration: 0.35 }} className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_340px]">
              <div className="h-[600px]"><TaiwanFleetMap cities={model.cityNodes} focusCity={focusCity} onSelectCity={enterCity} /></div>
              <NetworkPanel model={model} onInspectCity={enterCity} />
            </motion.div>
          )}
          {level === "vehicle" && vehicle && (
            <motion.div key={`vehicle-${vehicle.id}`} initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -6 }} transition={{ duration: 0.35 }}>
              <div className="mb-3 flex items-center justify-between">
                <div>
                  <div className="label-xs">Vehicle Digital Twin</div>
                  <div className="mt-0.5 font-mono text-[15px] font-semibold text-white/95">{vehicle.plate}</div>
                  <div className="text-[11.5px] text-muted">{vehicle.station}</div>
                </div>
                <StatusPill status={vehicle.status} pulse={vehicle.status === "damage"} />
              </div>
              <VehicleWorkspace vehicle={vehicle} initialHotspotId={vehicle.hotspots.find((h) => h.kind === "damage")?.id ?? vehicle.hotspots[0]?.id ?? null} />
            </motion.div>
          )}
        </AnimatePresence>

        {/* transition veil: dark with a subtle radial focus toward the map center (where the vehicle sits after flyTo) */}
        <AnimatePresence>
          {veil && (
            <motion.div
              key="veil"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.3, ease: "easeInOut" }}
              className="veil-bg pointer-events-none absolute inset-0 z-30 rounded-2xl"
              style={{ backgroundImage: "radial-gradient(28% 32% at 38% 50%, rgba(110,168,255,0.10), transparent 70%)" }}
            />
          )}
        </AnimatePresence>
      </div>
    </div>
  );
}

"use client";

import { useMemo } from "react";
import { useOps } from "@/store/OpsStore";
import { WORKLOAD_WEIGHT, type CityNode, type LngLat } from "@/data/fleetMapData";
import type { Vehicle, VehicleStatus } from "@/types";

export interface MapVehiclePoint {
  id: string;
  plate: string;
  lngLat: LngLat;
  district: string;
  stationId: string;
  cityId: string;
  status: VehicleStatus;
  vehicleId: string;
}

export interface DistrictSummary {
  id: string;
  name: string;
  lngLat: LngLat;
  cityId: string;
  vehicles: number;
  alerts: number;
  workload: number;
}

export interface FleetMapModel {
  points: MapVehiclePoint[];
  districtSummaries: DistrictSummary[];
  cityNodes: CityNode[];
  taipei: { vehicles: number; healthy: number; damage: number; cleaning: number; pendingReview: number };
  network: { vehicles: number; incidents: number; cleaning: number; pendingReview: number };
  storeVehicleById: Record<string, Vehicle>;
}

const ALERT: VehicleStatus[] = ["damage", "cleaning", "pending-review", "unavailable", "maintenance"];
const STATUS_LABEL = (w: number) => (w >= 0.8 ? "最高優先" : w >= 0.45 ? "中等" : "正常");

/**
 * 指揮中心地圖資料：全部由 OpsStore（後端 fleet / cases / tasks / stations）推導。
 * 站點位置來自後端站點表；行政區統計 = 該區各站點車輛加總；城市統計 = 各區加總。
 */
export function useFleetMap(): FleetMapModel {
  const { vehicles, stations, cities } = useOps();

  return useMemo(() => {
    const storeVehicleById = Object.fromEntries(vehicles.map((v) => [v.id, v]));
    const stationById = Object.fromEntries(stations.map((s) => [s.id, s]));
    const points: MapVehiclePoint[] = vehicles
      .filter((v) => v.lngLat && v.stationId && stationById[v.stationId])
      .map((v, i) => {
        const st = stationById[v.stationId!];
        // 同站多車：以小偏移散開，避免標記完全重疊
        const k = i % 7;
        const off = 0.00035;
        const jitter: LngLat = v.exactLocation
          ? v.lngLat!                      // 可租車輛：顯示實際座標，不偏移
          : [v.lngLat![0] + Math.cos(k * 0.9) * off * (k ? 1 : 0), v.lngLat![1] + Math.sin(k * 0.9) * off * (k ? 1 : 0)];
        return { id: v.id, plate: v.plate, lngLat: jitter, district: st.district, stationId: st.id, cityId: st.city, status: v.status, vehicleId: v.id };
      });

    const districtMap = new Map<string, DistrictSummary>();
    for (const st of stations) {
      const key = `${st.city}:${st.district}`;
      const d = districtMap.get(key) ?? { id: key, name: st.district, lngLat: [st.lng, st.lat] as LngLat, cityId: st.city, vehicles: 0, alerts: 0, workload: 0 };
      const inSt = points.filter((p) => p.stationId === st.id);
      d.vehicles += inSt.length;
      d.alerts += inSt.filter((p) => ALERT.includes(p.status)).length;
      d.workload += inSt.reduce((s, p) => s + WORKLOAD_WEIGHT[p.status], 0);
      districtMap.set(key, d);
    }
    const districtSummaries = [...districtMap.values()];

    // 城市負載 = 加權異常量（絕對值），再以最大城市正規化：車多事多的城市就是最高優先。
    const raw = cities.map((c) => {
      const inCity = points.filter((p) => p.cityId === c.id);
      const damage = inCity.filter((p) => p.status === "damage").length;
      const cleaning = inCity.filter((p) => p.status === "cleaning").length;
      const pendingReview = inCity.filter((p) => p.status === "pending-review").length;
      const unavailable = inCity.filter((p) => p.status === "unavailable").length;
      return { c, inCity, damage, cleaning, pendingReview, load: damage * 1 + cleaning * 0.6 + pendingReview * 0.5 + unavailable * 0.8 };
    });
    const maxLoad = Math.max(1, ...raw.map((r) => r.load));
    const cityNodes: CityNode[] = raw.map(({ c, inCity, damage, cleaning, pendingReview, load }) => {
      const w = load / maxLoad;
      return { id: c.id, name: c.name, lngLat: [c.lng, c.lat], vehicles: inCity.length, damage, cleaning, pendingReview, workload: w, statusLabel: STATUS_LABEL(w), enabled: c.id === "taipei" };
    });
    const tp = points.filter((p) => p.cityId === "taipei");
    const taipei = { vehicles: tp.length, healthy: tp.filter((p) => p.status === "healthy" || p.status === "ready").length, damage: tp.filter((p) => p.status === "damage").length, cleaning: tp.filter((p) => p.status === "cleaning").length, pendingReview: tp.filter((p) => p.status === "pending-review").length };
    const network = cityNodes.reduce((a, c) => ({ vehicles: a.vehicles + c.vehicles, incidents: a.incidents + c.damage, cleaning: a.cleaning + c.cleaning, pendingReview: a.pendingReview + c.pendingReview }), { vehicles: 0, incidents: 0, cleaning: 0, pendingReview: 0 });
    return { points, districtSummaries, cityNodes, taipei, network, storeVehicleById };
  }, [vehicles, stations, cities]);
}

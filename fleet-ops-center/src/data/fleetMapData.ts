/**
 * 指揮中心靜態地理資料：台灣外框與地形峰值、狀態色與負載權重。
 * 站點與車輛座標改由後端 /api/ops/stations 與 /api/ops/fleet 提供。
 */
import type { VehicleStatus } from "@/types";

export type LngLat = [number, number];

/** 城市節點（指揮中心台灣層）：座標來自後端 stations，統計由車輛即時推導。 */
export interface CityNode {
  id: string;
  name: string;
  lngLat: LngLat;
  vehicles: number;
  damage: number;
  cleaning: number;
  pendingReview: number;
  /** 0–1 營運負載。 */
  workload: number;
  statusLabel: string;
  enabled: boolean;
}

/** Simplified Taiwan main-island outline (lng, lat), clockwise from the north tip. */
export const TAIWAN_OUTLINE: LngLat[] = [
  [121.52, 25.3], [121.74, 25.18], [121.95, 25.03], [122.0, 24.9], [121.88, 24.78], [121.84, 24.6], [121.68, 24.45],
  [121.62, 24.2], [121.62, 23.95], [121.52, 23.7], [121.44, 23.4], [121.4, 23.1], [121.3, 22.85], [121.18, 22.65],
  [121.0, 22.35], [120.9, 22.05], [120.86, 21.9], [120.72, 21.95], [120.68, 22.2], [120.6, 22.45], [120.5, 22.6],
  [120.3, 22.7], [120.18, 22.95], [120.1, 23.2], [120.1, 23.5], [120.15, 23.8], [120.3, 24.05], [120.5, 24.3],
  [120.75, 24.6], [120.9, 24.8], [121.0, 24.95], [121.15, 25.08], [121.35, 25.2],
];

/**
 * Stylized elevation peaks: [lng, lat, amplitude, sigma(deg)].
 * Central Mountain Range (irregular, multiple summits), Xueshan NW branch, Alishan,
 * Coastal Range on the east, Yangmingshan in the north. Western plains stay flat.
 */
export const TAIWAN_PEAKS: [number, number, number, number][] = [
  [121.5, 24.72, 0.42, 0.22], [121.36, 24.42, 0.55, 0.2], [121.22, 24.12, 0.62, 0.22], [121.08, 23.78, 0.66, 0.24],
  [120.98, 23.45, 0.64, 0.22], [120.9, 23.12, 0.58, 0.2], [120.82, 22.78, 0.48, 0.2], [120.74, 22.42, 0.34, 0.18], [120.64, 22.1, 0.16, 0.14],
  [121.28, 24.62, 0.4, 0.14], [121.1, 24.38, 0.32, 0.14], [120.8, 23.5, 0.28, 0.12], [121.46, 23.5, 0.14, 0.1], [121.38, 23.15, 0.12, 0.1],
  [121.56, 25.17, 0.14, 0.08], [121.7, 24.9, 0.2, 0.12],
];

/** Workload weight per status for the heatmap. */
export const WORKLOAD_WEIGHT: Record<VehicleStatus, number> = {
  rented: 0.05,
  healthy: 0.05,
  ready: 0.1,
  damage: 1,
  cleaning: 0.6,
  "pending-review": 0.5,
  maintenance: 0.7,
  unavailable: 0.8,
};

/** Status → marker color (kept muted; matches statusMeta dots). */
export const MARKER_COLORS: Record<VehicleStatus, string> = {
  rented: "#818cf8",
  healthy: "#34d399",
  ready: "#5eead4",
  cleaning: "#fbbf24",
  damage: "#fb7185",
  "pending-review": "#a78bfa",
  maintenance: "#fb923c",
  unavailable: "#b45c6a",
};

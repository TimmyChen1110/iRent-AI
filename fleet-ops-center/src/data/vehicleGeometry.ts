import type { HotspotLocation } from "@/types";

/** 3D 車身各區域的標記座標（車頭 +X、右側 +Z）與顯示名稱。 */
export const HOTSPOT_POSITIONS: Record<HotspotLocation, [number, number, number]> = {
  "front-bumper": [2.1, 0.55, 0],
  "rear-bumper": [-2.06, 0.55, 0],
  hood: [1.45, 1.04, 0],
  roof: [-0.4, 1.56, 0],
  "left-front-door": [0.46, 0.76, -0.86],
  "right-front-door": [0.46, 0.76, 0.86],
  "left-rear-door": [-0.6, 0.76, -0.86],
  "right-rear-door": [-0.6, 0.76, 0.86],
  "left-front-fender": [1.5, 0.78, -0.86],
  "right-front-fender": [1.5, 0.78, 0.86],
  "left-rear-quarter": [-1.6, 0.8, -0.84],
  "right-rear-quarter": [-1.6, 0.8, 0.84],
  windshield: [0.86, 1.3, 0],
  interior: [-0.15, 1.0, 0],
  "rear-seat": [-0.85, 0.95, 0.38],
  "cup-holder": [0.12, 0.82, 0],
  "driver-seat": [0.15, 0.98, -0.42],
};

export const INTERIOR_LOCATIONS: HotspotLocation[] = ["interior", "rear-seat", "cup-holder", "driver-seat"];

export const LOCATION_LABELS: Record<HotspotLocation, string> = {
  "front-bumper": "前保桿",
  "rear-bumper": "後保桿",
  hood: "引擎蓋",
  roof: "車頂",
  "left-front-door": "左前車門",
  "right-front-door": "右前車門",
  "left-rear-door": "左後車門",
  "right-rear-door": "右後車門",
  "left-front-fender": "左前葉子板",
  "right-front-fender": "右前葉子板",
  "left-rear-quarter": "左後側板",
  "right-rear-quarter": "右後側板",
  windshield: "擋風玻璃",
  interior: "車內",
  "rear-seat": "後座",
  "cup-holder": "杯架",
  "driver-seat": "駕駛座",
};


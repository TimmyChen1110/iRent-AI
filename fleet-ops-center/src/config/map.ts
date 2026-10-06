/**
 * Map configuration for the Taipei 3D city layer.
 *
 * Uses MapLibre GL JS with OpenFreeMap vector tiles (OpenMapTiles schema, ODbL).
 * No API token is required. If NEXT_PUBLIC_MAPBOX_TOKEN is ever provided it is
 * intentionally NOT required for the build; the app must always run without it.
 */
import type { StyleSpecification } from "maplibre-gl";

export const MAP_TILES_URL = "https://tiles.openfreemap.org/planet";

/** Static MapLibre worker (maplibre-gl-worker.mjs + maplibre-gl-shared.mjs copied from node_modules/maplibre-gl/dist; re-copy after upgrading maplibre-gl). */
export const MAPLIBRE_WORKER_URL = `${process.env.NEXT_PUBLIC_BASE_PATH ?? ""}/maplibre/maplibre-gl-worker.mjs`;

/** Default Taipei camera: Xinyi district, pitched 3D view. */
export const TAIPEI_CAMERA = {
  center: [121.5636, 25.0338] as [number, number],
  zoom: 14.6,
  pitch: 60,
  bearing: -12,
};

/** Individual vehicle markers appear at or above this zoom. */
export const CLUSTER_ZOOM = 14.2;
/** District cluster chips are hidden at or above this zoom (street-level view). */
export const DISTRICT_CHIP_ZOOM = 15.0;

/** Zoom used when flying to a single vehicle. */
export const VEHICLE_FOCUS_ZOOM = 16.6;

const BG = "#0b0e14";
const WATER = "#0e1420";
const LAND = "#10141c";
const PARK = "#121a1a";
const ROAD_MAJOR = "#2a3344";
const ROAD_MINOR = "#1c2230";
const BUILDING = "#1a2030";
const BUILDING_TOP = "#232b3d";

/**
 * Minimal dark "command center" style: water, parks, roads, 3D buildings, boundaries.
 * No POIs / shop labels on purpose (they clutter an operations view).
 */
export const TAIPEI_DARK_STYLE: StyleSpecification = {
  version: 8,
  name: "iRent Ops Dark",
  sources: {
    omt: { type: "vector", url: MAP_TILES_URL },
  },
  layers: [
    { id: "background", type: "background", paint: { "background-color": BG } },
    { id: "land", type: "fill", source: "omt", "source-layer": "landcover", paint: { "fill-color": LAND, "fill-opacity": 0.6 } },
    { id: "park", type: "fill", source: "omt", "source-layer": "park", paint: { "fill-color": PARK, "fill-opacity": 0.8 } },
    { id: "water", type: "fill", source: "omt", "source-layer": "water", paint: { "fill-color": WATER } },
    {
      id: "road-minor",
      type: "line",
      source: "omt",
      "source-layer": "transportation",
      minzoom: 13,
      filter: ["all", ["!in", "class", "motorway", "trunk", "primary", "secondary", "rail", "transit"]],
      paint: { "line-color": ROAD_MINOR, "line-width": ["interpolate", ["linear"], ["zoom"], 13, 0.6, 16, 2.2] },
    },
    {
      id: "road-major",
      type: "line",
      source: "omt",
      "source-layer": "transportation",
      filter: ["in", "class", "motorway", "trunk", "primary", "secondary"],
      paint: { "line-color": ROAD_MAJOR, "line-width": ["interpolate", ["linear"], ["zoom"], 11, 0.8, 14, 2.4, 17, 6] },
    },
    {
      id: "road-major-glow",
      type: "line",
      source: "omt",
      "source-layer": "transportation",
      filter: ["in", "class", "motorway", "trunk", "primary"],
      paint: { "line-color": "#6ea8ff", "line-opacity": 0.12, "line-width": ["interpolate", ["linear"], ["zoom"], 12, 2, 16, 9], "line-blur": 4 },
    },
    {
      id: "buildings-3d",
      type: "fill-extrusion",
      source: "omt",
      "source-layer": "building",
      minzoom: 13,
      paint: {
        "fill-extrusion-color": ["interpolate", ["linear"], ["coalesce", ["get", "render_height"], 10], 0, BUILDING, 60, BUILDING_TOP, 250, "#34405a"],
        "fill-extrusion-height": ["interpolate", ["linear"], ["zoom"], 13, 0, 14.5, ["coalesce", ["get", "render_height"], 10]],
        "fill-extrusion-base": ["coalesce", ["get", "render_min_height"], 0],
        "fill-extrusion-opacity": 0.9,
        "fill-extrusion-vertical-gradient": true,
      },
    },
    {
      id: "boundary",
      type: "line",
      source: "omt",
      "source-layer": "boundary",
      filter: ["<=", "admin_level", 6],
      paint: { "line-color": "#2d3648", "line-width": 1, "line-dasharray": [2, 2] },
    },
  ],
};

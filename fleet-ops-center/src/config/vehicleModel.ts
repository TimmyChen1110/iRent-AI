/**
 * Set to a GLB/GLTF path under /public (e.g. "/models/vehicle.glb") to swap the
 * procedural placeholder for a real model. Null keeps the placeholder.
 */
export const VEHICLE_MODEL_URL: string | null = null;

/** Uniform scale applied to the GLTF so that it roughly matches the placeholder footprint. */
export const MODEL_SCALE = 1;

/** Default camera for the full-vehicle view. */
export const DEFAULT_CAMERA = {
  position: [6.4, 3.0, 6.6] as [number, number, number],
  target: [0, 0.55, 0] as [number, number, number],
};

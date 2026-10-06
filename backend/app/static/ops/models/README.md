# Vehicle 3D model

Drop a free, legally licensed GLB/GLTF car model here (e.g. `vehicle.glb`) and set
`VEHICLE_MODEL_URL = "/models/vehicle.glb"` in `src/config/vehicleModel.ts`.

Until a model is present the app renders a procedural placeholder vehicle, so the
whole system runs without any external asset. Hotspots are 3D-coordinate based and
therefore work with any model as long as it is centered, faces +X and is roughly
4.1 m long (see `MODEL_SCALE` in the same config file).

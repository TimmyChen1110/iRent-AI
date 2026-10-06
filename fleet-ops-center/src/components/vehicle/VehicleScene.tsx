"use client";

import { Suspense, useCallback, useEffect, useMemo, useRef, useState, type RefObject } from "react";
import { Canvas } from "@react-three/fiber";
import { ContactShadows, Environment, Grid, MeshReflectorMaterial, OrbitControls } from "@react-three/drei";
import * as THREE from "three";
import type { OrbitControls as OrbitControlsImpl } from "three-stdlib";
import type { DamageHotspot as Hotspot, HotspotLocation, TwinMode } from "@/types";
import { DEFAULT_CAMERA } from "@/config/vehicleModel";
import { HOTSPOT_POSITIONS, INTERIOR_LOCATIONS } from "@/data/vehicleGeometry";
import { VehicleModel } from "./VehicleModel";
import { DamageHotspot } from "./DamageHotspot";
import { DamageRegion } from "./DamageRegion";
import { CameraRig, focusForPoint, INTERIOR_CAMERA, type CameraFocus } from "./CameraRig";
import { ErrorBoundary } from "./ErrorBoundary";

export interface VehicleSceneProps {
  hotspots: Hotspot[];
  selectedHotspotId: string | null;
  onSelectHotspot: (id: string | null) => void;
  onPickRegion?: (location: HotspotLocation) => void;
  autoRotate: boolean;
  resetToken: number;
  mode: TwinMode;
  tooltipRef?: RefObject<HTMLDivElement | null>;
}

export function VehicleScene({
  hotspots,
  selectedHotspotId,
  onSelectHotspot,
  onPickRegion,
  autoRotate,
  resetToken,
  mode,
  tooltipRef,
}: VehicleSceneProps) {
  const controlsRef = useRef<OrbitControlsImpl | null>(null);
  const animatingRef = useRef(false);
  const [interacting, setInteracting] = useState(false);
  const idleTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const selected = hotspots.find((h) => h.id === selectedHotspotId) ?? null;
  const visible = hotspots.filter((h) => h.mode === mode);

  // Recreated when selection / mode / reset token changes so CameraRig re-animates.
  const focus = useMemo<CameraFocus>(() => {
    if (selected) return focusForPoint(selected.position, selected.mode);
    return mode === "interior" ? INTERIOR_CAMERA : { position: DEFAULT_CAMERA.position, target: DEFAULT_CAMERA.target };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selected?.id, mode, resetToken]);

  const handleStart = useCallback(() => {
    animatingRef.current = false;
    setInteracting(true);
    if (idleTimer.current) clearTimeout(idleTimer.current);
  }, []);
  const handleEnd = useCallback(() => {
    if (idleTimer.current) clearTimeout(idleTimer.current);
    idleTimer.current = setTimeout(() => setInteracting(false), 3500);
  }, []);

  useEffect(() => () => {
    if (idleTimer.current) clearTimeout(idleTimer.current);
  }, []);

  const handlePick = useCallback(
    (point: THREE.Vector3) => {
      if (!onPickRegion) return;
      let best: HotspotLocation = "roof";
      let bestD = Infinity;
      (Object.keys(HOTSPOT_POSITIONS) as HotspotLocation[]).forEach((loc) => {
        const interior = INTERIOR_LOCATIONS.includes(loc);
        if (interior !== (mode === "interior")) return;
        const [x, y, z] = HOTSPOT_POSITIONS[loc];
        const d = point.distanceTo(new THREE.Vector3(x, y, z));
        if (d < bestD) {
          bestD = d;
          best = loc;
        }
      });
      onPickRegion(best);
    },
    [onPickRegion, mode],
  );

  return (
    <Canvas
      shadows
      dpr={[1, 2]}
      camera={{ fov: 34, near: 0.1, far: 100, position: DEFAULT_CAMERA.position }}
      gl={{ antialias: true, alpha: true, toneMapping: THREE.ACESFilmicToneMapping, toneMappingExposure: 1.05 }}
      onPointerMissed={() => onSelectHotspot(null)}
      style={{ background: "transparent" }}
    >
      {/* studio lighting: key / fill / rim / top softbox */}
      <ambientLight intensity={0.3} />
      <hemisphereLight args={["#dbe7ff", "#0b0d12", 0.5]} />
      <directionalLight position={[5, 7, 5]} intensity={2.4} castShadow shadow-mapSize={[2048, 2048]} shadow-bias={-0.0002} />
      <directionalLight position={[-6, 4, -3]} intensity={0.9} color="#9cbcff" />
      <directionalLight position={[-2, 3, 7]} intensity={1.2} color="#ffffff" />
      <spotLight position={[0, 8, 0]} angle={0.7} penumbra={1} intensity={1.8} color="#ffffff" />

      <ErrorBoundary fallback={null}>
        <Suspense fallback={null}>
          <Environment preset="city" environmentIntensity={0.55} />
        </Suspense>
      </ErrorBoundary>

      <group position={[0, -0.02, 0]}>
        <VehicleModel
          onPick={handlePick}
          xray={mode === "interior"}
          dimmed={Boolean(selected)}
          damagedPanels={hotspots.filter((h) => h.kind === "damage").map((h) => ({ location: h.location, selected: h.id === selectedHotspotId }))}
        />
        {visible.map((h) => (
          <group key={h.id}>
            {h.kind === "damage" && <DamageRegion hotspot={h} selected={h.id === selectedHotspotId} />}
            <DamageHotspot
              hotspot={h}
              selected={h.id === selectedHotspotId}
              dimmed={selectedHotspotId !== null && h.id !== selectedHotspotId}
              onSelect={(id) => onSelectHotspot(id)}
              tooltipRef={tooltipRef}
            />
          </group>
        ))}
      </group>

      {/* subtle ground reflection + contact shadow so the car sits on the floor */}
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, -0.005, 0]}>
        <planeGeometry args={[40, 40]} />
        <MeshReflectorMaterial blur={[400, 120]} resolution={1024} mixBlur={1} mixStrength={mode === "interior" ? 0.25 : 0.6} roughness={1} depthScale={1.1} minDepthThreshold={0.4} maxDepthThreshold={1.4} color="#0a0d14" metalness={0.4} mirror={0.35} />
      </mesh>
      <ContactShadows position={[0, 0.002, 0]} opacity={mode === "interior" ? 0.25 : 0.6} scale={12} blur={2.4} far={3} resolution={1024} color="#000000" />
      <Grid
        position={[0, 0.004, 0]}
        args={[30, 30]}
        cellSize={0.5}
        cellThickness={0.5}
        cellColor="#1b2130"
        sectionSize={2.5}
        sectionThickness={0.8}
        sectionColor="#283145"
        fadeDistance={16}
        fadeStrength={1.6}
        infiniteGrid
      />

      <OrbitControls
        ref={controlsRef}
        enablePan={false}
        enableDamping
        dampingFactor={0.08}
        minDistance={2.2}
        maxDistance={11}
        maxPolarAngle={Math.PI / 2 - 0.04}
        minPolarAngle={0.2}
        autoRotate={autoRotate && !interacting && !selected && mode === "exterior"}
        autoRotateSpeed={0.55}
        target={DEFAULT_CAMERA.target}
        onStart={handleStart}
        onEnd={handleEnd}
      />
      <CameraRig controlsRef={controlsRef} focus={focus} animatingRef={animatingRef} />
    </Canvas>
  );
}

export default VehicleScene;

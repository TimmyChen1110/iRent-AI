"use client";

import { Suspense, useMemo } from "react";
import { Line, RoundedBox, useGLTF } from "@react-three/drei";
import { useFrame } from "@react-three/fiber";
import * as THREE from "three";
import { MODEL_SCALE, VEHICLE_MODEL_URL } from "@/config/vehicleModel";
import { ErrorBoundary } from "./ErrorBoundary";
import { CabinInterior } from "./CabinInterior";

export interface VehicleModelProps {
  onPick?: (point: THREE.Vector3) => void;
  /** Interior mode: body becomes a translucent X-ray shell and the cabin is shown. */
  xray?: boolean;
  /** Lower emphasis of the body while a hotspot is focused. */
  dimmed?: boolean;
  /** Panels that carry confirmed/possible damage (tinted + scratch marks). */
  damagedPanels?: { location: string; selected: boolean }[];
}

/**
 * Abstract vehicle model. Renders a GLTF when VEHICLE_MODEL_URL is set and loads,
 * otherwise a procedural compact hatchback (facing +X, right side = +Z, ~4.1 m long).
 */
export function VehicleModel(props: VehicleModelProps) {
  if (!VEHICLE_MODEL_URL) return <ProceduralHatchback {...props} />;
  return (
    <ErrorBoundary fallback={<ProceduralHatchback {...props} />}>
      <Suspense fallback={<ProceduralHatchback {...props} />}>
        <GLTFVehicle url={VEHICLE_MODEL_URL} {...props} />
      </Suspense>
    </ErrorBoundary>
  );
}

function GLTFVehicle({ url, onPick, xray }: VehicleModelProps & { url: string }) {
  const { scene } = useGLTF(url);
  const cloned = useMemo(() => {
    const c = scene.clone(true);
    c.traverse((o) => {
      const mesh = o as THREE.Mesh;
      if (mesh.isMesh && mesh.material) {
        const m = (mesh.material as THREE.Material).clone();
        m.transparent = true;
        mesh.material = m;
      }
    });
    return c;
  }, [scene]);
  useFrame((_, delta) => {
    cloned.traverse((o) => {
      const mesh = o as THREE.Mesh;
      if (mesh.isMesh) {
        const m = mesh.material as THREE.Material;
        m.opacity = THREE.MathUtils.damp(m.opacity, xray ? 0.15 : 1, 6, delta);
        m.depthWrite = !xray;
      }
    });
  });
  return (
    <group>
      <primitive object={cloned} scale={MODEL_SCALE} onPointerDown={(e: { stopPropagation: () => void; point: THREE.Vector3 }) => { e.stopPropagation(); onPick?.(e.point); }} />
      <CabinInterior visible={Boolean(xray)} />
    </group>
  );
}

/* ----------------------------- procedural hatchback ----------------------------- */

/** Side silhouette (x = length, y = height). Rear at -x, front at +x. */
const BODY_PROFILE: [number, number][] = [
  [-1.95, 0.4], [-2.05, 0.6], [-2.04, 0.86], [-1.97, 1.0], [-1.9, 1.1],
  [-1.72, 1.36], [-1.5, 1.44], [-0.7, 1.47], [0.1, 1.45], [0.55, 1.36],
  [0.95, 1.14], [1.3, 1.04], [1.9, 0.96], [2.08, 0.84], [2.1, 0.6],
  [2.0, 0.42], [1.8, 0.36], [-1.78, 0.36],
];
/** Glasshouse silhouette (slightly inset so the glass band reads through the paint). */
const GLASS_PROFILE: [number, number][] = [
  [-1.8, 1.02], [-1.67, 1.33], [-1.48, 1.415], [-0.7, 1.45], [0.1, 1.43], [0.54, 1.335], [0.9, 1.14], [0.9, 1.02],
];
const WIDTH = 1.58;
const BEVEL = 0.1;
const SIDE = WIDTH / 2 + BEVEL; // outer side surface of the un-beveled part (≈ 0.79) + bevel reach
const WHEEL_X = [1.28, -1.28];
const WHEEL_Y = 0.345;
const WHEEL_Z = 0.78;

const PAINT = new THREE.Color("#e7eaf0");
const PAINT_DIM = new THREE.Color("#b7bcc6");
const DAMAGE_TINT = new THREE.Color("#e8a7ad");

function profileShape(points: [number, number][]) {
  const s = new THREE.Shape();
  points.forEach(([x, y], i) => (i === 0 ? s.moveTo(x, y) : s.lineTo(x, y)));
  s.closePath();
  return s;
}

/** Scratch marks for the right rear door (slightly irregular polylines on the panel surface). */
const SCRATCHES: [number, number, number][][] = [
  [[-0.78, 0.8, 0], [-0.62, 0.78, 0], [-0.47, 0.775, 0]],
  [[-0.72, 0.74, 0], [-0.58, 0.73, 0], [-0.5, 0.715, 0]],
  [[-0.66, 0.69, 0], [-0.56, 0.69, 0]],
];

function ProceduralHatchback({ onPick, xray, dimmed, damagedPanels = [] }: VehicleModelProps) {
  const mats = useMemo(() => {
    const paint = () => new THREE.MeshPhysicalMaterial({ color: PAINT.clone(), roughness: 0.22, metalness: 0.18, clearcoat: 1, clearcoatRoughness: 0.06, envMapIntensity: 1.2, transparent: true, sheen: 0.2, sheenColor: new THREE.Color("#cfd6e6") });
    return {
      body: paint(),
      doorFR: paint(), doorRR: paint(), doorFL: paint(), doorRL: paint(),
      glass: new THREE.MeshPhysicalMaterial({ color: "#1a2230", roughness: 0.05, metalness: 0.2, clearcoat: 1, transparent: true, opacity: 0.88, envMapIntensity: 1.4 }),
      trim: new THREE.MeshStandardMaterial({ color: "#14171d", roughness: 0.85, metalness: 0.1, transparent: true }),
      chrome: new THREE.MeshStandardMaterial({ color: "#c9ced8", roughness: 0.22, metalness: 0.95, transparent: true }),
      tire: new THREE.MeshStandardMaterial({ color: "#101216", roughness: 0.92, metalness: 0, transparent: true }),
      rim: new THREE.MeshStandardMaterial({ color: "#aab1bd", roughness: 0.3, metalness: 0.9, transparent: true }),
      headlight: new THREE.MeshStandardMaterial({ color: "#e8f1ff", emissive: "#bcd4ff", emissiveIntensity: 1.1, roughness: 0.15, transparent: true }),
      taillight: new THREE.MeshStandardMaterial({ color: "#c81e34", emissive: "#ff2e45", emissiveIntensity: 0.9, roughness: 0.25, transparent: true }),
      indicator: new THREE.MeshStandardMaterial({ color: "#f5b24a", emissive: "#f59e0b", emissiveIntensity: 0.5, roughness: 0.3, transparent: true }),
    };
  }, []);

  const bodyGeo = useMemo(() => new THREE.ExtrudeGeometry(profileShape(BODY_PROFILE), { depth: WIDTH, bevelEnabled: true, bevelThickness: BEVEL, bevelSize: 0.09, bevelSegments: 6, curveSegments: 12 }), []);
  const glassGeo = useMemo(() => new THREE.ExtrudeGeometry(profileShape(GLASS_PROFILE), { depth: WIDTH + 2 * BEVEL + 0.02, bevelEnabled: true, bevelThickness: 0.02, bevelSize: 0.02, bevelSegments: 2, curveSegments: 8 }), []);

  const rrDamaged = damagedPanels.find((p) => p.location === "right-rear-door");

  useFrame((_, delta) => {
    const k = 1 - Math.exp(-6 * delta);
    const xrayOpacity = (full: number, ghost: number) => (xray ? ghost : full);
    for (const [name, m] of Object.entries(mats)) {
      const target =
        name === "glass" ? xrayOpacity(0.88, 0.05) : name === "tire" || name === "rim" ? xrayOpacity(1, 0.22) : name === "trim" || name === "chrome" ? xrayOpacity(1, 0.15) : name === "headlight" || name === "taillight" || name === "indicator" ? xrayOpacity(1, 0.25) : xrayOpacity(1, 0.1);
      m.opacity += (target - m.opacity) * k;
      m.depthWrite = !xray;
    }
    const baseTarget = dimmed && !xray ? PAINT_DIM : PAINT;
    for (const name of ["body", "doorFR", "doorFL", "doorRL"] as const) mats[name].color.lerp(baseTarget, k);
    const rrTarget = rrDamaged ? (rrDamaged.selected ? DAMAGE_TINT : PAINT.clone().lerp(DAMAGE_TINT, 0.45)) : baseTarget;
    mats.doorRR.color.lerp(rrTarget, k);
  });

  return (
    <group onPointerDown={(e) => { e.stopPropagation(); onPick?.(e.point); }}>
      {/* main body: extruded side silhouette, rounded edges */}
      <mesh geometry={bodyGeo} material={mats.body} position={[0, 0, -WIDTH / 2]} castShadow receiveShadow />
      {/* glasshouse band (reads through paint as dark glass) */}
      <mesh geometry={glassGeo} material={mats.glass} position={[0, 0, -(WIDTH + 2 * BEVEL + 0.02) / 2]} />
      {/* windshield + rear glass surfaces */}
      <mesh position={[0.76, 1.26, 0]} rotation={[0, 0, 0.5]} material={mats.glass}>
        <boxGeometry args={[0.02, 0.5, 1.5]} />
      </mesh>
      <mesh position={[-1.8, 1.2, 0]} rotation={[0, 0, -0.9]} material={mats.glass}>
        <boxGeometry args={[0.02, 0.5, 1.42]} />
      </mesh>
      {/* B-pillar divider inside the glass band */}
      {[1, -1].map((sd) => (
        <mesh key={sd} position={[-0.2, 1.22, sd * (SIDE + 0.09)]} material={mats.trim}><boxGeometry args={[0.05, 0.36, 0.02]} /></mesh>
      ))}
      {/* shark-fin antenna */}
      <mesh position={[-1.15, 1.47, 0]} rotation={[0, 0, 0.25]} material={mats.trim}><boxGeometry args={[0.14, 0.06, 0.03]} /></mesh>

      {/* door panels (separate meshes so damage can tint the right rear door) */}
      <DoorPanel x={0.46} z={SIDE - 0.065} material={mats.doorFR} />
      <DoorPanel x={-0.58} z={SIDE - 0.065} material={mats.doorRR} />
      <DoorPanel x={0.46} z={-(SIDE - 0.065)} material={mats.doorFL} />
      <DoorPanel x={-0.58} z={-(SIDE - 0.065)} material={mats.doorRL} />
      {/* door seams */}
      {[1.0, -0.06, -1.12].map((x) => (
        <group key={x}>
          <mesh position={[x, 0.76, SIDE - 0.028]} material={mats.trim}><boxGeometry args={[0.012, 0.64, 0.012]} /></mesh>
          <mesh position={[x, 0.76, -(SIDE - 0.028)]} material={mats.trim}><boxGeometry args={[0.012, 0.64, 0.012]} /></mesh>
        </group>
      ))}
      {/* door handles */}
      {[0.6, -0.42].map((x) => (
        <group key={x}>
          <mesh position={[x, 0.86, SIDE - 0.01]} material={mats.chrome}><boxGeometry args={[0.17, 0.035, 0.03]} /></mesh>
          <mesh position={[x, 0.86, -(SIDE - 0.01)]} material={mats.chrome}><boxGeometry args={[0.17, 0.035, 0.03]} /></mesh>
        </group>
      ))}
      {/* side character line */}
      {[1, -1].map((s) => (
        <mesh key={s} position={[0.05, 0.98, s * (SIDE - 0.02)]} material={mats.chrome}><boxGeometry args={[3.5, 0.006, 0.006]} /></mesh>
      ))}

      {/* scratch marks on the right rear door */}
      {rrDamaged && SCRATCHES.map((pts, i) => (
        <Line key={i} points={pts.map(([x, y]) => [x, y, SIDE + 0.004] as [number, number, number])} color="#4a2126" lineWidth={1.3} transparent opacity={xray ? 0.1 : 0.9} />
      ))}

      {/* mirrors */}
      {[1, -1].map((s) => (
        <group key={s} position={[0.98, 1.08, s * (SIDE + 0.06)]}>
          <mesh material={mats.trim}><boxGeometry args={[0.06, 0.03, 0.12]} /></mesh>
          <RoundedBox args={[0.18, 0.11, 0.14]} radius={0.03} position={[-0.02, 0.02, s * 0.1]} material={mats.body} />
        </group>
      ))}

      {/* front: grille, bumper trim, headlights, indicators */}
      <mesh position={[2.09, 0.62, 0]} material={mats.trim}><boxGeometry args={[0.04, 0.2, 1.0]} /></mesh>
      <RoundedBox args={[0.08, 0.14, 1.9]} radius={0.03} position={[2.06, 0.44, 0]} material={mats.trim} />
      {[1, -1].map((s) => (
        <group key={s}>
          <mesh position={[2.0, 0.9, s * 0.56]} rotation={[0, s * 0.35, 0]} material={mats.headlight}><boxGeometry args={[0.05, 0.11, 0.42]} /></mesh>
          <mesh position={[2.02, 0.74, s * 0.78]} material={mats.indicator}><boxGeometry args={[0.03, 0.05, 0.14]} /></mesh>
        </group>
      ))}
      {/* rear: taillights wrapping the corners, bumper trim, plate recess */}
      {[1, -1].map((s) => (
        <group key={s}>
          <mesh position={[-2.03, 0.94, s * 0.6]} rotation={[0, -s * 0.3, 0]} material={mats.taillight}><boxGeometry args={[0.05, 0.12, 0.44]} /></mesh>
          <mesh position={[-1.93, 0.96, s * (SIDE - 0.02)]} material={mats.taillight}><boxGeometry args={[0.18, 0.1, 0.03]} /></mesh>
        </group>
      ))}
      <RoundedBox args={[0.08, 0.14, 1.9]} radius={0.03} position={[-2.04, 0.44, 0]} material={mats.trim} />
      <mesh position={[-2.07, 0.72, 0]} material={mats.trim}><boxGeometry args={[0.02, 0.12, 0.36]} /></mesh>
      {/* lower sill */}
      <mesh position={[0, 0.37, 0]} material={mats.trim}><boxGeometry args={[3.5, 0.08, WIDTH + 0.16]} /></mesh>

      {/* wheels + arches */}
      {WHEEL_X.map((x) => [1, -1].map((s) => <Wheel key={`${x}-${s}`} x={x} z={s * WHEEL_Z} side={s} mats={mats} />))}

      <CabinInterior visible={Boolean(xray)} />
    </group>
  );
}

function DoorPanel({ x, z, material }: { x: number; z: number; material: THREE.Material }) {
  return <RoundedBox args={[1.0, 0.58, 0.03]} radius={0.02} smoothness={3} position={[x, 0.7, z]} material={material} castShadow />;
}

function Wheel({ x, z, side, mats }: { x: number; z: number; side: number; mats: Record<string, THREE.Material> }) {
  return (
    <group position={[x, WHEEL_Y, z]}>
      {/* wheel-well recess (dark disc behind the tire) + arch flare over the top half */}
      <mesh position={[0, 0.02, -side * 0.12]} rotation={[Math.PI / 2, 0, 0]} material={mats.trim}>
        <cylinderGeometry args={[0.42, 0.42, 0.26, 32]} />
      </mesh>
      <mesh position={[0, 0.02, side * 0.03]} material={mats.trim}>
        <torusGeometry args={[0.44, 0.04, 10, 40, Math.PI]} />
      </mesh>
      {/* tire */}
      <group rotation={[Math.PI / 2, 0, 0]}>
        <mesh material={mats.tire} castShadow><cylinderGeometry args={[0.345, 0.345, 0.22, 48]} /></mesh>
        <mesh material={mats.tire} position={[0, side * 0.11, 0]} rotation={[Math.PI / 2, 0, 0]}><torusGeometry args={[0.3, 0.05, 12, 48]} /></mesh>
        {/* rim face + spokes + hub */}
        <mesh material={mats.rim} position={[0, side * 0.06, 0]}><cylinderGeometry args={[0.24, 0.24, 0.1, 32]} /></mesh>
        <mesh material={mats.trim} position={[0, side * 0.085, 0]}><cylinderGeometry args={[0.2, 0.2, 0.06, 32]} /></mesh>
        {[0, 1, 2, 3, 4].map((i) => (
          <mesh key={i} material={mats.rim} position={[0, side * 0.115, 0]} rotation={[0, (i / 5) * Math.PI * 2, 0]}>
            <boxGeometry args={[0.38, 0.03, 0.06]} />
          </mesh>
        ))}
        <mesh material={mats.chrome} position={[0, side * 0.125, 0]}><cylinderGeometry args={[0.05, 0.05, 0.03, 16]} /></mesh>
      </group>
    </group>
  );
}

if (VEHICLE_MODEL_URL) useGLTF.preload(VEHICLE_MODEL_URL);

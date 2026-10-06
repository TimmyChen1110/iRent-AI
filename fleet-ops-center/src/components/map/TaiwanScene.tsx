"use client";
/* eslint-disable react-hooks/immutability -- Three.js objects are mutated per frame in useFrame (standard R3F pattern) */

import { useEffect, useMemo, useRef, useState, type RefObject } from "react";
import { Canvas, useFrame, useThree } from "@react-three/fiber";
import { OrbitControls, Line } from "@react-three/drei";
import * as THREE from "three";
import type { OrbitControls as OrbitControlsImpl } from "three-stdlib";
import { TAIWAN_OUTLINE, TAIWAN_PEAKS, type CityNode, type LngLat } from "@/data/fleetMapData";

/** lng/lat → scene units (north = -z, east = +x). */
export function projectLngLat([lng, lat]: LngLat): [number, number, number] {
  return [(lng - 121.0) * 2.2 * 0.92, 0, -(lat - 23.7) * 2.2];
}

const DEFAULT_POS = new THREE.Vector3(3.2, 5.4, 7.0);
const DEFAULT_TARGET = new THREE.Vector3(0.3, 0, 0.2);

function nodeColor(workload: number) {
  return workload >= 0.8 ? "#fb7185" : workload >= 0.45 ? "#fbbf24" : "#6ea8ff";
}

export interface TaiwanSceneProps {
  cities: CityNode[];
  hovered: string | null;
  onHover: (id: string | null) => void;
  onSelect: (id: CityNode["id"]) => void;
  /** City id the camera should fly to (null = default view). */
  focusCity: CityNode["id"] | null;
  resetToken: number;
  labelRefs: RefObject<Record<string, HTMLDivElement | null>>;
}

export function TaiwanScene(props: TaiwanSceneProps) {
  return (
    <Canvas dpr={[1, 2]} camera={{ fov: 38, near: 0.1, far: 100, position: DEFAULT_POS.toArray() }} gl={{ antialias: true, alpha: true, toneMapping: THREE.ACESFilmicToneMapping }} style={{ background: "transparent" }}>
      <fog attach="fog" args={["#07090d", 9, 22]} />
      <ambientLight intensity={0.5} />
      <hemisphereLight args={["#b9d2ff", "#06080c", 0.6]} />
      <directionalLight position={[-3, 6, 4]} intensity={1.7} />
      <directionalLight position={[-5, 4, -4]} intensity={0.5} color="#6ea8ff" />
      <Island />
      {props.cities.map((c) => (
        <CityMarker key={c.id} city={c} hovered={props.hovered === c.id} onHover={props.onHover} onSelect={props.onSelect} labelRefs={props.labelRefs} />
      ))}
      <gridHelper args={[40, 40, "#141a26", "#10151f"]} position={[0, -0.02, 0]} />
      <Rig {...props} />
    </Canvas>
  );
}

function shapeFrom(points: LngLat[]) {
  const shape = new THREE.Shape();
  points.forEach((ll, i) => {
    const [x, , z] = projectLngLat(ll);
    // Shape is built in XY then rotated to lie flat: use (x, -z) so north stays north.
    if (i === 0) shape.moveTo(x, -z);
    else shape.lineTo(x, -z);
  });
  shape.closePath();
  return shape;
}

const PLATE_TOP = 0.05;

/* ---- terrain helpers (lng/lat space) ---- */
function pointInPolygon(lng: number, lat: number, poly: LngLat[]) {
  let inside = false;
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    const [xi, yi] = poly[i];
    const [xj, yj] = poly[j];
    if (yi > lat !== yj > lat && lng < ((xj - xi) * (lat - yi)) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
}
function distToPolygon(lng: number, lat: number, poly: LngLat[]) {
  let best = Infinity;
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    const [x1, y1] = poly[j];
    const [x2, y2] = poly[i];
    const dx = x2 - x1;
    const dy = y2 - y1;
    const t = Math.max(0, Math.min(1, ((lng - x1) * dx + (lat - y1) * dy) / (dx * dx + dy * dy || 1)));
    const ex = x1 + t * dx - lng;
    const ey = y1 + t * dy - lat;
    best = Math.min(best, Math.sqrt(ex * ex + ey * ey));
  }
  return best;
}
/** Stylized elevation: gaussian peaks along the Central Range + gentle undulation, flattened toward the coast. */
function elevationAt(lng: number, lat: number) {
  let e = 0;
  for (const [plng, plat, amp, sigma] of TAIWAN_PEAKS) {
    const dx = (lng - plng) * 0.92;
    const dy = lat - plat;
    e += amp * Math.exp(-(dx * dx + dy * dy) / (2 * sigma * sigma));
  }
  e += 0.025 * Math.sin(lng * 9.5) * Math.cos(lat * 8.2) + 0.015 * Math.sin(lng * 17 + lat * 6);
  const coast = distToPolygon(lng, lat, TAIWAN_OUTLINE);
  const falloff = THREE.MathUtils.smoothstep(coast, 0, 0.16);
  return Math.max(0, e) * falloff;
}

/** Heightfield terrain clipped to the island, with topographic vertex shading and faint contour bands. */
function useTerrainGeometry() {
  return useMemo(() => {
    const LNG0 = 119.95, LNG1 = 122.15, LAT0 = 21.75, LAT1 = 25.45;
    const NX = 110, NY = 170;
    const [x0, , z0] = projectLngLat([LNG0, LAT1]);
    const [x1, , z1] = projectLngLat([LNG1, LAT0]);
    const geo = new THREE.PlaneGeometry(x1 - x0, z1 - z0, NX, NY);
    geo.rotateX(-Math.PI / 2);
    geo.translate((x0 + x1) / 2, 0, (z0 + z1) / 2);
    const pos = geo.attributes.position as THREE.BufferAttribute;
    const colors = new Float32Array(pos.count * 3);
    const low = new THREE.Color("#1a2234");
    const mid = new THREE.Color("#2b3852");
    const high = new THREE.Color("#55637f");
    const c = new THREE.Color();
    let maxE = 0;
    const elev = new Float32Array(pos.count);
    for (let i = 0; i < pos.count; i++) {
      const x = pos.getX(i);
      const z = pos.getZ(i);
      const lng = x / (2.2 * 0.92) + 121.0;
      const lat = -z / 2.2 + 23.7;
      const inside = pointInPolygon(lng, lat, TAIWAN_OUTLINE);
      const e = inside ? elevationAt(lng, lat) : 0;
      elev[i] = e;
      maxE = Math.max(maxE, e);
      // Lowland sits a hair under the plate so only real relief rises above the coastline.
      pos.setY(i, inside ? PLATE_TOP - 0.006 + e * 0.5 : -0.03);
    }
    for (let i = 0; i < pos.count; i++) {
      const t = Math.min(1, elev[i] / Math.max(maxE, 0.001));
      if (t < 0.5) c.copy(low).lerp(mid, t * 2);
      else c.copy(mid).lerp(high, (t - 0.5) * 2);
      colors[i * 3] = c.r;
      colors[i * 3 + 1] = c.g;
      colors[i * 3 + 2] = c.b;
    }
    geo.setAttribute("color", new THREE.BufferAttribute(colors, 3));
    geo.computeVertexNormals();
    return geo;
  }, []);
}

function Island() {
  const plate = useMemo(() => new THREE.ExtrudeGeometry(shapeFrom(TAIWAN_OUTLINE), { depth: PLATE_TOP, bevelEnabled: false, curveSegments: 8 }), []);
  const terrain = useTerrainGeometry();
  const outline = useMemo(() => TAIWAN_OUTLINE.concat([TAIWAN_OUTLINE[0]]).map((ll) => { const [x, , z] = projectLngLat(ll); return [x, PLATE_TOP + 0.02, z] as [number, number, number]; }), []);
  return (
    <group>
      {/* thin coastal plate keeps the coastline crisp */}
      <mesh geometry={plate} rotation={[-Math.PI / 2, 0, 0]}>
        <meshStandardMaterial color="#1a2234" roughness={0.9} metalness={0.05} />
      </mesh>
      {/* terrain heightfield (outside-island vertices are sunk below the ocean plate) */}
      <mesh geometry={terrain} position={[0, 0.002, 0]}>
        <meshStandardMaterial vertexColors roughness={0.85} metalness={0.05} flatShading={false} />
      </mesh>
      <Line points={outline} color="#5b7aa6" lineWidth={1.1} transparent opacity={0.85} />
      {/* ocean plate */}
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0.3, -0.01, 0.3]}>
        <circleGeometry args={[7.5, 64]} />
        <meshBasicMaterial color="#0c1322" transparent opacity={0.92} />
      </mesh>
    </group>
  );
}

function CityMarker({ city, hovered, onHover, onSelect, labelRefs }: { city: CityNode; hovered: boolean; onHover: (id: string | null) => void; onSelect: (id: CityNode["id"]) => void; labelRefs: RefObject<Record<string, HTMLDivElement | null>> }) {
  const [x, , z] = projectLngLat(city.lngLat);
  const color = nodeColor(city.workload);
  const height = 0.22 + city.workload * 0.48;
  const column = useRef<THREE.Mesh>(null);
  const ring = useRef<THREE.Mesh>(null);
  const light = useRef<THREE.PointLight>(null);
  const v = useMemo(() => new THREE.Vector3(), []);

  useFrame(({ clock, camera, size }) => {
    const t = clock.getElapsedTime();
    if (ring.current) {
      const p = (t * 0.6 + city.workload) % 1;
      ring.current.scale.setScalar(0.5 + p * 1.6);
      (ring.current.material as THREE.MeshBasicMaterial).opacity = (1 - p) * (city.workload >= 0.8 ? 0.55 : 0.3);
    }
    if (column.current) column.current.scale.y = THREE.MathUtils.damp(column.current.scale.y, hovered ? 1.15 : 1, 8, 0.016);
    if (light.current) light.current.intensity = 0.8 + Math.sin(t * 2 + city.workload * 6) * 0.25 + (hovered ? 0.8 : 0);
    const el = labelRefs.current?.[city.id];
    if (el) {
      v.set(x, 0.3 + height + 0.06, z).project(camera);
      el.style.transform = `translate(-50%, -100%) translate(${(((v.x + 1) / 2) * size.width).toFixed(1)}px, ${(((1 - v.y) / 2) * size.height).toFixed(1)}px)`;
    }
  });

  return (
    <group position={[x, 0.3, z]}>
      <mesh ref={ring} rotation={[-Math.PI / 2, 0, 0]} position={[0, 0.02, 0]}>
        <ringGeometry args={[0.13, 0.16, 48]} />
        <meshBasicMaterial color={color} transparent opacity={0.4} depthWrite={false} side={THREE.DoubleSide} />
      </mesh>
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, 0.015, 0]}>
        <circleGeometry args={[0.07, 32]} />
        <meshBasicMaterial color={color} transparent opacity={0.55} />
      </mesh>
      <mesh
        ref={column}
        position={[0, height / 2, 0]}
        onPointerOver={(e) => { e.stopPropagation(); onHover(city.id); document.body.style.cursor = city.enabled ? "pointer" : "default"; }}
        onPointerOut={() => { onHover(null); document.body.style.cursor = "auto"; }}
        onClick={(e) => { e.stopPropagation(); onSelect(city.id); }}
      >
        <cylinderGeometry args={[0.022, 0.034, height, 16]} />
        <meshStandardMaterial color={color} emissive={color} emissiveIntensity={hovered ? 2.2 : 1.4} transparent opacity={0.85} />
      </mesh>
      {/* node at the top of the beam */}
      <mesh position={[0, height, 0]}>
        <sphereGeometry args={[0.05, 16, 16]} />
        <meshStandardMaterial color={color} emissive={color} emissiveIntensity={2} />
      </mesh>
      {/* bigger hit area */}
      <mesh position={[0, height / 2, 0]} onPointerOver={(e) => { e.stopPropagation(); onHover(city.id); }} onClick={(e) => { e.stopPropagation(); onSelect(city.id); }}>
        <cylinderGeometry args={[0.25, 0.25, height + 0.3, 8]} />
        <meshBasicMaterial transparent opacity={0} depthWrite={false} />
      </mesh>
      <pointLight ref={light} color={color} intensity={0.8} distance={1.8} decay={2} position={[0, height * 0.7, 0]} />
    </group>
  );
}

function Rig({ focusCity, cities, resetToken }: TaiwanSceneProps) {
  const controls = useRef<OrbitControlsImpl | null>(null);
  const { camera } = useThree();
  const goalPos = useRef(DEFAULT_POS.clone());
  const goalTarget = useRef(DEFAULT_TARGET.clone());
  const animating = useRef(false);
  const [interacting, setInteracting] = useState(false);

  useEffect(() => {
    const city = focusCity ? cities.find((c) => c.id === focusCity) : null;
    if (city) {
      const [x, , z] = projectLngLat(city.lngLat);
      goalPos.current.set(x + 0.8, 1.3, z + 1.2);
      goalTarget.current.set(x, 0.3, z);
    } else {
      goalPos.current.copy(DEFAULT_POS);
      goalTarget.current.copy(DEFAULT_TARGET);
    }
    animating.current = true;
  }, [focusCity, cities, resetToken]);

  useFrame((_, delta) => {
    if (!animating.current || !controls.current) return;
    const k = 1 - Math.exp(-delta * 3.8);
    camera.position.lerp(goalPos.current, k);
    controls.current.target.lerp(goalTarget.current, k);
    controls.current.update();
    if (camera.position.distanceTo(goalPos.current) < 0.02) animating.current = false;
  });

  return (
    <OrbitControls
      ref={controls}
      enablePan={false}
      enableDamping
      minDistance={2}
      maxDistance={14}
      maxPolarAngle={Math.PI / 2 - 0.15}
      autoRotate={!interacting && !focusCity}
      autoRotateSpeed={0.22}
      target={DEFAULT_TARGET}
      onStart={() => { animating.current = false; setInteracting(true); }}
      onEnd={() => setTimeout(() => setInteracting(false), 4000)}
    />
  );
}

export default TaiwanScene;

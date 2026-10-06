"use client";

import { useMemo, useRef } from "react";
import { useFrame } from "@react-three/fiber";
import { RoundedBox } from "@react-three/drei";
import * as THREE from "three";

/**
 * Simplified cabin volume for Interior inspection mode: floor, two front seats,
 * rear bench, dashboard, center console with cup holder, steering wheel.
 * Fades in/out so the Exterior → Interior transition is smooth.
 */
export function CabinInterior({ visible }: { visible: boolean }) {
  const seat = useMemo(() => new THREE.MeshStandardMaterial({ color: "#2b3140", roughness: 0.9, transparent: true, opacity: 0 }), []);
  const dash = useMemo(() => new THREE.MeshStandardMaterial({ color: "#1c2029", roughness: 0.7, metalness: 0.2, transparent: true, opacity: 0 }), []);
  const floor = useMemo(() => new THREE.MeshStandardMaterial({ color: "#151922", roughness: 1, transparent: true, opacity: 0 }), []);
  const accent = useMemo(() => new THREE.MeshStandardMaterial({ color: "#3b4457", roughness: 0.6, metalness: 0.3, transparent: true, opacity: 0 }), []);
  const group = useRef<THREE.Group>(null);

  useFrame((_, delta) => {
    const target = visible ? 1 : 0;
    for (const m of [seat, dash, floor, accent]) m.opacity = THREE.MathUtils.damp(m.opacity, target, 6, delta);
    if (group.current) group.current.visible = seat.opacity > 0.02;
  });

  return (
    <group ref={group} visible={false}>
      {/* floor */}
      <mesh position={[-0.2, 0.5, 0]} material={floor}>
        <boxGeometry args={[2.9, 0.04, 1.5]} />
      </mesh>
      {/* front seats */}
      <Seat x={0.15} z={-0.42} seat={seat} accent={accent} />
      <Seat x={0.15} z={0.42} seat={seat} accent={accent} />
      {/* rear bench */}
      <Seat x={-0.85} z={0} w={1.35} seat={seat} accent={accent} />
      {/* dashboard */}
      <RoundedBox args={[0.45, 0.32, 1.5]} radius={0.06} position={[0.95, 0.92, 0]} material={dash} />
      {/* center console + cup holder */}
      <RoundedBox args={[0.9, 0.2, 0.3]} radius={0.05} position={[0.25, 0.7, 0]} material={dash} />
      <mesh position={[0.12, 0.81, 0]} rotation={[Math.PI / 2, 0, 0]} material={accent}>
        <ringGeometry args={[0.05, 0.08, 24]} />
      </mesh>
      {/* steering wheel */}
      <mesh position={[0.72, 1.02, -0.42]} rotation={[0, 0, Math.PI / 2 - 0.4]} material={accent}>
        <torusGeometry args={[0.16, 0.025, 12, 32]} />
      </mesh>
    </group>
  );
}

function Seat({ x, z, w = 0.5, seat, accent }: { x: number; z: number; w?: number; seat: THREE.Material; accent: THREE.Material }) {
  return (
    <group position={[x, 0, z]}>
      <RoundedBox args={[0.55, 0.16, w]} radius={0.05} position={[0, 0.74, 0]} material={seat} />
      <RoundedBox args={[0.16, 0.5, w]} radius={0.05} position={[-0.24, 1.0, 0]} rotation={[0, 0, 0.18]} material={seat} />
      <RoundedBox args={[0.18, 0.12, w * 0.5]} radius={0.04} position={[-0.3, 1.3, 0]} material={accent} />
    </group>
  );
}

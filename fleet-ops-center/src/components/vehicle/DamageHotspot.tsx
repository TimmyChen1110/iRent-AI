"use client";

import { useRef, useState, type RefObject } from "react";
import { useFrame } from "@react-three/fiber";
import { Billboard } from "@react-three/drei";
import * as THREE from "three";
import type { DamageHotspot as Hotspot } from "@/types";

const COLORS = {
  damage: { core: "#ff4d5e", glow: "#ff3b4a" },
  cleaning: { core: "#ffb648", glow: "#ff9f1c" },
};

export function DamageHotspot({
  hotspot,
  selected,
  dimmed,
  onSelect,
  tooltipRef,
}: {
  hotspot: Hotspot;
  selected: boolean;
  dimmed: boolean;
  onSelect: (id: string) => void;
  /** DOM tooltip living outside the canvas; positioned here by projecting the hotspot. */
  tooltipRef?: RefObject<HTMLDivElement | null>;
}) {
  const [hovered, setHovered] = useState(false);
  const ring1 = useRef<THREE.Mesh>(null);
  const ring2 = useRef<THREE.Mesh>(null);
  const core = useRef<THREE.Mesh>(null);
  const glow = useRef<THREE.Mesh>(null);
  const light = useRef<THREE.PointLight>(null);
  const color = COLORS[hotspot.kind];

  const projected = useRef(new THREE.Vector3());

  useFrame(({ clock, camera, size }) => {
    const t = clock.getElapsedTime();
    if (tooltipRef?.current && (hovered || selected)) {
      projected.current.set(hotspot.position[0], hotspot.position[1] + 0.18, hotspot.position[2]).project(camera);
      const x = ((projected.current.x + 1) / 2) * size.width;
      const y = ((1 - projected.current.y) / 2) * size.height;
      const el = tooltipRef.current;
      el.style.transform = `translate(-50%, -100%) translate(${x.toFixed(1)}px, ${y.toFixed(1)}px)`;
      el.style.opacity = projected.current.z < 1 ? "1" : "0";
      el.dataset.kind = hotspot.kind;
      el.textContent = `${hotspot.label} · ${Math.round(hotspot.confidence * 100)}%`;
    }
    const speed = selected ? 1.6 : 1.1;
    const p1 = (t * speed) % 1;
    const p2 = ((t * speed) + 0.5) % 1;
    if (ring1.current) {
      ring1.current.scale.setScalar(0.6 + p1 * 1.6);
      (ring1.current.material as THREE.MeshBasicMaterial).opacity = (1 - p1) * 0.7;
    }
    if (ring2.current) {
      ring2.current.scale.setScalar(0.6 + p2 * 1.6);
      (ring2.current.material as THREE.MeshBasicMaterial).opacity = (1 - p2) * 0.5;
    }
    if (core.current) {
      const target = hovered || selected ? 1.35 : 1;
      core.current.scale.lerp(new THREE.Vector3(target, target, target), 0.15);
    }
    if (glow.current) {
      const m = glow.current.material as THREE.MeshBasicMaterial;
      m.opacity = selected ? 0.09 + Math.sin(t * 3) * 0.03 : 0;
    }
    if (light.current) light.current.intensity = selected ? 2.2 + Math.sin(t * 3) * 0.6 : 0;
  });

  return (
    <group position={hotspot.position}>
      {/* subtle area glow on the panel */}
      <mesh ref={glow}>
        <sphereGeometry args={[0.3, 24, 24]} />
        <meshBasicMaterial color={color.glow} transparent opacity={0} blending={THREE.AdditiveBlending} depthWrite={false} />
      </mesh>
      <pointLight ref={light} color={color.glow} intensity={0} distance={1.6} decay={2} />

      <Billboard>
        <mesh ref={ring1}>
          <ringGeometry args={[0.1, 0.125, 40]} />
          <meshBasicMaterial color={color.core} transparent opacity={0.6} side={THREE.DoubleSide} depthWrite={false} />
        </mesh>
        <mesh ref={ring2}>
          <ringGeometry args={[0.1, 0.125, 40]} />
          <meshBasicMaterial color={color.core} transparent opacity={0.4} side={THREE.DoubleSide} depthWrite={false} />
        </mesh>
      </Billboard>

      <mesh
        ref={core}
        onPointerOver={(e) => {
          e.stopPropagation();
          setHovered(true);
          document.body.style.cursor = "pointer";
        }}
        onPointerOut={() => {
          setHovered(false);
          document.body.style.cursor = "auto";
          if (!selected && tooltipRef?.current) tooltipRef.current.style.opacity = "0";
        }}
        onClick={(e) => {
          e.stopPropagation();
          onSelect(hotspot.id);
        }}
      >
        <sphereGeometry args={[0.075, 24, 24]} />
        <meshStandardMaterial
          color={color.core}
          emissive={color.glow}
          emissiveIntensity={selected ? 2.4 : dimmed ? 0.6 : 1.4}
          transparent
          opacity={dimmed ? 0.5 : 1}
        />
      </mesh>
      {/* larger invisible hit target */}
      <mesh
        onPointerOver={(e) => {
          e.stopPropagation();
          setHovered(true);
          document.body.style.cursor = "pointer";
        }}
        onPointerOut={() => {
          setHovered(false);
          document.body.style.cursor = "auto";
          if (!selected && tooltipRef?.current) tooltipRef.current.style.opacity = "0";
        }}
        onClick={(e) => {
          e.stopPropagation();
          onSelect(hotspot.id);
        }}
      >
        <sphereGeometry args={[0.2, 12, 12]} />
        <meshBasicMaterial transparent opacity={0} depthWrite={false} />
      </mesh>

    </group>
  );
}

"use client";

import { useMemo, useRef } from "react";
import { useFrame } from "@react-three/fiber";
import * as THREE from "three";
import type { DamageHotspot } from "@/types";

/**
 * Translucent "decal" that highlights the panel area around a damage hotspot.
 * Oriented by the panel normal inferred from the hotspot position (side / end / top).
 */
export function DamageRegion({ hotspot, selected }: { hotspot: DamageHotspot; selected: boolean }) {
  const mesh = useRef<THREE.Mesh>(null);
  const [x, y, z] = hotspot.position;
  const isDamage = hotspot.kind === "damage";

  const texture = useMemo(() => {
    const size = 256;
    const canvas = document.createElement("canvas");
    canvas.width = canvas.height = size;
    const ctx = canvas.getContext("2d")!;
    const g = ctx.createRadialGradient(size / 2, size / 2, 0, size / 2, size / 2, size / 2);
    const c = isDamage ? "255,70,90" : "255,170,60";
    g.addColorStop(0, `rgba(${c},0.95)`);
    g.addColorStop(0.45, `rgba(${c},0.45)`);
    g.addColorStop(1, `rgba(${c},0)`);
    ctx.fillStyle = g;
    ctx.fillRect(0, 0, size, size);
    const t = new THREE.CanvasTexture(canvas);
    t.colorSpace = THREE.SRGBColorSpace;
    return t;
  }, [isDamage]);

  // Panel normal + offset so the decal sits just above the surface.
  const { position, rotation, scale } = useMemo(() => {
    const off = 0.02;
    if (Math.abs(z) > 0.8) return { position: [x, y, z + Math.sign(z) * off] as const, rotation: [0, z > 0 ? 0 : Math.PI, 0] as const, scale: [0.85, 0.55] as const };
    if (Math.abs(x) > 1.9) return { position: [x + Math.sign(x) * off, y, z] as const, rotation: [0, x > 0 ? Math.PI / 2 : -Math.PI / 2, 0] as const, scale: [0.8, 0.45] as const };
    return { position: [x, y + off, z] as const, rotation: [-Math.PI / 2, 0, 0] as const, scale: [0.8, 0.6] as const };
  }, [x, y, z]);

  useFrame(({ clock }) => {
    if (!mesh.current) return;
    const m = mesh.current.material as THREE.MeshBasicMaterial;
    const t = clock.getElapsedTime();
    const base = selected ? 0.55 : 0.28;
    m.opacity = base + (selected ? Math.sin(t * 2.2) * 0.08 : 0);
  });

  return (
    <mesh ref={mesh} position={[position[0], position[1], position[2]]} rotation={[rotation[0], rotation[1], rotation[2]]}>
      <planeGeometry args={[scale[0], scale[1]]} />
      <meshBasicMaterial map={texture} transparent opacity={0.3} depthWrite={false} blending={THREE.AdditiveBlending} side={THREE.DoubleSide} />
    </mesh>
  );
}

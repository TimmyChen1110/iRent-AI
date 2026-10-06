"use client";

import { useEffect, useRef, type MutableRefObject } from "react";
import { useFrame, useThree } from "@react-three/fiber";
import * as THREE from "three";
import type { OrbitControls as OrbitControlsImpl } from "three-stdlib";
import { DEFAULT_CAMERA } from "@/config/vehicleModel";

export interface CameraFocus {
  position: [number, number, number];
  target: [number, number, number];
}

/** Default camera for Interior mode: elevated three-quarter view into the cabin. */
export const INTERIOR_CAMERA: CameraFocus = { position: [3.0, 3.4, 3.6], target: [-0.2, 0.85, 0] };

export function focusForPoint(point: [number, number, number], mode: "exterior" | "interior" = "exterior"): CameraFocus {
  const p = new THREE.Vector3(...point);
  const dir = new THREE.Vector3(p.x, 0, p.z);
  if (dir.length() < 0.35) dir.set(0.6, 0, 1);
  dir.normalize();
  const dist = mode === "interior" ? 2.6 : 4.7;
  const lift = mode === "interior" ? 2.3 : 1.5;

  const cam = p.clone().add(dir.multiplyScalar(dist)).add(new THREE.Vector3(0, lift, 0));
  return { position: [cam.x, cam.y, cam.z], target: [p.x, p.y, p.z] };
}

export function CameraRig({
  controlsRef,
  focus,
  animatingRef,
}: {
  controlsRef: MutableRefObject<OrbitControlsImpl | null>;
  focus: CameraFocus | null;
  animatingRef: MutableRefObject<boolean>;
}) {
  const { camera } = useThree();
  const goalPos = useRef(new THREE.Vector3(...DEFAULT_CAMERA.position));
  const goalTarget = useRef(new THREE.Vector3(...DEFAULT_CAMERA.target));

  useEffect(() => {
    const f = focus ?? DEFAULT_CAMERA;
    goalPos.current.set(...f.position);
    goalTarget.current.set(...f.target);
    animatingRef.current = true;
  }, [focus, animatingRef]);

  useFrame((_, delta) => {
    if (!animatingRef.current) return;
    const controls = controlsRef.current;
    const k = 1 - Math.exp(-delta * 4.2);
    camera.position.lerp(goalPos.current, k);
    if (controls) {
      controls.target.lerp(goalTarget.current, k);
      controls.update();
    } else {
      camera.lookAt(goalTarget.current);
    }
    const done =
      camera.position.distanceTo(goalPos.current) < 0.01 &&
      (!controls || controls.target.distanceTo(goalTarget.current) < 0.01);
    if (done) animatingRef.current = false;
  });

  return null;
}

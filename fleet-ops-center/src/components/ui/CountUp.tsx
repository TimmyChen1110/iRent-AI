"use client";

import { useEffect, useRef, useState } from "react";
import { animate } from "framer-motion";
import { formatNumber } from "@/lib/utils";

export function CountUp({ value, duration = 1.1, className }: { value: number; duration?: number; className?: string }) {
  const [display, setDisplay] = useState(0);
  const from = useRef(0);

  useEffect(() => {
    const controls = animate(from.current, value, {
      duration,
      ease: [0.22, 1, 0.36, 1],
      onUpdate: (v) => setDisplay(Math.round(v)),
    });
    from.current = value;
    return () => controls.stop();
  }, [value, duration]);

  return <span className={className}>{formatNumber(display)}</span>;
}

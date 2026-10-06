"use client";
/* eslint-disable @next/next/no-img-element -- local placeholder evidence photos */

import { useCallback, useEffect, useRef, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { ZoomIn, ZoomOut, Layers, SplitSquareHorizontal, ScanSearch, Sparkles, Link2 } from "lucide-react";
import type { DamageHotspot, DiffRegion, Evidence } from "@/types";
import { GlassPanel, SectionHeader } from "@/components/ui/GlassPanel";
import { cn, pct } from "@/lib/utils";

type Mode = "slider" | "overlay" | "side";

export function BeforeAfterComparison({
  evidence,
  className,
  title = "AI 證據比對",
  focus,
}: {
  evidence: Evidence;
  className?: string;
  title?: string;
  /** Set by "View Evidence" on the 3D twin: links this panel to the hotspot it came from. */
  focus?: { hotspot: DamageHotspot; token: number } | null;
}) {
  const [mode, setMode] = useState<Mode>("slider");
  const [split, setSplit] = useState(50);
  const [overlay, setOverlay] = useState(50);
  const [zoom, setZoom] = useState(1);
  // Diff visibility is keyed to the latest "View Evidence" token so each click re-shows it without an effect.
  const [diffToggle, setDiffToggle] = useState<{ token: number; value: boolean }>({ token: 0, value: true });
  const focusToken = focus?.token ?? 0;
  const showDiff = diffToggle.token === focusToken ? diffToggle.value : true;
  const toggleDiff = () => setDiffToggle({ token: focusToken, value: !showDiff });
  const [dragging, setDragging] = useState(false);
  const stageRef = useRef<HTMLDivElement>(null);

  const interiorFocus = focus?.hotspot.mode === "interior";
  const summary = interiorFocus && evidence.interiorSummary ? evidence.interiorSummary : evidence.summary;
  const summaryConfidence = interiorFocus ? (focus?.hotspot.confidence ?? evidence.confidence) : evidence.confidence;

  const updateSplit = useCallback((clientX: number) => {
    const el = stageRef.current;
    if (!el) return;
    const rect = el.getBoundingClientRect();
    const x = Math.min(Math.max(clientX - rect.left, 0), rect.width);
    setSplit((x / rect.width) * 100);
  }, []);

  useEffect(() => {
    if (!dragging) return;
    const move = (e: PointerEvent) => updateSplit(e.clientX);
    const up = () => setDragging(false);
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
    return () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
    };
  }, [dragging, updateSplit]);

  const imgStyle = { transform: `scale(${zoom})`, transformOrigin: "60% 60%" } as const;
  const region = evidence.diffRegion;
  const noPhotos = !evidence.before && !evidence.after;

  return (
    <GlassPanel className={cn("relative", className)}>
      {/* Highlight pulse each time "View Evidence" links here (keyed by token, no state). */}
      {focus && (
        <motion.div
          key={`flash-${focus.token}`}
          initial={{ opacity: 1 }}
          animate={{ opacity: 0 }}
          transition={{ duration: 2, ease: "easeOut" }}
          className={cn("pointer-events-none absolute inset-0 rounded-2xl ring-2", interiorFocus ? "ring-amber-400/50" : "ring-rose-400/50")}
        />
      )}
      <AnimatePresence>
        {focus && (
          <motion.div
            key={focus.token}
            initial={{ opacity: 0, y: -6 }}
            animate={{ opacity: 1, y: 0 }}
            className={cn("mb-3 flex items-center gap-2 rounded-lg border px-3 py-1.5 text-[11.5px]", interiorFocus ? "border-amber-400/20 bg-amber-400/[0.06] text-amber-100" : "border-rose-400/20 bg-rose-400/[0.06] text-rose-100")}
          >
            <Link2 className="h-3.5 w-3.5 shrink-0" />
            <span className="truncate">
              來自 3D 數位分身 · <span className="font-semibold">{focus.hotspot.label}</span> 標記 · AI 原文「{focus.hotspot.title}」
            </span>
            <span className="ml-auto hidden shrink-0 text-white/50 2xl:inline">此判定的來源照片</span>
          </motion.div>
        )}
      </AnimatePresence>
      <SectionHeader
        title={title}
        subtitle="租前 vs 還車後"
        action={
          <div className="flex items-center gap-1">
            <ModeButton active={mode === "slider"} onClick={() => setMode("slider")} title="滑桿比對">
              <SplitSquareHorizontal className="h-3.5 w-3.5" />
            </ModeButton>
            <ModeButton active={mode === "overlay"} onClick={() => setMode("overlay")} title="疊圖">
              <Layers className="h-3.5 w-3.5" />
            </ModeButton>
            <ModeButton active={mode === "side"} onClick={() => setMode("side")} title="並排">
              <span className="text-[10px] font-semibold">A|B</span>
            </ModeButton>
            <span className="mx-1 h-4 w-px bg-white/10" />
            <ModeButton active={showDiff} onClick={toggleDiff} title="標示差異">
              <ScanSearch className="h-3.5 w-3.5" />
            </ModeButton>
            <ModeButton onClick={() => setZoom((z) => Math.max(1, +(z - 0.25).toFixed(2)))} title="縮小">
              <ZoomOut className="h-3.5 w-3.5" />
            </ModeButton>
            <span className="tabular w-10 text-center text-[11px] text-white/60">{Math.round(zoom * 100)}%</span>
            <ModeButton onClick={() => setZoom((z) => Math.min(3, +(z + 0.25).toFixed(2)))} title="放大">
              <ZoomIn className="h-3.5 w-3.5" />
            </ModeButton>
          </div>
        }
      />

      {noPhotos ? (
        <div className="grid aspect-[16/9] w-full place-items-center rounded-xl border border-dashed border-white/10 text-[12.5px] text-muted">此車目前沒有借還照片證據</div>
      ) : mode === "side" ? (
        <div className="grid grid-cols-2 gap-3">
          <Frame label="租前">
            {evidence.before ? <img src={evidence.before} alt="租前照片" className="h-full w-full object-cover transition-transform duration-300" style={imgStyle} draggable={false} /> : <Missing />}
          </Frame>
          <Frame label="還車後" accent>
            {evidence.after ? <img src={evidence.after} alt="還車後照片" className="h-full w-full object-cover transition-transform duration-300" style={imgStyle} draggable={false} /> : <Missing />}
            <DiffBoxes visible={showDiff && !interiorFocus} boxes={evidence.boxes} region={region} confidence={evidence.confidence} />
          </Frame>
        </div>
      ) : (
        <div
          ref={stageRef}
          className={cn("always-dark no-select relative aspect-[16/9] w-full overflow-hidden rounded-xl bg-black/40 ring-1 ring-white/[0.06]", mode === "slider" && "cursor-col-resize")}
          onPointerDown={(e) => {
            if (mode !== "slider") return;
            setDragging(true);
            updateSplit(e.clientX);
          }}
        >
          {/* after (base) */}
          {evidence.after ? <img src={evidence.after} alt="還車後照片" className="absolute inset-0 h-full w-full object-cover transition-transform duration-300" style={imgStyle} draggable={false} /> : <Missing />}
          <DiffBoxes visible={showDiff && !interiorFocus} boxes={evidence.boxes} region={region} confidence={evidence.confidence} />

          {/* before (clipped or blended) */}
          <div
            className="absolute inset-0"
            style={
              mode === "slider"
                ? { clipPath: `inset(0 ${100 - split}% 0 0)` }
                : { opacity: 1 - overlay / 100 }
            }
          >
            {evidence.before ? <img src={evidence.before} alt="租前照片" className="absolute inset-0 h-full w-full object-cover transition-transform duration-300" style={imgStyle} draggable={false} /> : <Missing />}
          </div>

          {mode === "slider" && (
            <>
              <div className="pointer-events-none absolute inset-y-0 w-px bg-white/90 shadow-[0_0_12px_rgba(255,255,255,0.6)]" style={{ left: `${split}%` }} />
              <div
                className="pointer-events-none absolute top-1/2 grid h-9 w-9 -translate-x-1/2 -translate-y-1/2 place-items-center rounded-full bg-white text-black shadow-xl"
                style={{ left: `${split}%` }}
              >
                <SplitSquareHorizontal className="h-4 w-4" />
              </div>
            </>
          )}

          <Tag className="left-3 top-3">租前</Tag>
          <Tag className="right-3 top-3" accent>
            還車後
          </Tag>

          {mode === "overlay" && (
            <div className="absolute inset-x-4 bottom-3 flex items-center gap-3 rounded-lg bg-black/60 px-3 py-2 backdrop-blur">
              <span className="text-[11px] text-white/60">租前</span>
              <input type="range" min={0} max={100} value={overlay} onChange={(e) => setOverlay(Number(e.target.value))} className="flex-1 accent-white" />
              <span className="text-[11px] text-white/60">還車後</span>
            </div>
          )}
        </div>
      )}

      <div className="mt-4 flex items-start gap-3 rounded-xl border border-rose-400/15 bg-rose-400/[0.06] p-3.5">
        <span className="grid h-7 w-7 shrink-0 place-items-center rounded-lg bg-rose-400/15 text-rose-200">
          <Sparkles className="h-3.5 w-3.5" />
        </span>
        <div className="min-w-0 flex-1">
          <div className="text-[13px] font-medium text-white/90">{summary}</div>
          <div className="mt-0.5 text-[12px] text-muted">
            信心度 <span className="tabular font-semibold text-white/85">{pct(summaryConfidence)}</span> · 借車照 vs 還車照 · AI 標註框 {evidence.boxes.length} 個
          </div>
        </div>
      </div>
    </GlassPanel>
  );
}

function DiffBoxes({ visible, boxes, region, confidence }: { visible: boolean; boxes: Evidence["boxes"]; region?: DiffRegion; confidence: number }) {
  if (!visible) return null;
  if (boxes.length > 0) {
    return (
      <>
        {boxes.map((b, i) => {
          const [y0, x0, y1, x1] = b.box_2d;
          return (
            <motion.div key={i} initial={{ opacity: 0, scale: 0.9 }} animate={{ opacity: 1, scale: 1 }} transition={{ delay: i * 0.08 }} className="pointer-events-none absolute rounded-lg border-2 border-rose-400/90 shadow-[0_0_0_4px_rgba(251,113,133,0.15),0_0_30px_rgba(251,113,133,0.35)]" style={{ left: `${x0 / 10}%`, top: `${y0 / 10}%`, width: `${(x1 - x0) / 10}%`, height: `${(y1 - y0) / 10}%` }}>
              <span className="absolute -top-6 left-0 whitespace-nowrap rounded-md bg-rose-500 px-1.5 py-0.5 text-[10px] font-semibold text-white">{i + 1} · {b.label}{typeof b.confidence === "number" ? ` · ${Math.round(b.confidence * 100)}%` : ""}</span>
            </motion.div>
          );
        })}
      </>
    );
  }
  if (!region) return null;
  return (
    <motion.div
      initial={{ opacity: 0, scale: 0.9 }}
      animate={{ opacity: 1, scale: 1 }}
      className="pointer-events-none absolute rounded-lg border-2 border-rose-400/90 shadow-[0_0_0_4px_rgba(251,113,133,0.15),0_0_30px_rgba(251,113,133,0.35)]"
      style={{ left: `${region.x}%`, top: `${region.y}%`, width: `${region.w}%`, height: `${region.h}%` }}
    >
      <span className="absolute -top-6 left-0 rounded-md bg-rose-500 px-1.5 py-0.5 text-[10px] font-semibold text-white">新增車損 · {pct(confidence)}</span>
      <span className="absolute inset-0 rounded-lg bg-rose-400/10 mix-blend-screen" />
    </motion.div>
  );
}

function Missing() {
  return <div className="grid h-full w-full place-items-center text-[12px] text-white/35">無照片</div>;
}

function Frame({ label, accent, children }: { label: string; accent?: boolean; children: React.ReactNode }) {
  return (
    <div className="always-dark relative aspect-[16/10] overflow-hidden rounded-xl bg-black/40 ring-1 ring-white/[0.06]">
      {children}
      <Tag className="left-3 top-3" accent={accent}>
        {label}
      </Tag>
    </div>
  );
}

function Tag({ children, className, accent }: { children: React.ReactNode; className?: string; accent?: boolean }) {
  return (
    <span
      className={cn(
        "pointer-events-none absolute rounded-md px-2 py-1 text-[10.5px] font-semibold uppercase tracking-wider backdrop-blur",
        accent ? "bg-rose-500/80 text-white" : "bg-black/60 text-white/85",
        className,
      )}
    >
      {children}
    </span>
  );
}

function ModeButton({ active, onClick, title, children }: { active?: boolean; onClick: () => void; title: string; children: React.ReactNode }) {
  return (
    <button
      title={title}
      onClick={onClick}
      className={cn(
        "grid h-7 w-7 place-items-center rounded-md transition",
        active ? "bg-white/[0.12] text-white" : "text-white/50 hover:bg-white/[0.06] hover:text-white",
      )}
    >
      {children}
    </button>
  );
}

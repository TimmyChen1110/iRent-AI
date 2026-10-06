import type { HotspotLocation } from "@/types";

/**
 * 把 AI 回傳的自由文字位置（例「右後保險桿下緣（右後輪後方）」、「左後車門下緣」）
 * 對應到 3D 車身的 14 個區域。規則：先判左右／前後，再判部位；對不到就依拍攝角度推。
 * 這是近似對應，標註卡上仍會顯示 AI 原文。
 */
export function locateDamage(text: string | null | undefined, angle?: string | null): HotspotLocation {
  const t = (text || "").replace(/\s/g, "");
  const a = angle || "";
  const left = /左/.test(t) || (!/右/.test(t) && /左/.test(a));
  const right = /右/.test(t) || (!/左/.test(t) && /右/.test(a));
  const rear = /後|尾|行李|hatch/i.test(t) || (!/前|頭|引擎/.test(t) && /後/.test(a));
  const front = /前|頭|引擎|大燈|水箱|日行燈|進氣/.test(t) || (!rear && /前/.test(a));

  if (/車頂|roof/i.test(t)) return "roof";
  if (/擋風|windshield/i.test(t)) return "windshield";
  if (/引擎蓋|hood|車頭/.test(t) && !/保險桿|保桿/.test(t)) return "hood";
  if (/車門|門板|門/.test(t)) {
    if (rear) return left ? "left-rear-door" : "right-rear-door";
    return left ? "left-front-door" : "right-front-door";
  }
  if (/葉子板|側板|側裙|輪拱|側身/.test(t)) {
    if (rear) return left ? "left-rear-quarter" : "right-rear-quarter";
    return left ? "left-front-fender" : "right-front-fender";
  }
  if (/保險桿|保桿|尾燈|大燈|後尾門|行李箱|車尾|反光片|下唇/.test(t)) {
    if (rear && !front) return "rear-bumper";
    if (front && !rear) return "front-bumper";
    return rear ? "rear-bumper" : "front-bumper";
  }
  if (rear) return left ? "left-rear-quarter" : right ? "right-rear-quarter" : "rear-bumper";
  if (front) return left ? "left-front-fender" : right ? "right-front-fender" : "front-bumper";
  return left ? "left-front-door" : right ? "right-front-door" : "roof";
}

/** 車內問題 → 車艙標記位置（依序落在後座／杯架／駕駛座）。 */
export function locateInteriorIssue(issue: string, index: number): HotspotLocation {
  if (/杯|飲|瓶|罐/.test(issue)) return "cup-holder";
  if (/駕駛|前座|方向盤|儀表/.test(issue)) return "driver-seat";
  if (/後座|後排|行李/.test(issue)) return "rear-seat";
  return (["rear-seat", "cup-holder", "driver-seat"] as const)[index % 3];
}

const TYPE_MAP: Array<[RegExp, "scratch" | "dent" | "crack" | "paint" | "stain" | "debris"]> = [
  [/刮|擦/, "scratch"], [/凹/, "dent"], [/破|裂|碎/, "crack"], [/漆|轉印|掉漆/, "paint"], [/污|漬/, "stain"],
];
export function damageType(text: string | null | undefined) {
  return TYPE_MAP.find(([re]) => re.test(text || ""))?.[1] ?? "scratch";
}
export function damageSeverity(s: string | null | undefined): "low" | "medium" | "high" {
  if (!s) return "medium";
  if (/high|高|嚴重/i.test(s)) return "high";
  if (/low|低|輕/i.test(s)) return "low";
  return "medium";
}

/** 精簡後台共用標籤：AI 檢測／人工審核狀態、資料來源、車牌辨識比對。 */
import type { DataSource, ReviewState, RentalRow } from "./types";

type Tone = "danger" | "success" | "info" | "neutral" | "warning" | "violet";

export const REVIEW_META: Record<ReviewState, { label: string; tone: Tone }> = {
  capturing: { label: "等待還車照片", tone: "neutral" },
  analyzing: { label: "檢測中", tone: "info" },
  passed: { label: "檢測完成，無異常", tone: "success" },
  pending_review: { label: "發現異常，待審核", tone: "danger" },
  reviewed: { label: "已審核", tone: "violet" },
  failed: { label: "檢測失敗", tone: "warning" },
};

export const SOURCE_META: Record<DataSource, { label: string; tone: Tone }> = {
  app: { label: "App 租約", tone: "neutral" },
  fixture: { label: "固定劇本（非真實 AI）", tone: "warning" },
  legacy: { label: "舊版上傳流程", tone: "neutral" },
};

export const PLATE_META: Record<RentalRow["pickup_plate_status"], { label: string; tone: Tone }> = {
  MATCH: { label: "車牌相符", tone: "success" },
  MISMATCH: { label: "車牌不符（待人工確認）", tone: "danger" },
  MANUAL: { label: "手動輸入（待人工確認）", tone: "warning" },
  UNKNOWN: { label: "部分未辨識", tone: "warning" },
  PENDING: { label: "尚無照片", tone: "neutral" },
};

/** 案件人工裁決狀態（沿用既有 review_status）。 */
export const CASE_REVIEW_LABEL: Record<string, string> = {
  unreviewed: "待審核", confirmed_open: "已確認・整備中", confirmed_done: "已確認・整備完成", rejected: "已駁回（AI 誤判）", retake: "待補件", normal: "正常",
};

export function duration(seconds: number | null | undefined): string {
  if (seconds == null) return "—";
  const h = Math.floor(seconds / 3600), m = Math.floor((seconds % 3600) / 60);
  return h ? `${h} 小時 ${m} 分` : `${m} 分`;
}

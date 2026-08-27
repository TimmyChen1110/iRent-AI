#!/usr/bin/env python3
"""Stage 1 — CV 前處理：借/還照對齊 + 差異偵測（實驗性，【未接入主流程】）。

⚠️ 實測結論：這層過濾器不可用，已從主判定鏈路排除。
   在 141 組配對上實跑（見 cv_results.json）：
     - 對齊成功率僅 64/141（45%）——手持拍攝的角度/距離差異太大，
       ORB+RANSAC 在 77 組上找不到足夠 inlier。
       （後續已升級為 SIFT+ORB@15 → 92/141=65%，見下方第二次驗證；
        cv_results.json 現為升級後的結果。）
     - 對齊成功的 64 組中，正樣本 pair_score 為 [11.06, 11.80, 12.01]，
       完全落在負樣本區間 [9.74, 12.33] 之內——【沒有任何閾值能分離兩者】。
   因此不存在「安全放行區間」，強行加這層只會漏抓真實車損。
   真正有效的零成本過濾層是 quality_gate.py（純 CV 攔品質不合格照片，
   已接入 judge_photos.judge_pair() 的步驟 ①）。

   本檔保留作為「我們試過 CV 差異偵測、並用數據證明它不夠」的實驗紀錄，
   請勿在架構圖或簡報中宣稱此層有成本節省效果。

⚠️⚠️ 2026-08-27 第二次驗證：外部提出的「純 CV 還車判讀」方法論，逐項實測後
   結論不變。**若有人再次提議這條路線，先讀這段，不要重跑第三次。**

   該方法論針對上述失敗點提出四項升級，實測結果分歧：

   ① 配準升級【有效，已採納】：改 robust 偵測器 + inlier 門檻 25→15。
      ORB@25=45% → ORB@15=56% → SIFT@15=60% → SIFT+ORB 補位=67%。
      （方法論原文建議 AKAZE，本機 OpenCV 5.0 未內建，改用同性質的 SIFT。）
      本檔實跑為 92/141=65%（比 67% 略低：量測腳本另加了 Shades-of-Gray
      白平衡，本檔未採用——它只對配準有邊際幫助，卻會改動 pair_score 基準）。
      **但對齊變多不等於可用**：升級後 positive [11.00, 11.96] 仍完全落在
      negative [9.74, 12.45] 之內，與升級前同樣無法分離。

   ② Gating 可分離性【無效，主張證偽】：方法論宣稱「60–80% 可零成本放行」。
      加上高光遮罩、Shades-of-Gray 白平衡、增益補償、Lab-L 通道 SSIM、
      陰影比值判別（實際濾掉 84 個候選區塊）後，對照人工重標：
        - 正樣本區間 [9.64, 10.81]，**71% 的負樣本仍落在此區間內**
        - 「不漏放任何真損」門檻 = 9.64 → 只能放行全體 8%（非 60–80%）
        - 反向高分告警：0/11 正樣本高過最大負樣本，無告警區間
        - 另有 47 組配準失敗（含 11 筆真損）依定義必須全部送 VLM
      → 前處理做好做滿之後，重疊率仍與第一次實驗同級。不是調參問題。

   ③ 高光佔比取代 VLM 觀測品質【前提不成立】：方法論舉例「高光蓋住 40% panel」。
      實測 141 張還車照：p50=2.5%、p90=8.7%、**max 僅 14.7%，無一超過 20%**。
      動態範圍太窄，無法取代 coverage.py 的分區品質評分。

   ④ 車牌當比例尺推嚴重度【覆蓋率不足】：還車照僅 46% 找得到疑似車牌矩形
      （且此為寬鬆上界——只要求形狀近似 320:150，未要求辨識字元）。
      過半案例拿不到 mm/pixel，無法據此做零成本嚴重度分級。

   根因與 Prompt 架構規格落敗相同：方法論預設「營運人員標準化拍攝」，
   本資料集是用戶手持手機拍攝，角度／距離／光照差異遠大於其假設。

流程（每組配對）：
  1. SIFT（ORB 補位）特徵匹配 + RANSAC Homography，把借車照對齊到還車照視角
  2. CLAHE 均衡化後計算 SSIM 差異圖（降低光照影響）
  3. 差異圖二值化 → 連通元件 → 候選差異框
  4. pair_score = 最顯著元件的 (平均差異 × log(面積))；對齊失敗者強制送 VLM

輸出 cv_results.json（閾值可分離性分析結果如上）。
用法：python3 cv_prefilter.py
"""
import json
import math
import time
from pathlib import Path

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
PAIRS = json.loads((HERE / "pairs.json").read_text())["pairs"]
OUT = HERE / "cv_results.json"

MIN_INLIERS = 15          # RANSAC inlier 數低於此視為對齊失敗
                          # 25→15：實測 ORB 45%→56% 對齊成功率，且未引入誤配（見檔頭）
DIFF_BIN = 0.55           # 差異圖二值化門檻 (1 - SSIM)
MIN_AREA = 400            # 候選元件最小面積 (px)
BORDER = 12               # 忽略貼邊元件（warp 邊緣偽差異）


def load_gray(path: str) -> np.ndarray:
    img = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
    if img is None:
        raise IOError(path)
    if img.shape != (720, 1280):
        img = cv2.resize(img, (1280, 720))
    return img


def _align_with(src: np.ndarray, dst: np.ndarray, detector: str):
    """用指定偵測器對齊一次。回傳 (warped, valid_mask, inliers)。"""
    if detector == "SIFT":
        det, norm = cv2.SIFT_create(nfeatures=3000), cv2.NORM_L2
    else:
        det, norm = cv2.ORB_create(nfeatures=3000), cv2.NORM_HAMMING
    k1, d1 = det.detectAndCompute(src, None)
    k2, d2 = det.detectAndCompute(dst, None)
    if d1 is None or d2 is None or len(k1) < 50 or len(k2) < 50:
        return None, None, 0
    raw = cv2.BFMatcher(norm).knnMatch(d1, d2, k=2)
    good = [m for m, n in (p for p in raw if len(p) == 2) if m.distance < 0.75 * n.distance]
    if len(good) < MIN_INLIERS:
        return None, None, len(good)
    pts1 = np.float32([k1[m.queryIdx].pt for m in good]).reshape(-1, 1, 2)
    pts2 = np.float32([k2[m.trainIdx].pt for m in good]).reshape(-1, 1, 2)
    H, mask = cv2.findHomography(pts1, pts2, cv2.RANSAC, 5.0)
    if H is None:
        return None, None, 0
    inliers = int(mask.sum())
    if inliers < MIN_INLIERS:
        return None, None, inliers
    h, w = dst.shape
    warped = cv2.warpPerspective(src, H, (w, h))
    valid = cv2.warpPerspective(np.full_like(src, 255), H, (w, h))
    valid = cv2.erode((valid > 250).astype(np.uint8), np.ones((15, 15), np.uint8))
    return warped, valid, inliers


def align(src: np.ndarray, dst: np.ndarray):
    """把 src(借) 對齊到 dst(還)。SIFT 優先、ORB 補位。

    2026-08-27 實測（141 組）：SIFT 60% > ORB 56%，兩者聯集 67%——
    兩個偵測器失敗的組別不同，所以補位有意義，不是多跑一次而已。
    """
    warped, valid, inliers = _align_with(src, dst, "SIFT")
    if warped is not None:
        return warped, valid, inliers
    best_inl = inliers
    warped, valid, inliers = _align_with(src, dst, "ORB")
    if warped is not None:
        return warped, valid, inliers
    return None, None, max(best_inl, inliers)


def ssim_map(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    a = a.astype(np.float64)
    b = b.astype(np.float64)
    C1, C2 = (0.01 * 255) ** 2, (0.03 * 255) ** 2
    blur = lambda x: cv2.GaussianBlur(x, (11, 11), 1.5)
    mu_a, mu_b = blur(a), blur(b)
    va = blur(a * a) - mu_a**2
    vb = blur(b * b) - mu_b**2
    cov = blur(a * b) - mu_a * mu_b
    return ((2 * mu_a * mu_b + C1) * (2 * cov + C2)) / ((mu_a**2 + mu_b**2 + C1) * (va + vb + C2))


def analyze_pair(pickup_path: str, return_path: str) -> dict:
    src, dst = load_gray(pickup_path), load_gray(return_path)
    warped, valid, inliers = align(src, dst)
    if warped is None:
        return {"align_ok": False, "inliers": inliers, "pair_score": None, "components": []}

    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    wa, db = clahe.apply(warped), clahe.apply(dst)
    dmap = 1.0 - ssim_map(wa, db)
    dmap[valid == 0] = 0.0
    dmap[:BORDER, :] = 0; dmap[-BORDER:, :] = 0; dmap[:, :BORDER] = 0; dmap[:, -BORDER:] = 0

    binary = (dmap > DIFF_BIN).astype(np.uint8)
    binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8))
    n, labels, stats, _ = cv2.connectedComponentsWithStats(binary)
    comps = []
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        if area < MIN_AREA:
            continue
        mean_d = float(dmap[labels == i].mean())
        comps.append({
            "bbox": [int(x), int(y), int(x + w), int(y + h)],
            "area": int(area),
            "mean_diff": round(mean_d, 4),
            "salience": round(mean_d * math.log(area), 4),
        })
    comps.sort(key=lambda c: -c["salience"])
    return {
        "align_ok": True,
        "inliers": inliers,
        "pair_score": comps[0]["salience"] if comps else 0.0,
        "components": comps[:8],
    }


def main():
    results = []
    t0 = time.time()
    for i, p in enumerate(PAIRS):
        r = analyze_pair(p["pickup"], p["return"])
        r.update(car=p["car"], angle=p["angle"], label=p["label"])
        results.append(r)
        if (i + 1) % 20 == 0:
            print(f"  {i + 1}/{len(PAIRS)} done ({time.time() - t0:.0f}s)")
    OUT.write_text(json.dumps(results, ensure_ascii=False, indent=1))

    ok = [r for r in results if r["align_ok"]]
    fail = [r for r in results if not r["align_ok"]]
    print(f"\n對齊成功 {len(ok)}/{len(results)}（失敗 {len(fail)} 組強制送 VLM）")
    for lbl in ("negative", "positive"):
        scores = sorted(r["pair_score"] for r in ok if r["label"] == lbl)
        if scores:
            q = lambda p: scores[min(len(scores) - 1, int(p * len(scores)))]
            print(f"  {lbl:8s} n={len(scores):3d}  score min={scores[0]:.2f} "
                  f"p25={q(.25):.2f} p50={q(.5):.2f} p75={q(.75):.2f} max={scores[-1]:.2f}")


if __name__ == "__main__":
    main()

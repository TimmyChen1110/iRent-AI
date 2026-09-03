"""純 CV 方法論可行性量測（一次性實驗，【未接入主流程】，2026-08-27）。

外部提出一份「純 CV 還車影像判讀」方法論，本檔逐項在既有 141 組配對上實測其主張。
結論摘要（完整版見 cv_prefilter.py 檔頭）：
  A. 配準升級      ✅ 有效 → 已採納進 cv_prefilter.align()（45%→65%）
  B. 高光佔比      ❌ max 僅 14.7%，動態範圍不足以取代 coverage.py 的 VLM 評分
  C. 車牌比例尺    ❌ 還車照僅 46% 可見，過半案例無法取得 mm/pixel
  D. gating 可分離 ❌ 71% 負樣本落在正樣本區間內，安全放行僅 8%（主張為 60–80%）

保留本檔的理由：D 的否決結論是簡報素材（「我們量化評估過並用數據否決」），
而重跑它需要完整的前處理堆疊（高光遮罩／白平衡／增益補償／陰影判別），
不留檔的話下次有人提同樣方案就得從頭寫一遍。

用法：python3 cv_methodology_probe.py   # 約 75s，輸出 cv_methodology_probe.json
注意：本機 OpenCV 5.0 未內建 AKAZE（方法論原文建議），改用同性質的 SIFT。
"""
import json, math, sys, time
from pathlib import Path
from pairs_io import load_pairs  # noqa: E402
import cv2, numpy as np
from PIL import Image, ImageOps

H = Path(__file__).resolve().parent
PAIRS = load_pairs()
RELABELS = {(r["car"], r["angle"]): r["relabel"]
            for r in json.loads((H/"relabels.json").read_text())["relabels"]}

W, HH = 1280, 720
MIN_INLIERS = 15   # 文件 §2 建議值（舊實驗用 25）


def load(path):
    """EXIF 正規化後回傳 BGR uint8。資料集 76% 照片帶 Orientation。"""
    im = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
    a = np.asarray(im)[:, :, ::-1]
    return cv2.resize(a, (W, HH))


# ---------- §1 高光 / 陰影 ----------
def highlight_mask(bgr):
    """二色反射模型：高亮度 + 低飽和度 = 鏡面反射。回傳 (mask, 佔比)。"""
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    v = hsv[:, :, 2].astype(np.float32)/255.0
    s = hsv[:, :, 1].astype(np.float32)/255.0
    m = ((v > 0.90) & (s < 0.15)).astype(np.uint8)
    return m, float(m.mean())


def shades_of_gray(bgr, p=6):
    """Shades of Gray 白平衡（Minkowski p=6），文件 §1 指定。"""
    f = bgr.astype(np.float32)
    ill = np.power(np.mean(np.power(f, p), axis=(0, 1)), 1.0/p)
    ill = ill/ (ill.mean() + 1e-6)
    return np.clip(f/ (ill + 1e-6), 0, 255).astype(np.uint8)


# ---------- §2 配準 ----------
def align(src, dst, detector):
    g1 = cv2.cvtColor(src, cv2.COLOR_BGR2GRAY)
    g2 = cv2.cvtColor(dst, cv2.COLOR_BGR2GRAY)
    # 本機 OpenCV 5.0 未內建 AKAZE；改用 SIFT 作為「對光照更 robust 的
    # 替代偵測器」，這正是文件 §2 提 AKAZE 的目的。
    if detector == "SIFT":
        det = cv2.SIFT_create(nfeatures=3000)
        norm = cv2.NORM_L2
    else:
        det = cv2.ORB_create(nfeatures=3000)
        norm = cv2.NORM_HAMMING
    k1, d1 = det.detectAndCompute(g1, None)
    k2, d2 = det.detectAndCompute(g2, None)
    if d1 is None or d2 is None or len(k1) < 50 or len(k2) < 50:
        return None, None, 0
    raw = cv2.BFMatcher(norm).knnMatch(d1, d2, k=2)
    good = [m for m, n in (p for p in raw if len(p) == 2)
            if m.distance < 0.75*n.distance]
    if len(good) < MIN_INLIERS:
        return None, None, len(good)
    p1 = np.float32([k1[m.queryIdx].pt for m in good]).reshape(-1, 1, 2)
    p2 = np.float32([k2[m.trainIdx].pt for m in good]).reshape(-1, 1, 2)
    M, mask = cv2.findHomography(p1, p2, cv2.RANSAC, 5.0)
    if M is None:
        return None, None, 0
    inl = int(mask.sum())
    if inl < MIN_INLIERS:
        return None, None, inl
    warped = cv2.warpPerspective(src, M, (W, HH))
    valid = cv2.warpPerspective(np.full(src.shape[:2], 255, np.uint8), M, (W, HH))
    valid = cv2.erode((valid > 250).astype(np.uint8), np.ones((15, 15), np.uint8))
    return warped, valid, inl


# ---------- §2 差異 ----------
def ssim_map(a, b):
    a = a.astype(np.float64); b = b.astype(np.float64)
    C1, C2 = (0.01*255)**2, (0.03*255)**2
    blur = lambda x: cv2.GaussianBlur(x, (11, 11), 1.5)
    ma, mb = blur(a), blur(b)
    va = blur(a*a)-ma**2; vb = blur(b*b)-mb**2; cov = blur(a*b)-ma*mb
    return ((2*ma*mb+C1)*(2*cov+C2))/((ma**2+mb**2+C1)*(va+vb+C2))


def gain_compensate(warped_L, dst_L, valid):
    """用有效區回歸 I_ret ≈ a*I_pick + b，拉平曝光差（文件 §2）。"""
    m = valid > 0
    if m.sum() < 1000:
        return warped_L
    x = warped_L[m].astype(np.float64); y = dst_L[m].astype(np.float64)
    if x.std() < 1e-3:
        return warped_L
    a, b = np.polyfit(x, y, 1)
    return np.clip(a*warped_L.astype(np.float64)+b, 0, 255).astype(np.uint8)


def shadow_like(ratio_region):
    """陰影只改亮度不改結構 → 比值圖近乎常數（低變異係數）。"""
    if ratio_region.size < 20:
        return False
    mu = float(ratio_region.mean())
    if mu <= 1e-6:
        return False
    return float(ratio_region.std())/mu < 0.12


def analyze(pickup, ret):
    src, dst = load(pickup), load(ret)
    src, dst = shades_of_gray(src), shades_of_gray(dst)

    hm_r, hr_ret = highlight_mask(dst)
    _, hr_pick = highlight_mask(src)

    out = {"hl_ret": hr_ret, "hl_pick": hr_pick}

    res = {}
    for det in ("ORB", "SIFT"):
        w, v, inl = align(src, dst, det)
        res[det] = (w, v, inl)
        out[f"inl_{det}"] = inl
        out[f"ok_{det}"] = w is not None

    warped, valid, inl = res["SIFT"] if res["SIFT"][0] is not None else res["ORB"]
    if warped is None:
        out.update(align_ok=False, pair_score=None, n_comp=0, shadow_rejected=0)
        return out

    La = cv2.cvtColor(warped, cv2.COLOR_BGR2LAB)[:, :, 0]
    Lb = cv2.cvtColor(dst, cv2.COLOR_BGR2LAB)[:, :, 0]
    La = gain_compensate(La, Lb, valid)

    d = 1.0 - ssim_map(La, Lb)
    d[valid == 0] = 0.0
    d[hm_r > 0] = 0.0                      # §1 高光區排除
    B = 12
    d[:B, :] = 0; d[-B:, :] = 0; d[:, :B] = 0; d[:, -B:] = 0

    binary = (d > 0.55).astype(np.uint8)
    binary = cv2.morphologyEx(binary, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5)))
    binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8))
    n, labels, stats, _ = cv2.connectedComponentsWithStats(binary)

    ratio = (Lb.astype(np.float64)+1.0)/(La.astype(np.float64)+1.0)
    comps, shadow_rej = [], 0
    for i in range(1, n):
        x, y, w_, h_, area = stats[i]
        if area < 400:
            continue
        sel = labels == i
        if shadow_like(ratio[sel]):        # §1 陰影判別
            shadow_rej += 1
            continue
        md = float(d[sel].mean())
        comps.append(md*math.log(area))
    comps.sort(reverse=True)
    out.update(align_ok=True, inliers=inl,
               pair_score=(comps[0] if comps else 0.0),
               n_comp=len(comps), shadow_rejected=shadow_rej)
    return out


def main():
    rows, t0 = [], time.time()
    for i, p in enumerate(PAIRS):
        try:
            r = analyze(p["pickup"], p["return"])
        except Exception as e:
            r = {"align_ok": False, "pair_score": None, "error": str(e)[:80]}
        r.update(car=p["car"], angle=p["angle"], label=p["label"],
                 relabel=RELABELS.get((p["car"], p["angle"])))
        rows.append(r)
        if (i+1) % 20 == 0:
            print(f"  {i+1}/{len(PAIRS)}  ({time.time()-t0:.0f}s)", file=sys.stderr)
    (H/"cv_methodology_probe.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=1))
    print(f"DONE {len(rows)} rows in {time.time()-t0:.0f}s", file=sys.stderr)


if __name__ == "__main__":
    main()

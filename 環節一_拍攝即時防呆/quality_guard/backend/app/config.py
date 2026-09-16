"""品質檢查門檻值與模型檔案路徑。

門檻值的初始值來源分兩種，讀的時候要分清楚：

1. **已用真實資料校準**：模糊、亮度、車牌面積比例——這些是 M3/M4 用
   `validation/run_validation.py` 對 285 張真實照片跑出分布後訂的。
2. **尚未校準的初始猜測**：四階段整合（Stage 2 換 YOLO、Stage 3 換 CNN）之後
   新增或換算過的門檻，標了「待校準」，要重跑一次 validation 才算數。

## 模型檔案路徑：為什麼指向 `app_models/` 原路徑而不是複製一份

`整合計畫_四階段辨識.md` §Stage 2 允許兩種做法（複製到 `app/models/`，或用設定
檔指回 `app_models/`）。這裡選**指回原路徑**，理由：

- `best.pt`(6.2MB) + `cct_s_v2_global.onnx`(5.3MB) 是二進位檔，複製一份等於在
  git 裡多存 11.5MB 而且從此有兩份會各自漂移的權重，之後隊友更新模型時很容易
  只更新到其中一份。
- 兩個資料夾都在同一個 repo (`環節一_拍攝即時防呆/`) 底下，相對路徑穩定。

代價是 `quality_guard/backend/` 不能單獨搬走部署。真的要單獨部署時，用下面的
環境變數把路徑指到容器內的實際位置即可（Dockerfile 各自 COPY 進去）：

    IRENT_PLATE_DETECT_MODEL=/models/best.pt
    IRENT_PLATE_OCR_ONNX=/models/cct_s_v2_global.onnx
    IRENT_PLATE_OCR_CONFIG=/models/cct_s_v2_global_plate_config.yaml
    IRENT_VIEW_CLASSIFIER=/models/view_classifier.pt
"""

import os
from dataclasses import dataclass
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
# backend/ -> quality_guard/ -> 環節一_拍攝即時防呆/
STAGE1_DIR = BACKEND_DIR.parent.parent
APP_MODELS_DIR = STAGE1_DIR / "app_models"


def _model_path(env_var: str, default: Path) -> Path:
    override = os.environ.get(env_var)
    return Path(override).expanduser().resolve() if override else default


# Stage 2：隊友訓練的 YOLO 車牌偵測 + fast-plate-ocr 文字辨識
PLATE_DETECT_MODEL_PATH = _model_path(
    "IRENT_PLATE_DETECT_MODEL", APP_MODELS_DIR / "detect" / "best.pt"
)
PLATE_OCR_ONNX_PATH = _model_path(
    "IRENT_PLATE_OCR_ONNX", APP_MODELS_DIR / "ocr" / "cct_s_v2_global.onnx"
)
PLATE_OCR_CONFIG_PATH = _model_path(
    "IRENT_PLATE_OCR_CONFIG", APP_MODELS_DIR / "ocr" / "cct_s_v2_global_plate_config.yaml"
)

# Stage 3：本專案訓練的四角視角分類器（MobileNetV2 transfer learning）
VIEW_CLASSIFIER_PATH = _model_path(
    "IRENT_VIEW_CLASSIFIER", BACKEND_DIR / "app" / "models" / "view_classifier.pt"
)

# 推論裝置。YOLO 吃 ultralytics 的 device 字串（None=自動、cpu、mps、0）；
# OCR 走 onnxruntime，只吃 auto/cpu/cuda（Apple Silicon 沒有 mps 後端，維持 cpu）。
PLATE_DETECT_DEVICE = os.environ.get("IRENT_PLATE_DETECT_DEVICE") or None
PLATE_OCR_DEVICE = os.environ.get("IRENT_PLATE_OCR_DEVICE", "cpu")


@dataclass
class QualityThresholds:
    # --- 第 1 關：基本可讀性 ---
    #
    # 只擋「解析度不足」與「整張沒有內容」。模糊與亮度**預設不擋關**，只在第 1 關的
    # 結論裡標註供參考——判斷「這張照片能不能用」的工作交給第 2 關的車牌偵測。
    #
    # 為什麼這樣改：實測 285 張真實照片中，被舊的模糊/亮度規則擋掉的 39 張裡，有
    # **12 張的車牌其實讀得完全正確**（夜間停車場的照片偏暗，但車牌有反光板，反而
    # 比車身清楚）。用「整張照片的平均亮度」去否決一張車牌清晰可讀的照片並不合理。
    # 代價是另外 3 張會讀錯 1 個字元而放行——換回 12 張好照片，划算。
    #
    # 想改回擋關（例如之後要求更嚴格的存證品質）就把對應的旗標打開。
    stage1_blocks_on_blur: bool = False
    stage1_blocks_on_brightness: bool = False

    # 以下門檻仍然會計算並顯示（標註「偏暗」「偏模糊」），只是預設不擋關。
    # 數值是 M3 用 285 張真實照片校準的，改回擋關時可直接沿用。
    blur_threshold: float = 100.0

    brightness_min_mean: float = 0.25
    brightness_max_mean: float = 0.85
    brightness_max_dark_ratio: float = 0.55
    brightness_max_bright_ratio: float = 0.35

    min_width_px: int = 480
    min_height_px: int = 270

    # --- Stage 2：車牌偵測 + OCR ---
    # YOLO 偵測信心值門檻。沿用 app_models/main.py CLI 的預設 0.25。
    plate_detect_min_conf: float = 0.25
    # YOLO 推論解析度。對 285 張真實照片實測（多數是 1280x720 / 800x600 手機直拍）：
    #   imgsz=640  偵測率 0.596   27 ms/張
    #   imgsz=960  偵測率 0.642   47 ms/張   <- 取這個
    #   imgsz=1280 偵測率 ~0.64   90 ms/張（再往上開始掉，1600 明顯變差）
    # 960 是準確率/延遲的甜蜜點，仍遠低於 plan.md §11 的 <1 秒目標。
    #
    # ⚠️ 上面這組偵測率是**加入方向防護網之前**量的。加了之後同一批照片是 0.747
    # （防護網救回 30 張橫躺的照片，見 checks/orientation.py）。解析度之間的相對
    # 關係沒有重新量過，但 640→960 那 4.6 個百分點跟方向問題是兩件獨立的事：
    # 橫躺的照片解析度開再大也一樣測不到。
    plate_detect_imgsz: int = 960
    # 裁切車牌時往外多留的邊界比例，餵給 OCR 用（沿用 app_models 的 0.08）。
    plate_crop_padding: float = 0.08

    # OCR 平均字元機率門檻（0-1）。
    # ⚠️ 尺度變更警告：舊的 pytesseract 版本這個欄位叫 plate_min_confidence，
    # 刻度是 0-100；換成 fast-plate-ocr 之後是 0-1 的字元機率平均值，
    # 兩者不能直接沿用數字，所以欄位名稱一併改掉避免有人照抄舊值。
    # 已用 285 張真實照片校準：165 張有偵測到車牌的樣本，OCR 信心值
    # p1=0.59 / p2=0.64 / p10=0.80 / 中位數=1.00，訂在 0.40 落在 p1 以下，
    # 只擋掉真的糊到讀不出字的那 1%，不會誤擋正常照片。
    plate_ocr_min_confidence: float = 0.40

    # 合法的車牌字元數（不含分隔線）。讀出來的字數不在這個集合裡，代表車牌很可能
    # 只拍到一半（頭尾被裁掉），回 PLATE_INCOMPLETE 要使用者重拍。
    #
    # 用 285 張真實照片校準：真值車牌 100% 都是 7 碼（3 英文 + 4 數字）。OCR 讀出
    # 7 碼的 131 張裡有 125 張（95%）完全正確；讀出非 7 碼的 34 張則是 **0 張正確**，
    # 內容多半像 RDG857 / RDR635（尾碼被切）或 FH8052 / JG8578（首碼被切）。
    # 也就是這條規則在這批資料上幾乎沒有誤擋成本，卻能攔下 34 張錯讀。
    #
    # ⚠️ 台灣還有 6 碼車牌格式（1234-AB、AB-1234），這批車隊沒有，但若之後車隊納入
    # 這類車輛，要改成 frozenset({6, 7})，否則那些車會被永久擋住。
    plate_text_valid_lengths: frozenset[int] = frozenset({7})

    # 車牌 bbox 面積佔整張圖片面積的比例，用來近似遠近判斷。
    # 已用 YOLO 的 bbox 重新校準（舊值 0.0007/0.12 是傳統 CV 候選框的分布，
    # 那種框帶 18%/25% padding，跟現在的緊框加 8% padding 不能混用）。
    #
    # 校準依據不是純粹看分位數，而是看「OCR 從哪裡開始讀不出來」——
    # 285 張真實照片中 165 張有偵測到車牌，依面積比例分桶的 OCR 正確率：
    #     [0.000, 0.005)   n=2    正確率 0.00   平均信心 0.52
    #     [0.005, 0.008)   n=12   正確率 0.50   平均信心 0.91
    #     [0.008, 0.012)   n=25   正確率 0.64   平均信心 0.92
    #     [0.012, 0.020)   n=51   正確率 0.86   平均信心 0.99
    #     [0.020, 0.030)   n=48   正確率 0.81   平均信心 0.98
    #     [0.030, 0.050)   n=19   正確率 0.74   平均信心 0.97
    #     [0.050, 1.000)   n=8    正確率 0.75   平均信心 0.93
    # 0.005 以下正確率直接掉到 0，就把 TOO_FAR 訂在那裡；再往上訂（例如 0.008）
    # 會連帶擋掉一半以上其實讀得對的照片，不划算。
    plate_area_ratio_min: float = 0.005  # 低於此比例視為太遠
    # ⚠️ 上限沒有真實資料支撐：這批照片的面積比例最大只到 0.077，高比例區間也
    # 沒有看到 OCR 變差，所以這條規則在真實資料上一次都沒觸發過。留 0.12 當保險絲，
    # 真正擋下「拍太近」的是找不到車牌時的平滑色塊判斷（見 framing.py）。
    plate_area_ratio_max: float = 0.12  # 高於此比例視為太近/裁切

    # 偵測不到車牌時，要不要試著把圖轉 90 度再測一次（見 checks/orientation.py）。
    # 正常的手機上傳走 EXIF 就已經正立，這條路徑不會觸發；擋的是 EXIF 被上傳流程
    # 清掉、但像素沒跟著轉正的照片——那種照片會讓車牌偵測完全失效，使用者陷入
    # 「怎麼重拍都說沒偵測到車牌」的死路。
    # 代價只加在「第一次偵測失敗」的照片上（最多多兩次 YOLO 推論，約 47ms/次）。
    enable_orientation_probe: bool = True

    # 車牌偵測沒過時，還要不要繼續跑視角分類？
    # False（預設）＝闖關式：前一關沒過就不跑下一關，前端會把「四角辨識」顯示成
    #   「未執行」。這是目前產品要的流程。
    # True ＝ 盡量多給資訊：即使車牌沒抓到也回報角度。實測沒偵測到車牌的 81 張真實
    #   照片，視角分類仍有 91.4% 正確率（有抓到車牌的是 97.0%），所以這個選項不是
    #   在賭運氣；純粹是產品要「闖關」還是要「一次講完」的取捨。
    #
    # ⚠️ 打開這個選項會多一個新版模型才有的風險：方向防護網是靠「偵測到車牌」來
    # 確認方向的，車牌沒偵測到就代表**方向沒被確認過**。新版分類器對橫躺輸入的
    # 準確率只有 32.7%，且 view_confidence_min 只擋得下其中 49%——也就是橫躺又沒
    # 車牌的照片有約 35% 會被很有信心地答錯。上一版模型沒這個問題（它意外地能抗
    # 旋轉），取捨理由見 README「已知限制」。
    run_view_stage_when_plate_missing: bool = False

    # --- Stage 4：視角分類信心值防線 ---
    # 低於此值時回 UNCERTAIN_VIEW，不硬說使用者拍錯角度。
    #
    # 已用 285 張真實照片看過分布：走到第 3 關的 174 張，top-1 機率
    # 中位數 0.972、p10 0.758、最低 0.474，訂在 0.60 只觸發 7 次。
    # 維持 0.60 而不調高：這條防線的價值不在闖關模式（能走到第 3 關的照片構圖
    # 都正常，分類器幾乎永遠很有信心，包含它答錯的時候），而在
    # run_view_stage_when_plate_missing 打開、或方向沒被確認的照片上。
    view_confidence_min: float = 0.60


DEFAULT_THRESHOLDS = QualityThresholds()

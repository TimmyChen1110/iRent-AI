// 後端網址預設用目前頁面的 host + 8000 埠組出來，這樣不管是 localhost 開還是手機
// 用區網 IP 開（例如 http://192.168.1.23:5500），都會打到同一台機器的後端。
//
// 後端跑在別的埠時用網址參數覆寫，不必改程式（同一台機器上同時有舊版服務佔著
// 8000 時很需要這個）：
//     ?api=8010                      → http://<同一個 host>:8010
//     ?api=http://192.168.1.23:8010  → 完整網址（後端在另一台機器）
function resolveApiBase() {
  const override = new URLSearchParams(location.search).get("api");
  if (!override) return `${location.protocol}//${location.hostname}:8000`;
  if (/^https?:\/\//.test(override)) return override.replace(/\/$/, "");
  return `${location.protocol}//${location.hostname}:${override}`;
}

const API_BASE = resolveApiBase();

const dropzone = document.getElementById("dropzone");
const dropzoneEmpty = document.getElementById("dropzone-empty");
const preview = document.getElementById("preview");
const fileInput = document.getElementById("file-input");
const resetBtn = document.getElementById("reset-btn");
const viewSelect = document.getElementById("view-select");
const statusEl = document.getElementById("status");
const resultEl = document.getElementById("result");

let objectUrl = null;
// 目前這張照片。貼上/拖放進來的檔案不會出現在 fileInput.files，所以自己留一份，
// 換「指定角度」時才有辦法重跑同一張。
let currentFile = null;

// 每個錯誤碼補一句「為什麼會這樣」，讓使用者知道下一步該怎麼做，
// 而不是只看到一句「請重拍」。文案跟後端 ERROR_MESSAGES 是互補的：
// 後端那句講「要做什麼」，這裡講「為什麼」。
const ERROR_HINTS = {
  IMAGE_INVALID: "檔案不是有效的圖片，或整張畫面沒有內容（全黑／全白）。",
  LOW_RESOLUTION: "解析度太低，放大後看不清楚車牌與車損細節。",
  IMAGE_BLURRY: "畫面細節不足，通常是手震或對焦沒完成就按下快門。",
  TOO_DARK: "整體曝光不足，車身與車牌的細節會被暗部吃掉。",
  TOO_BRIGHT: "畫面過曝，白色車身與車牌反光會糊成一片。",
  PLATE_NOT_FOUND: "畫面裡找不到完整車牌——常見原因是車牌被裁到畫面邊緣外。",
  TOO_FAR: "車牌在畫面中佔比太小，放大後會看不清楚號碼。",
  TOO_CLOSE: "拍得太近，車輛與車牌沒有完整入鏡。",
  PLATE_TEXT_UNREADABLE: "車牌位置找得到，但字元辨識信心太低，通常是太糊或角度太斜。",
  PLATE_INCOMPLETE: "讀出來的字數不足，代表車牌的頭或尾被畫面邊緣裁掉了。",
  WRONG_VIEW: "系統判斷的角度跟指定角度不同，可能站錯位置了。",
  UNCERTAIN_VIEW: "畫面資訊不足以判斷是車輛的哪一角，通常是拍太近或只拍到局部。",
};

const STAGE_ICONS = { passed: "✅", failed: "❌", skipped: "⏸" };
const STAGE_STATUS_TEXT = { passed: "通過", failed: "未通過", skipped: "未執行" };

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);
}

function percent(value) {
  return value === null || value === undefined ? "—" : `${(value * 100).toFixed(1)}%`;
}

/**
 * 把原圖畫進 canvas 並框出車牌位置。
 *
 * 用 canvas 重畫而不是拿一層透明 overlay 疊在 <img> 上：overlay 要一直追著圖片的
 * 版面位置跑（視窗縮放、圖片載入時序、外層置中都會影響），而這裡的圖片是固定的
 * 檢查結果，直接畫成一張圖最穩，也方便使用者截圖回報。
 */
function renderAnnotatedPhoto(bbox, rotation = 0) {
  if (!preview.naturalWidth) return "";

  // rotation 是後端方向防護網套用的逆時針角度（見 backend/app/checks/orientation.py）。
  // 不是 0 的時候 bbox 是「轉正後」的座標，預覽圖必須先轉同樣的角度，框才會對齊。
  const swapped = rotation === 90 || rotation === 270;
  const sourceWidth = swapped ? preview.naturalHeight : preview.naturalWidth;
  const sourceHeight = swapped ? preview.naturalWidth : preview.naturalHeight;

  const maxWidth = 520;
  const scale = Math.min(1, maxWidth / sourceWidth);
  const canvas = document.createElement("canvas");
  canvas.width = Math.round(sourceWidth * scale);
  canvas.height = Math.round(sourceHeight * scale);

  const ctx = canvas.getContext("2d");
  if (rotation) {
    // 先把原點移到轉正後畫布的中心，轉完再以原圖尺寸置中畫上去。
    // canvas 的 rotate() 是順時針，所以逆時針 rotation 度要傳負值。
    ctx.translate(canvas.width / 2, canvas.height / 2);
    ctx.rotate((-rotation * Math.PI) / 180);
    const drawWidth = Math.round(preview.naturalWidth * scale);
    const drawHeight = Math.round(preview.naturalHeight * scale);
    ctx.drawImage(preview, -drawWidth / 2, -drawHeight / 2, drawWidth, drawHeight);
    ctx.setTransform(1, 0, 0, 1, 0, 0);
  } else {
    ctx.drawImage(preview, 0, 0, canvas.width, canvas.height);
  }

  if (bbox) {
    const [x1, y1, x2, y2] = bbox.map((v) => v * scale);
    const w = x2 - x1;
    const h = y2 - y1;

    // 外圈深色 + 內圈亮綠，讓框在白色車身和深色柏油上都看得見。
    ctx.lineWidth = 5;
    ctx.strokeStyle = "rgba(0, 0, 0, 0.55)";
    ctx.strokeRect(x1, y1, w, h);
    ctx.lineWidth = 3;
    ctx.strokeStyle = "#22c55e";
    ctx.strokeRect(x1, y1, w, h);

    const label = "車牌";
    ctx.font = "600 13px -apple-system, system-ui, sans-serif";
    const padding = 5;
    const textWidth = ctx.measureText(label).width;
    // 框太靠近上緣時，標籤改畫在框內側，不然會被裁掉。
    const labelY = y1 - 20 >= 0 ? y1 - 20 : y1 + 2;
    ctx.fillStyle = "#22c55e";
    ctx.fillRect(x1, labelY, textWidth + padding * 2, 18);
    ctx.fillStyle = "#06240f";
    ctx.fillText(label, x1 + padding, labelY + 13);
  }

  return `<img class="annotated" src="${canvas.toDataURL("image/jpeg", 0.9)}"
    alt="標示車牌位置的照片" />`;
}

function renderStageErrors(errors) {
  if (!errors.length) return "";
  return `<ul class="problems">${errors
    .map((error) => {
      const hint = ERROR_HINTS[error.code] || "";
      return `<li><span class="msg">${escapeHtml(error.message)}
        ${hint ? `<span class="why">${escapeHtml(hint)}</span>` : ""}</span></li>`;
    })
    .join("")}</ul>`;
}

function renderStage(stage, index, data) {
  const icon = STAGE_ICONS[stage.status] || "•";
  const statusText = STAGE_STATUS_TEXT[stage.status] || stage.status;

  let extra = "";
  // 第 2 關通過時，把標了車牌框的照片放在這一關底下——這是這一關的「證據」。
  if (stage.id === "plate" && stage.status !== "skipped" && data.debug.plate_bbox) {
    extra = renderAnnotatedPhoto(data.debug.plate_bbox, data.debug.orientation_rotation || 0);
  }
  // 第 3 關無論過不過，只要跑過就把判定結果與機率分布攤出來。
  if (stage.id === "view" && stage.status !== "skipped") {
    const probabilities = data.debug.view_probabilities || [];
    if (probabilities.length) {
      extra = `<div class="bars">${probabilities
        .map(
          (p) => `<div class="bar-row">
            <span class="bar-label">${escapeHtml(p.label)}</span>
            <span class="bar-track"><span class="bar-fill" style="width:${(p.probability * 100).toFixed(1)}%"></span></span>
            <span class="bar-value">${percent(p.probability)}</span>
          </div>`
        )
        .join("")}</div>`;
    }
  }

  return `<li class="stage stage-${stage.status}">
    <div class="stage-head">
      <span class="stage-icon">${icon}</span>
      <span class="stage-name"><span class="stage-no">第 ${index + 1} 關</span>${escapeHtml(stage.name)}</span>
      <span class="stage-status">${statusText}</span>
    </div>
    ${stage.summary ? `<p class="stage-summary">${escapeHtml(stage.summary)}</p>` : ""}
    ${renderStageErrors(stage.errors || [])}
    ${extra}
  </li>`;
}

function renderDebug(data) {
  const debug = data.debug;
  const rows = [
    ["實際跑到的內部階段", (debug.stages_run || []).join(" → ")],
    ["模糊分數（越高越銳利）", debug.blur_score?.toFixed(1)],
    ["平均亮度 0-1", debug.brightness?.mean?.toFixed(3)],
    ["車牌偵測信心（YOLO）", debug.plate_detect_confidence == null ? null : percent(debug.plate_detect_confidence)],
    ["車牌面積佔畫面比例", debug.plate_area_ratio?.toFixed(5)],
    ["車牌 bbox", debug.plate_bbox ? `[${debug.plate_bbox.join(", ")}]` : null],
    ["方向防護網旋轉角度", debug.orientation_rotation ? `逆時針 ${debug.orientation_rotation}°` : null],
    ["模型原始角度標籤", debug.view_model_label],
    ["車外/車內猜測（僅供參考）", debug.exterior_interior_guess],
    ["後端處理耗時", `${debug.elapsed_ms} ms`],
  ]
    .filter(([, value]) => value !== null && value !== undefined && value !== "")
    .map(([key, value]) => `<tr><th>${escapeHtml(key)}</th><td>${escapeHtml(value)}</td></tr>`)
    .join("");

  return `<details class="debug">
    <summary>技術細節（demo 用）</summary>
    <table class="debug-table">${rows}</table>
  </details>`;
}

function renderResult(data) {
  const stages = data.stages || [];
  const failed = stages.find((s) => s.status === "failed");
  const verdict = data.passed
    ? `<div class="verdict pass">✅ 三關全過，這張照片合格
         <span class="score">品質分數 ${data.quality_score}</span></div>`
    : `<div class="verdict fail">❌ 卡在「${escapeHtml(failed ? failed.name : "檢查")}」，請重拍
         <span class="score">品質分數 ${data.quality_score}</span></div>`;

  resultEl.innerHTML =
    verdict +
    `<ol class="stages">${stages.map((s, i) => renderStage(s, i, data)).join("")}</ol>` +
    renderDebug(data);
  resultEl.hidden = false;
}

function renderError(message) {
  resultEl.innerHTML = `<div class="verdict fail">⚠️ 無法完成檢查</div>
    <p>${escapeHtml(message)}</p>
    <p class="hint">目前 API 位置：${escapeHtml(API_BASE)}。
    請確認後端有啟動（<code>uvicorn app.main:app --host 0.0.0.0 --port 8000</code>），
    手機測試時電腦與手機要在同一個網路。</p>`;
  resultEl.hidden = false;
}

async function submit(file) {
  statusEl.textContent = "分析中…";
  resultEl.hidden = true;

  try {
    const imageBase64 = await fileToBase64(file);
    const payload = { image_base64: imageBase64 };
    // 空字串代表「不指定角度」，這時不要送 required_view，後端才會跳過 WRONG_VIEW。
    if (viewSelect.value) payload.required_view = viewSelect.value;

    const response = await fetch(`${API_BASE}/api/photo-quality/check`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!response.ok) throw new Error(`API 回傳狀態碼 ${response.status}`);

    const data = await response.json();
    renderResult(data);
    statusEl.textContent = data.passed ? "檢查完成：合格" : "檢查完成：請依提示重拍";
  } catch (err) {
    renderError(err.message);
    statusEl.textContent = "檢查失敗";
  }
}

function fileToBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result.split(",")[1]);
    reader.onerror = () => reject(reader.error || new Error("讀取檔案失敗"));
    reader.readAsDataURL(file);
  });
}

async function showPreview(file) {
  if (objectUrl) URL.revokeObjectURL(objectUrl);
  objectUrl = URL.createObjectURL(file);

  await new Promise((resolve, reject) => {
    preview.onload = resolve;
    preview.onerror = () => reject(new Error("這個檔案不是瀏覽器能顯示的圖片"));
    preview.src = objectUrl;
  });

  preview.classList.add("active");
  dropzoneEmpty.hidden = true;
  resetBtn.disabled = false;
}

async function handleFile(file) {
  if (!file) return;
  if (!file.type.startsWith("image/")) {
    statusEl.textContent = `「${file.name || "這個檔案"}」不是圖片檔`;
    return;
  }
  try {
    await showPreview(file);
  } catch (err) {
    statusEl.textContent = err.message;
    return;
  }
  currentFile = file;
  await submit(file);
}

function reset() {
  if (objectUrl) URL.revokeObjectURL(objectUrl);
  objectUrl = null;
  preview.src = "";
  preview.classList.remove("active");
  dropzoneEmpty.hidden = false;
  resultEl.hidden = true;
  resetBtn.disabled = true;
  currentFile = null;
  fileInput.value = "";
  statusEl.textContent = "尚未選擇照片";
}

fileInput.addEventListener("change", (event) => handleFile(event.target.files?.[0]));
resetBtn.addEventListener("click", reset);

// 貼上：綁在 document 上，使用者不用先點進某個欄位就能按 ⌘V。
document.addEventListener("paste", (event) => {
  const item = [...(event.clipboardData?.items || [])].find((i) => i.type.startsWith("image/"));
  if (!item) return;
  event.preventDefault();
  handleFile(item.getAsFile());
});

// 拖放
["dragenter", "dragover"].forEach((type) =>
  dropzone.addEventListener(type, (event) => {
    event.preventDefault();
    dropzone.classList.add("dragover");
  })
);
["dragleave", "drop"].forEach((type) =>
  dropzone.addEventListener(type, (event) => {
    event.preventDefault();
    dropzone.classList.remove("dragover");
  })
);
dropzone.addEventListener("drop", (event) => handleFile(event.dataTransfer?.files?.[0]));
dropzone.addEventListener("click", () => fileInput.click());
dropzone.addEventListener("keydown", (event) => {
  if (event.key === "Enter" || event.key === " ") {
    event.preventDefault();
    fileInput.click();
  }
});

// 換指定角度時重跑同一張照片，方便 demo 對照「指定對 vs 指定錯」的差別。
viewSelect.addEventListener("change", () => {
  if (currentFile) submit(currentFile);
});

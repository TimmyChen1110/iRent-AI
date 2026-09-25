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
const CHECK_ENDPOINT = `${API_BASE}/api/photo-quality/check`;

// ---------- DOM ----------
const camera = document.getElementById("camera");
const cameraEmpty = document.getElementById("camera-empty");
const cameraPill = document.getElementById("camera-pill");
const cameraOverlay = document.getElementById("camera-overlay");
const preview = document.getElementById("preview");
const fileInput = document.getElementById("file-input"); // capture=environment（手機開相機）
const albumInput = document.getElementById("album-input"); // 相簿／檔案
const cameraBtn = document.getElementById("camera-btn");
const albumBtn = document.getElementById("album-btn");
const resetBtn = document.getElementById("reset-btn");
const angleChips = document.getElementById("angle-chips");
const statusEl = document.getElementById("status");
const resultEl = document.getElementById("result");

// ---------- 狀態 ----------
let objectUrl = null;
// 目前這張照片。貼上/拖放進來的檔案不會出現在 fileInput.files，所以自己留一份，
// 換「指定角度」時才有辦法重跑同一張。
let currentFile = null;
// 目前指定角度。**這個字串會原封不動送給 API 的 required_view**，必須跟後端
// view_taxonomy.RequiredView 的中文值一致；空字串代表「不指定」。
let currentView = "";
// 分析中旗標 + 請求流水號：送出新請求時舊的會被 abort，晚回來的舊回應也會被丟掉。
let busy = false;
let requestSeq = 0;
let inflight = null; // AbortController

// ---------- 文案 ----------
// 顯示用的角度名稱。只影響畫面，不影響送給 API 的值。
const VIEW_DISPLAY = {
  "": "未指定角度",
  左前: "左前方",
  右前: "右前方",
  左後: "左後方",
  右後: "右後方",
  前車內: "前座車內",
  後車內: "後座車內",
};

// 三關的顯示名稱（後端 stage.name 是「基本可讀性／車牌偵測／四角辨識」，
// 這裡換成使用者語言；資料結構與順序完全照後端 stages）。
const STAGE_LABELS = { readability: "基本可讀性", plate: "車牌辨識", view: "拍攝角度" };
const STAGE_STATUS_TEXT = { passed: "通過", failed: "未通過", skipped: "未執行" };

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

// 第 1 關的 advisory（後端 debug.stage1_advisories 的原句 → 顯示用短語）
const ADVISORY_LABELS = {
  照片偏暗: "光線稍暗",
  照片偏亮: "光線偏亮",
  畫面偏模糊: "畫面稍模糊",
};

// ---------- Inline SVG icons（不用 emoji，可套主題色） ----------
const SVG_ATTRS =
  'viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"';
const ICONS = {
  check: `<svg ${SVG_ATTRS} width="18" height="18"><path d="M5 12.5l4.5 4.5L19 7.5"/></svg>`,
  x: `<svg ${SVG_ATTRS} width="18" height="18"><path d="M6 6l12 12M18 6L6 18"/></svg>`,
  alert: `<svg ${SVG_ATTRS} width="18" height="18"><path d="M12 8v5M12 16.5v.5"/><path d="M10.3 3.9L2.7 17.1A2 2 0 0 0 4.4 20h15.2a2 2 0 0 0 1.7-2.9L13.7 3.9a2 2 0 0 0-3.4 0z"/></svg>`,
  minus: `<svg ${SVG_ATTRS} width="18" height="18"><path d="M6 12h12"/></svg>`,
  camera: `<svg ${SVG_ATTRS} width="20" height="20" stroke-width="2"><path d="M4 8.5A2.5 2.5 0 0 1 6.5 6H8l1.2-1.8A1 1 0 0 1 10 3.8h4a1 1 0 0 1 .8.4L16 6h1.5A2.5 2.5 0 0 1 20 8.5v8a2.5 2.5 0 0 1-2.5 2.5h-11A2.5 2.5 0 0 1 4 16.5z"/><circle cx="12" cy="12.5" r="3.5"/></svg>`,
};
const STAGE_ICONS = { passed: ICONS.check, failed: ICONS.x, skipped: ICONS.minus };

// 大尺寸版本（結果卡）
function bigIcon(name) {
  return ICONS[name].replace(/width="\d+" height="\d+"/, 'width="30" height="30"');
}

// ---------- 小工具 ----------
function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);
}

function percent(value, digits = 0) {
  return value === null || value === undefined ? "—" : `${(value * 100).toFixed(digits)}%`;
}

function viewDisplay(view) {
  return VIEW_DISPLAY[view] || view || "";
}

// ---------- 角度選擇 ----------
function setView(view) {
  currentView = view;
  for (const chip of angleChips.querySelectorAll(".chip")) {
    chip.setAttribute("aria-checked", chip.dataset.view === view ? "true" : "false");
  }
  const label = view ? `目前拍攝：${viewDisplay(view)}` : VIEW_DISPLAY[""];
  cameraPill.textContent = label;
  cameraPill.classList.toggle("is-set", Boolean(view));
}

angleChips.addEventListener("click", (event) => {
  const chip = event.target.closest(".chip");
  if (!chip || busy) return;
  const view = chip.dataset.view ?? "";
  if (view === currentView) return;
  setView(view);
  // 換指定角度時重跑同一張照片，方便對照「指定對 vs 指定錯」的差別。
  if (currentFile) submit(currentFile);
});

// ---------- 忙碌狀態 ----------
function setBusy(on) {
  busy = on;
  cameraOverlay.hidden = !on;
  camera.setAttribute("aria-busy", on ? "true" : "false");
  for (const chip of angleChips.querySelectorAll(".chip")) chip.disabled = on;
  // <label> 不能 disabled：把對應 input 停掉、再加樣式，兩層保險。
  fileInput.disabled = on;
  albumInput.disabled = on;
  cameraBtn.classList.toggle("is-disabled", on);
  albumBtn.classList.toggle("is-disabled", on);
  cameraBtn.setAttribute("aria-disabled", on ? "true" : "false");
  albumBtn.setAttribute("aria-disabled", on ? "true" : "false");
  resetBtn.disabled = on || !currentFile;
}

// ---------- 車牌框 ----------
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

// ---------- 結果渲染 ----------
function renderStageErrors(errors) {
  if (!errors.length) return "";
  return `<ul class="problems">${errors
    .map((error) => {
      const hint = ERROR_HINTS[error.code] || "";
      return `<li><span class="msg">${escapeHtml(error.message)}</span>
        ${hint ? `<span class="why">${escapeHtml(hint)}</span>` : ""}</li>`;
    })
    .join("")}</ul>`;
}

function renderAdvisoryPills(advisories) {
  if (!advisories || !advisories.length) return "";
  return `<div class="pills">${advisories
    .map(
      (a) =>
        `<span class="pill pill-warn">${ICONS.alert.replace(/width="\d+" height="\d+"/, 'width="12" height="12"')} ${escapeHtml(ADVISORY_LABELS[a] || a)}</span>`
    )
    .join("")}</div>`;
}

// 每一關在卡片中間那行的一句話。失敗原因走 errors，不在這裡重複。
function stageLine(stage, data) {
  const advisories = data.debug.stage1_advisories || [];
  if (stage.status === "skipped") {
    return stage.summary || "前一關沒過，尚未執行";
  }
  if (stage.id === "readability") {
    if (stage.status === "failed") return "照片無法判讀";
    return advisories.length ? "可以判讀，但光線或清晰度略差" : "清晰度與亮度正常";
  }
  if (stage.id === "plate") {
    if (data.plate_text) return stage.status === "passed" ? "已辨識到車牌" : "有讀到車牌，但不完整或不夠清楚";
    if (data.debug.plate_bbox) return "有找到車牌位置，但讀不出號碼";
    return "畫面中沒有找到車牌";
  }
  if (stage.id === "view") {
    if (data.detected_view) {
      return stage.status === "passed" ? "拍攝角度符合" : `判定為「${viewDisplay(data.detected_view)}」`;
    }
    return "無法判斷拍攝角度";
  }
  return stage.summary || "";
}

function renderPlateHero(data) {
  if (!data.plate_text) return "";
  return `<div class="plate-hero">
    <span class="plate-label">辨識到車牌</span>
    <span class="plate-number">${escapeHtml(data.plate_text)}</span>
    <span class="plate-meta">辨識信心 ${percent(data.plate_confidence)}</span>
  </div>`;
}

function renderViewHero(data) {
  const probabilities = data.debug.view_probabilities || [];
  const hero = data.detected_view
    ? `<div class="view-hero">
        <span class="view-label">判定角度</span>
        <span class="view-value">${escapeHtml(viewDisplay(data.detected_view))}<small>${percent(data.view_confidence)}</small></span>
      </div>`
    : "";
  if (!probabilities.length) return hero;
  const topLabel = probabilities.reduce((a, b) => (b.probability > a.probability ? b : a)).label;
  const bars = `<div class="bars">${probabilities
    .map(
      (p) => `<div class="bar-row ${p.label === topLabel ? "top" : ""}">
        <span class="bar-label">${escapeHtml(viewDisplay(p.label))}</span>
        <span class="bar-track"><span class="bar-fill" style="width:${(p.probability * 100).toFixed(1)}%"></span></span>
        <span class="bar-value">${percent(p.probability)}</span>
      </div>`
    )
    .join("")}</div>`;
  return hero + bars;
}

function renderStage(stage, index, data) {
  const icon = STAGE_ICONS[stage.status] || ICONS.minus;
  const statusText = STAGE_STATUS_TEXT[stage.status] || stage.status;
  const name = STAGE_LABELS[stage.id] || stage.name;

  const extras = [];
  if (stage.status !== "skipped") {
    if (stage.id === "readability") {
      const pills = renderAdvisoryPills(data.debug.stage1_advisories);
      if (pills) extras.push(pills);
    }
    if (stage.id === "plate") {
      const hero = renderPlateHero(data);
      if (hero) extras.push(hero);
      // 第 2 關通過時，把標了車牌框的照片放在這一關底下——這是這一關的「證據」。
      if (data.debug.plate_bbox) {
        extras.push(renderAnnotatedPhoto(data.debug.plate_bbox, data.debug.orientation_rotation || 0));
      }
    }
    if (stage.id === "view") {
      const hero = renderViewHero(data);
      if (hero) extras.push(hero);
    }
  }
  const errors = renderStageErrors(stage.errors || []);
  if (errors) extras.unshift(errors);

  return `<li class="stage stage-${stage.status}">
    <span class="stage-icon">${icon}</span>
    <div class="stage-body">
      <div class="stage-name"><span class="stage-no">${index + 1}</span>${escapeHtml(name)}</div>
      <p class="stage-summary">${escapeHtml(stageLine(stage, data))}</p>
    </div>
    <span class="stage-status">${statusText}</span>
    ${extras.length ? `<div class="stage-extra">${extras.join("")}</div>` : ""}
  </li>`;
}

function renderDebug(data) {
  const debug = data.debug;
  const rows = [
    ["實際跑到的內部階段", (debug.stages_run || []).join(" → ")],
    ...(data.stages || []).map((s) => [`${STAGE_LABELS[s.id] || s.name} 原始結論`, s.summary]),
    ["模糊分數（越高越銳利）", debug.blur_score?.toFixed(1)],
    ["平均亮度 0-1", debug.brightness?.mean?.toFixed(3)],
    ["車牌偵測信心（YOLO）", debug.plate_detect_confidence == null ? null : percent(debug.plate_detect_confidence, 1)],
    ["車牌 OCR 信心", data.plate_confidence == null ? null : percent(data.plate_confidence, 1)],
    ["車牌面積佔畫面比例", debug.plate_area_ratio?.toFixed(5)],
    ["車牌 bbox", debug.plate_bbox ? `[${debug.plate_bbox.join(", ")}]` : null],
    ["方向防護網旋轉角度", debug.orientation_rotation ? `逆時針 ${debug.orientation_rotation}°` : null],
    ["模型原始角度標籤", debug.view_model_label],
    ["角度 top-1 機率", data.view_confidence == null ? null : percent(data.view_confidence, 1)],
    ["車外/車內猜測（僅供參考）", debug.exterior_interior_guess],
    ["品質分數（0-1）", data.quality_score],
    ["後端處理耗時", `${debug.elapsed_ms} ms`],
    ["API", CHECK_ENDPOINT],
  ]
    .filter(([, value]) => value !== null && value !== undefined && value !== "")
    .map(([key, value]) => `<tr><th>${escapeHtml(key)}</th><td>${escapeHtml(value)}</td></tr>`)
    .join("");

  return `<details class="debug">
    <summary>技術細節</summary>
    <table class="debug-table">${rows}</table>
  </details>`;
}

function passMessage(data) {
  const stages = data.stages || [];
  const skipped = stages.filter((s) => s.status === "skipped").length;
  if (skipped) return "車內照片可讀性通過（車內視角不檢查車牌與角度）";
  if (data.required_view) return "照片清晰，拍攝角度符合要求";
  if (data.detected_view) return `照片清晰，判定角度為「${viewDisplay(data.detected_view)}」`;
  return "照片清晰，可以使用";
}

function renderResult(data) {
  const stages = data.stages || [];
  const failed = stages.find((s) => s.status === "failed");
  const score = Math.round((data.quality_score || 0) * 100);
  const changeAngleBtn = currentView
    ? `<button type="button" class="btn btn-secondary" data-action="change-angle">更換拍攝角度</button>`
    : "";

  let card;
  if (data.passed) {
    card = `<div class="result-card pass">
      <div class="result-icon">${bigIcon("check")}</div>
      <h2 class="result-title">照片檢查通過</h2>
      <p class="result-msg">${escapeHtml(passMessage(data))}</p>
      <span class="badge">品質分數 ${score}</span>
      <div class="result-actions">
        <button type="button" class="btn btn-primary" data-action="retake">${ICONS.camera} 再拍一張</button>
        ${changeAngleBtn}
      </div>
    </div>`;
  } else {
    // 只講最重要的一句：第一個失敗關卡的第一個錯誤（後端文案本身就是可執行的動作）。
    const primary = failed?.errors?.[0]?.message || data.errors?.[0]?.message || "請重新拍攝";
    card = `<div class="result-card fail">
      <div class="result-icon">${bigIcon("alert")}</div>
      <h2 class="result-title">需要重新拍攝</h2>
      <p class="result-msg">${escapeHtml(primary)}</p>
      <span class="badge">品質分數 ${score}</span>
      <div class="result-actions">
        <button type="button" class="btn btn-primary" data-action="retake">${ICONS.camera} 重新拍攝</button>
        ${changeAngleBtn}
      </div>
    </div>`;
  }

  resultEl.innerHTML =
    card +
    `<ol class="stages">${stages.map((s, i) => renderStage(s, i, data)).join("")}</ol>` +
    renderDebug(data);
  resultEl.hidden = false;
}

function renderError(message) {
  resultEl.innerHTML = `<div class="result-card error">
      <div class="result-icon">${bigIcon("alert")}</div>
      <h2 class="result-title">目前無法完成照片檢查</h2>
      <p class="result-msg">請稍後再試一次</p>
      <div class="result-actions">
        <button type="button" class="btn btn-primary" data-action="retry">重新檢查</button>
        <button type="button" class="btn btn-secondary" data-action="retake">${ICONS.camera} 重新拍攝</button>
      </div>
    </div>
    <details class="debug">
      <summary>開發者資訊</summary>
      <pre class="debug-pre">${escapeHtml(
        `錯誤：${message}\nAPI：${CHECK_ENDPOINT}\n\n請確認後端有啟動：\n  uvicorn app.main:app --host 0.0.0.0 --port 8000\n手機測試時電腦與手機要在同一個網路；後端在別的埠時可用 ?api=<埠或網址> 覆寫。`
      )}</pre>
    </details>`;
  resultEl.hidden = false;
}

// 結果卡上的按鈕
resultEl.addEventListener("click", (event) => {
  const button = event.target.closest("[data-action]");
  if (!button || busy) return;
  const action = button.dataset.action;
  if (action === "retake") {
    fileInput.click();
  } else if (action === "retry") {
    if (currentFile) submit(currentFile);
  } else if (action === "change-angle") {
    angleChips.scrollIntoView({ behavior: "smooth", block: "center" });
    const checked = angleChips.querySelector('.chip[aria-checked="true"]');
    (checked || angleChips.querySelector(".chip"))?.focus({ preventScroll: true });
  }
});

// ---------- 送檢 ----------
async function submit(file) {
  // 舊請求還在飛就取消；就算取消不了（後端已收到），流水號也會讓晚到的回應被忽略。
  if (inflight) inflight.abort();
  const controller = new AbortController();
  inflight = controller;
  const seq = ++requestSeq;

  setBusy(true);
  statusEl.textContent = "正在檢查照片…";
  resultEl.hidden = true;

  try {
    const imageBase64 = await fileToBase64(file);
    const payload = { image_base64: imageBase64 };
    // 空字串代表「不指定角度」，這時不要送 required_view，後端才會跳過 WRONG_VIEW。
    if (currentView) payload.required_view = currentView;

    const response = await fetch(CHECK_ENDPOINT, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
      signal: controller.signal,
    });
    if (!response.ok) throw new Error(`API 回傳狀態碼 ${response.status}`);

    const data = await response.json();
    if (seq !== requestSeq) return; // 已有更新的請求，丟掉這份
    renderResult(data);
    statusEl.textContent = data.passed ? "檢查完成：合格" : "檢查完成：請依提示重新拍攝";
  } catch (err) {
    if (err.name === "AbortError" || seq !== requestSeq) return;
    renderError(err.message);
    statusEl.textContent = "檢查失敗";
  } finally {
    if (seq === requestSeq) {
      inflight = null;
      setBusy(false);
    }
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

// #preview 必須是真正的 <img>，而且要等 onload 完成再送檢：canvas 畫車牌框
// 靠它的 naturalWidth/naturalHeight 換算 bbox。
async function showPreview(file) {
  if (objectUrl) URL.revokeObjectURL(objectUrl);
  objectUrl = URL.createObjectURL(file);

  await new Promise((resolve, reject) => {
    preview.onload = resolve;
    preview.onerror = () => reject(new Error("這個檔案不是瀏覽器能顯示的圖片"));
    preview.src = objectUrl;
  });

  preview.classList.add("active");
  camera.classList.add("has-photo");
  cameraEmpty.hidden = true;
  resetBtn.disabled = false;
}

async function handleFile(file) {
  if (!file || busy) return;
  if (!file.type.startsWith("image/")) {
    statusEl.textContent = `「${file.name || "這個檔案"}」不是圖片檔，請選擇照片`;
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
  if (inflight) inflight.abort();
  inflight = null;
  requestSeq += 1; // 讓仍在處理中的回應失效
  setBusy(false);

  if (objectUrl) URL.revokeObjectURL(objectUrl);
  objectUrl = null;
  preview.src = "";
  preview.classList.remove("active");
  camera.classList.remove("has-photo");
  cameraEmpty.hidden = false;
  resultEl.hidden = true;
  resultEl.innerHTML = "";
  resetBtn.disabled = true;
  currentFile = null;
  fileInput.value = "";
  albumInput.value = "";
  statusEl.textContent = "尚未選擇照片";
}

// ---------- 輸入事件 ----------
fileInput.addEventListener("change", (event) => handleFile(event.target.files?.[0]));
albumInput.addEventListener("change", (event) => handleFile(event.target.files?.[0]));
resetBtn.addEventListener("click", reset);

// 貼上：綁在 document 上，使用者不用先點進某個欄位就能按 ⌘V。
document.addEventListener("paste", (event) => {
  const item = [...(event.clipboardData?.items || [])].find((i) => i.type.startsWith("image/"));
  if (!item) return;
  event.preventDefault();
  handleFile(item.getAsFile());
});

// 拖放（相機區就是 drop target）
["dragenter", "dragover"].forEach((type) =>
  camera.addEventListener(type, (event) => {
    event.preventDefault();
    if (!busy) camera.classList.add("dragover");
  })
);
["dragleave", "drop"].forEach((type) =>
  camera.addEventListener(type, (event) => {
    event.preventDefault();
    camera.classList.remove("dragover");
  })
);
camera.addEventListener("drop", (event) => handleFile(event.dataTransfer?.files?.[0]));

// 點相機區：手機開相機、桌機開檔案選擇（同一個 input，capture 在桌機會被忽略）
camera.addEventListener("click", () => {
  if (!busy) fileInput.click();
});
camera.addEventListener("keydown", (event) => {
  if (event.key === "Enter" || event.key === " ") {
    event.preventDefault();
    if (!busy) fileInput.click();
  }
});

setView("");

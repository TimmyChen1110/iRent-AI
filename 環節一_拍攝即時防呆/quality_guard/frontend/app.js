// 用目前頁面的 host 組 API 網址，這樣不管是 localhost 開還是手機用區網 IP
// 開（例如 http://192.168.1.23:5500），都會打到同一台機器的後端，不用手動改。
const API_BASE = `${location.protocol}//${location.hostname}:8000`;

const video = document.getElementById("video");
const photoImg = document.getElementById("captured-photo");
const overlay = document.getElementById("overlay");
const overlayCtx = overlay.getContext("2d");
const captureBtn = document.getElementById("capture-btn");
const retakeBtn = document.getElementById("retake-btn");
const fileInput = document.getElementById("file-input");
const statusEl = document.getElementById("status");
const resultEl = document.getElementById("result");
const viewSelect = document.getElementById("view-select");
const cameraSelect = document.getElementById("camera-select");
const diagEl = document.getElementById("diag");

let lastImageSize = { width: 0, height: 0 };
let currentStream = null;
let diagTimer = null;
// 目前用來顯示畫面、也用來算 overlay 尺寸的元素：即時預覽用 video，
// 手機拍照/上傳檔案用 img，兩者共用同一套 overlay 疊圖邏輯。
let activeVisualEl = video;

function stopCurrentStream() {
  if (currentStream) {
    currentStream.getTracks().forEach((track) => track.stop());
    currentStream = null;
  }
  if (diagTimer) {
    clearInterval(diagTimer);
    diagTimer = null;
  }
}

function startDiagnostics() {
  if (diagTimer) clearInterval(diagTimer);
  diagTimer = setInterval(() => {
    const track = currentStream?.getVideoTracks()[0];
    const lines = [
      `video.readyState=${video.readyState} (0=NOTHING,1=METADATA,2=CURRENT_DATA,3=FUTURE_DATA,4=ENOUGH_DATA)`,
      `video.videoWidth x videoHeight = ${video.videoWidth} x ${video.videoHeight}`,
      `video.paused=${video.paused}  video.currentTime=${video.currentTime.toFixed(2)}`,
      track
        ? `track.readyState=${track.readyState}  track.muted=${track.muted}  track.enabled=${track.enabled}`
        : "track=（無）",
    ];
    diagEl.textContent = lines.join("\n");
  }, 500);
}

async function populateCameraList() {
  const devices = await navigator.mediaDevices.enumerateDevices();
  const cameras = devices.filter((d) => d.kind === "videoinput");
  cameraSelect.innerHTML = cameras
    .map((cam, i) => `<option value="${cam.deviceId}">${cam.label || `相機 ${i + 1}`}</option>`)
    .join("");
}

async function startCamera(deviceId) {
  stopCurrentStream();
  try {
    const videoConstraint = deviceId
      ? { deviceId: { exact: deviceId }, width: { ideal: 1280 }, height: { ideal: 720 } }
      : { width: { ideal: 1280 }, height: { ideal: 720 } };

    const stream = await navigator.mediaDevices.getUserMedia({
      video: videoConstraint,
      audio: false,
    });
    currentStream = stream;
    video.srcObject = stream;
    startDiagnostics();

    const track = stream.getVideoTracks()[0];
    if (track) {
      track.addEventListener("mute", () => {
        statusEl.textContent = "⚠️ 攝影機軌道回報「靜音／無畫面資料」（track muted）——通常是被其他 App 佔用鏡頭，或系統層級擋住了視訊資料";
      });
      track.addEventListener("unmute", () => {
        statusEl.textContent = "攝影機軌道恢復送出畫面資料（unmuted）";
      });
    }

    // 部分瀏覽器（尤其 Chrome）不會單靠 autoplay 屬性就播放，
    // 一定要手動呼叫 play() 才會真的顯示畫面。
    try {
      await video.play();
    } catch (playErr) {
      statusEl.textContent = `相機畫面無法自動播放：${playErr.message}（請直接點一下畫面試試）`;
      video.addEventListener("click", () => video.play(), { once: true });
      return;
    }

    // 有了權限之後才能拿到裝置名稱，藉此重新填充下拉選單，
    // 並確保目前選到的就是實際在用的那顆鏡頭。
    await populateCameraList();
    const activeTrack = stream.getVideoTracks()[0];
    const settings = activeTrack ? activeTrack.getSettings() : {};
    if (activeTrack && cameraSelect.querySelector(`option[value="${settings.deviceId}"]`)) {
      cameraSelect.value = settings.deviceId;
    }

    statusEl.textContent = `相機已啟動（${activeTrack?.label || "未知裝置"}），等待畫面…`;
  } catch (err) {
    statusEl.textContent = `無法開啟相機：${err.message}（可改用檔案上傳的瀏覽器測試環境）`;
  }
}

video.addEventListener("loadedmetadata", () => {
  resizeOverlay();
});

video.addEventListener("error", () => {
  statusEl.textContent = `video 元素回報錯誤：${video.error?.message || video.error?.code || "未知"}`;
});

video.addEventListener("playing", () => {
  if (video.videoWidth > 0 && video.videoHeight > 0) {
    statusEl.textContent = `相機畫面正常（${video.videoWidth}x${video.videoHeight}），對準車輛後按「拍照」`;
  } else {
    statusEl.textContent = "相機已連上，但畫面尺寸是 0——鏡頭可能被其他裝置佔用或被遮住";
  }
});

cameraSelect.addEventListener("change", () => startCamera(cameraSelect.value));

function resizeOverlay() {
  const rect = activeVisualEl.getBoundingClientRect();
  overlay.width = rect.width;
  overlay.height = rect.height;
}

window.addEventListener("resize", resizeOverlay);

function drawPlateBoxOnOverlay(bbox) {
  overlayCtx.clearRect(0, 0, overlay.width, overlay.height);
  if (!bbox || !lastImageSize.width) return;

  const scaleX = overlay.width / lastImageSize.width;
  const scaleY = overlay.height / lastImageSize.height;
  const [x1, y1, x2, y2] = bbox;

  overlayCtx.strokeStyle = "#3ddc84";
  overlayCtx.lineWidth = 3;
  overlayCtx.strokeRect(x1 * scaleX, y1 * scaleY, (x2 - x1) * scaleX, (y2 - y1) * scaleY);
}

function captureFrameAsBase64() {
  const canvas = document.createElement("canvas");
  canvas.width = video.videoWidth;
  canvas.height = video.videoHeight;
  lastImageSize = { width: canvas.width, height: canvas.height };
  const ctx = canvas.getContext("2d");
  ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
  const dataUrl = canvas.toDataURL("image/jpeg", 0.85);
  return dataUrl.split(",")[1];
}

function renderResult(data) {
  resultEl.classList.remove("pass", "fail");
  resultEl.classList.add(data.passed ? "pass" : "fail");

  const headline = data.passed
    ? "✅ 合格，可以送出"
    : "❌ 不合格，請依提示重拍";

  const errorItems = (data.errors || [])
    .map((e) => `<li>${e.message}</li>`)
    .join("");

  resultEl.innerHTML = `
    <div class="headline">${headline}（品質分數 ${data.quality_score}）</div>
    ${errorItems ? `<ul>${errorItems}</ul>` : ""}
    <div class="debug">車牌辨識：${data.plate_text || "（未辨識）"}　信心值：${
    data.plate_confidence ?? "-"
  }
耗時：${data.debug?.elapsed_ms ?? "-"} ms</div>
  `;

  drawPlateBoxOnOverlay(data.debug?.plate_bbox);
}

async function submitForQualityCheck(imageBase64) {
  statusEl.textContent = "分析中…";
  resultEl.className = "";
  resultEl.textContent = "";

  try {
    const response = await fetch(`${API_BASE}/api/photo-quality/check`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        required_view: viewSelect.value,
        image_base64: imageBase64,
      }),
    });

    if (!response.ok) {
      throw new Error(`API 回傳錯誤狀態碼 ${response.status}`);
    }

    const data = await response.json();
    renderResult(data);
    statusEl.textContent = data.passed ? "拍攝完成" : "請依提示重拍";
    retakeBtn.disabled = false;
  } catch (err) {
    statusEl.textContent = `連線後端失敗：${err.message}（目前 API_BASE=${API_BASE}，請確認手機/電腦在同一個網路、且後端有用 --host 0.0.0.0 啟動）`;
    captureBtn.disabled = false;
  }
}

async function handleCapture() {
  captureBtn.disabled = true;
  const imageBase64 = captureFrameAsBase64();
  await submitForQualityCheck(imageBase64);
}

function fileToBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result.split(",")[1]);
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(file);
  });
}

async function handleFileSelected(event) {
  const file = event.target.files?.[0];
  if (!file) return;

  const objectUrl = URL.createObjectURL(file);
  await new Promise((resolve) => {
    photoImg.onload = resolve;
    photoImg.src = objectUrl;
  });
  lastImageSize = { width: photoImg.naturalWidth, height: photoImg.naturalHeight };

  // 切到「顯示上傳照片」模式：藏起即時預覽，overlay 改用 photoImg 的尺寸來算。
  video.classList.add("hidden-by-photo");
  photoImg.classList.add("active");
  activeVisualEl = photoImg;
  resizeOverlay();

  retakeBtn.disabled = false;
  await submitForQualityCheck(await fileToBase64(file));
}

function handleRetake() {
  overlayCtx.clearRect(0, 0, overlay.width, overlay.height);
  resultEl.className = "";
  resultEl.textContent = "";
  statusEl.textContent = "對準車輛後按「拍照」";
  captureBtn.disabled = false;
  retakeBtn.disabled = true;

  // 從「上傳照片」模式切回即時預覽模式（如果目前是那個模式的話）。
  photoImg.classList.remove("active");
  video.classList.remove("hidden-by-photo");
  activeVisualEl = video;
  fileInput.value = "";
  resizeOverlay();
}

captureBtn.addEventListener("click", handleCapture);
retakeBtn.addEventListener("click", handleRetake);
fileInput.addEventListener("change", handleFileSelected);

startCamera();

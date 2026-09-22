const $ = (id) => document.getElementById(id);
const levelClass = (level) =>
  ({ 0: "badge-cyan", 1: "badge-cyan", 2: "badge-amber", 3: "badge-red" })[
    level
  ] || "badge-cyan";
const statusClass = (status) =>
  status === "已关闭"
    ? "badge-green"
    : status === "待确认"
      ? "badge-red"
      : "badge-amber";
const fmtTime = (value) =>
  value
    ? new Date(value).toLocaleString("zh-CN", {
        hour12: false,
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
      })
    : "—";
const esc = (value) =>
  String(value ?? "").replace(
    /[&<>'"]/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" })[
        c
      ],
  );
let currentFilter = "";
const browserCameraId =
  "browser-" + (crypto.randomUUID ? crypto.randomUUID() : Date.now());
const cameraCaptureCanvas = document.createElement("canvas");
let browserCameraStream = null;
let browserCameraTimer = null;
let browserCameraBusy = false;
let openCVTimer = null;
let openCVBusy = false;
let lastOpenCVDetectionId = null;

async function api(url, options) {
  const response = await fetch(url, { credentials: "same-origin", ...options });
  const data = await response.json().catch(() => ({}));
  if (response.status === 401) {
    window.location.assign(
      "/login?next=" + encodeURIComponent(window.location.pathname),
    );
    throw new Error("登录已失效，请重新登录");
  }
  if (!response.ok) throw new Error(data.detail || "请求失败");
  return data;
}

async function loadDashboard() {
  try {
    const [dashboard, health] = await Promise.all([
      api("/api/dashboard"),
      api("/health"),
    ]);
    $("todayDetections").textContent = dashboard.stats.today_detections;
    $("activeEvents").textContent = dashboard.stats.active_events;
    $("severeToday").textContent = dashboard.stats.severe_today;
    $("closedEvents").textContent = dashboard.stats.closed_events;
    $("modelState").textContent = health.model.loaded
      ? "在线 · 已加载"
      : health.model.available
        ? "已配置 · 待加载"
        : "模型不可用";
    if (currentFilter) await loadEvents();
    else renderEvents(dashboard.recent_events);
    renderDetections(dashboard.recent_detections);
  } catch (error) {
    showToast(error.message);
  }
}

async function loadEvents() {
  try {
    const query = currentFilter
      ? "&status=" + encodeURIComponent(currentFilter)
      : "";
    renderEvents(await api("/api/events?limit=50" + query));
  } catch (error) {
    showToast(error.message);
  }
}

function renderEvents(events) {
  $("eventsList").innerHTML = events.length
    ? events
        .map(
          (event) => `
    <article class="event-card" onclick="showEvent(${event.id})">
      <div class="event-top"><span class="badge ${levelClass(event.level)}">${esc(event.warning)}</span><small>${fmtTime(event.updated_at)}</small></div>
      <div class="event-title">${esc(event.title)}</div>
      <div class="event-meta"><span>⌖ ${esc(event.location)}</span><span class="badge ${statusClass(event.status)}">${esc(event.status)}</span><span>置信度 ${(event.confidence * 100).toFixed(0)}%</span></div>
    </article>`,
        )
        .join("")
    : '<div class="empty">暂无符合条件的预警事件</div>';
}

function renderDetections(rows) {
  $("detectionTable").innerHTML = rows.length
    ? rows
        .map((row) => {
          const reached = row.level > 0 && row.confidence >= 0.15;
          return `<tr><td>${fmtTime(row.created_at)}</td><td>${esc(row.location)}</td><td>${row.objects?.length ? row.objects.map((o) => esc(o.class_name_zh)).join("、") : "未发现目标"}</td><td><span class="badge ${levelClass(row.level)}">${esc(row.level_name)}</span></td><td>${(row.confidence * 100).toFixed(0)}%</td><td>${reached ? "检测到漂浮物" : "正常归档"}</td></tr>`;
        })
        .join("")
    : '<tr><td colspan="6" class="empty">还没有识别记录，请先上传河道图片</td></tr>';
}

function eventActions(event) {
  if (event.status === "待确认")
    return `<div class="action-form"><label>处理人员<input id="handlerInput" class="form-input" placeholder="例如：张三" /></label><button onclick="advanceEvent(${event.id},'已派单')">确认并派单</button></div>`;
  if (event.status === "已派单")
    return `<button onclick="advanceEvent(${event.id},'处理中')">开始处理</button>`;
  if (event.status === "处理中")
    return `<div class="action-form"><label>处理说明<textarea id="processingNote" class="form-input" placeholder="填写垃圾清理、打捞和现场处置情况"></textarea></label><button onclick="advanceEvent(${event.id},'已处理')">提交并标记已处理</button></div>`;
  if (event.status === "已处理") {
    const verification = event.verification_result
      ? `<p class="verification-result ${event.verification_result === "通过" ? "passed" : "failed"}">最近复核：${esc(event.verification_result)} · ${esc(event.verification_name)} ${event.verification_confidence ? (event.verification_confidence * 100).toFixed(0) + "%" : ""}</p>`
      : '<p class="verification-result">尚未上传复核图片</p>';
    const passButton =
      event.verification_result === "通过"
        ? `<button onclick="advanceEvent(${event.id},'复核通过')">确认复核通过</button>`
        : "";
    return `<div class="action-form">${verification}<label>复核图片<input id="verifyImage" class="form-input" type="file" accept="image/*" /></label><div><button onclick="verifyEvent(${event.id})">上传并模型复核</button>${passButton}</div></div>`;
  }
  if (event.status === "复核通过")
    return `<button onclick="advanceEvent(${event.id},'已关闭')">关闭并归档事件</button>`;
  return '<span class="badge badge-green" style="padding:10px">✓ 事件已完成闭环</span>';
}

async function showEvent(id) {
  try {
    const event = await api("/api/events/" + id);
    const detectionImage = event.source_detection?.annotated_image_url
      ? `<div><small>模型标注图片</small><img src="${esc(event.source_detection.annotated_image_url)}" alt="模型标注图片" /></div>`
      : "";
    const verificationImage = event.verification_image_url
      ? `<div><small>复核图片</small><img src="${esc(event.verification_image_url)}" alt="复核图片" /></div>`
      : "";
    const verificationDetectionImage = event.verification_detection
      ?.annotated_image_url
      ? `<div><small>复核标注图片</small><img src="${esc(event.verification_detection.annotated_image_url)}" alt="复核标注图片" /></div>`
      : "";
    $("modalContent").innerHTML = `
      <p class="eyebrow">EVENT / ${esc(event.event_no || "#" + event.id)}</p>
      <h3>${esc(event.title)}</h3>
      <div class="modal-sub">${esc(event.location)} · 创建于 ${fmtTime(event.created_at)} · ${esc(event.warning)}</div>
      <div class="event-meta"><span class="badge ${levelClass(event.level)}">${esc(event.level_name)}</span><span>置信度 ${(event.confidence * 100).toFixed(0)}%</span><span class="badge ${statusClass(event.status)}">${esc(event.status)}</span></div>
      <div class="modal-section"><strong>系统建议</strong><p>${esc(event.advice)}</p></div>
      <div class="evidence-grid"><div><small>原始识别图片</small><img src="${esc(event.image_url)}" alt="原始识别图片" /></div>${detectionImage}${verificationImage}${verificationDetectionImage}</div>
      <div class="modal-section info-grid"><span><small>处理人员</small>${esc(event.handler || "待派单")}</span><span><small>处理说明</small>${esc(event.processing_note || "待填写")}</span></div>
      <div class="timeline">${event.logs.map((log) => `<div><strong>${esc(log.to_status)}</strong> ${esc(log.note || "")}<small>${fmtTime(log.created_at)}</small></div>`).join("")}</div>
      <div class="modal-actions">${eventActions(event)}<button onclick="deleteEvent(${event.id})">删除事件</button></div>`;
    $("eventModal").classList.remove("hidden");
  } catch (error) {
    showToast(error.message);
  }
}

async function advanceEvent(id, status) {
  const body = { status, note: "", handler: "" };
  if (status === "已派单") body.handler = $("handlerInput")?.value.trim() || "";
  if (status === "已处理") body.note = $("processingNote")?.value.trim() || "";
  try {
    await api("/api/events/" + id + "/status", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    showToast("事件已推进至：" + status);
    await showEvent(id);
    loadDashboard();
  } catch (error) {
    showToast(error.message);
  }
}

async function verifyEvent(id) {
  const file = $("verifyImage")?.files[0];
  if (!file) return showToast("请先选择复核图片");
  const form = new FormData();
  form.append("image", file);
  try {
    const result = await api("/api/events/" + id + "/verify", {
      method: "POST",
      body: form,
    });
    showToast(result.message);
    await showEvent(id);
    loadDashboard();
  } catch (error) {
    showToast(error.message);
  }
}

async function deleteEvent(id) {
  if (
    !window.confirm(
      "确定删除该事件吗？事件处理日志将一并删除，识别记录会保留。",
    )
  )
    return;
  try {
    await api("/api/events/" + id, { method: "DELETE" });
    closeModal();
    showToast("事件已删除");
    await loadDashboard();
  } catch (error) {
    showToast(error.message);
  }
}

function closeModal() {
  $("eventModal").classList.add("hidden");
}
function showToast(message) {
  const toast = $("toast");
  toast.textContent = message;
  toast.classList.add("show");
  setTimeout(() => toast.classList.remove("show"), 3500);
}

function setCameraStatus(text, kind = "cyan") {
  const badge = $("cameraStatusBadge");
  badge.textContent = text;
  badge.className = `badge badge-${kind}`;
}

function renderCameraAnalysis(data) {
  const state = data.camera_state || {};
  $("cameraFrames").textContent = state.frames_analyzed ?? 0;
  $("cameraConsecutive").textContent =
    `${state.consecutive_floater ?? 0} / ${state.consecutive_required ?? 2}`;
  $("cameraConfidence").textContent =
    `${Math.round((data.confidence || 0) * 100)}%`;
  $("cameraResult").innerHTML = `
    <span class="level ${levelClass(data.floater_level ?? data.garbage_level)}">${esc(data.floater_name ?? data.garbage_name)}</span>
    <p>识别数量：${data.floater_count ?? data.garbage_count ?? 0} 个漂浮物</p>
    <p>${esc(data.monitoring_message)}</p>
    <p>${esc(data.advice)}</p>
    <img src="${esc(data.annotated_image_url)}" alt="最近抽帧识别结果" />`;
  if (data.event_action === "created")
    showToast("摄像头已创建事件：" + data.event_no);
  drawCameraOverlay(data);
  loadDashboard();
}

function drawCameraOverlay(data) {
  if (!browserCameraStream) return;
  const video = $("cameraVideo");
  const overlay = $("cameraOverlay");
  const width = video.videoWidth || data.frame_width || 1;
  const height = video.videoHeight || data.frame_height || 1;
  overlay.width = width;
  overlay.height = height;
  const ctx = overlay.getContext("2d");
  ctx.clearRect(0, 0, width, height);
  const scaleX = width / (data.frame_width || width);
  const scaleY = height / (data.frame_height || height);
  ctx.lineWidth = Math.max(2, width / 320);
  ctx.font = `${Math.max(13, width / 48)}px sans-serif`;
  for (const item of data.objects || []) {
    const [x1, y1, x2, y2] = item.bbox;
    const x = x1 * scaleX,
      y = y1 * scaleY,
      w = (x2 - x1) * scaleX,
      h = (y2 - y1) * scaleY;
    ctx.strokeStyle = "#f2b85b";
    ctx.fillStyle = "#f2b85b";
    ctx.strokeRect(x, y, w, h);
    const label = `Litter ${Math.round(item.confidence * 100)}%`;
    const labelWidth = ctx.measureText(label).width + 10;
    const labelTop = Math.max(0, y - 24);
    ctx.fillRect(x, labelTop, labelWidth, 24);
    ctx.fillStyle = "#071316";
    ctx.fillText(label, x + 5, labelTop + 17);
  }
}

async function resetBrowserCameraState() {
  const form = new FormData();
  form.append("camera_id", browserCameraId);
  try {
    await api("/api/camera/reset", { method: "POST", body: form });
  } catch (_) {}
  $("cameraFrames").textContent = "0";
  $("cameraConsecutive").textContent = "0 / 2";
  $("cameraConfidence").textContent = "0%";
}

async function startBrowserCamera() {
  if (!navigator.mediaDevices?.getUserMedia) {
    showToast(
      "当前浏览器不支持摄像头，请使用 Chrome 或 Edge，并通过 localhost/HTTPS 打开",
    );
    return;
  }
  try {
    browserCameraStream = await navigator.mediaDevices.getUserMedia({
      video: {
        width: { ideal: 1280 },
        height: { ideal: 720 },
        facingMode: { ideal: "environment" },
      },
      audio: false,
    });
    const video = $("cameraVideo");
    video.srcObject = browserCameraStream;
    await video.play();
    if (video.videoWidth && video.videoHeight)
      $("browserCameraPane").querySelector(".camera-stage").style.aspectRatio =
        `${video.videoWidth}/${video.videoHeight}`;
    $("cameraPlaceholder").classList.add("hidden");
    $("startCameraButton").disabled = true;
    $("stopCameraButton").disabled = false;
    await resetBrowserCameraState();
    setCameraStatus("实时巡护中", "green");
    const seconds = Number($("cameraInterval").value);
    browserCameraTimer = setInterval(captureBrowserFrame, seconds * 1000);
    setTimeout(captureBrowserFrame, 800);
  } catch (error) {
    setCameraStatus("启动失败", "red");
    showToast(
      error.name === "NotAllowedError"
        ? "摄像头权限被拒绝，请在浏览器地址栏中允许摄像头"
        : error.message,
    );
  }
}

async function captureBrowserFrame() {
  const video = $("cameraVideo");
  if (!browserCameraStream || browserCameraBusy || video.readyState < 2) return;
  browserCameraBusy = true;
  setCameraStatus("模型分析中", "amber");
  try {
    cameraCaptureCanvas.width = video.videoWidth;
    cameraCaptureCanvas.height = video.videoHeight;
    cameraCaptureCanvas.getContext("2d").drawImage(video, 0, 0);
    const blob = await new Promise((resolve) =>
      cameraCaptureCanvas.toBlob(resolve, "image/jpeg", 0.86),
    );
    if (!blob) throw new Error("摄像头画面抓取失败");
    const form = new FormData();
    form.append("image", blob, `camera-${Date.now()}.jpg`);
    form.append("camera_id", browserCameraId);
    form.append("location", $("cameraLocation").value);
    const result = await api("/api/camera/frame", {
      method: "POST",
      body: form,
    });
    renderCameraAnalysis(result);
    setCameraStatus("实时巡护中", "green");
  } catch (error) {
    setCameraStatus("识别异常", "red");
    showToast(error.message);
  } finally {
    browserCameraBusy = false;
  }
}

async function stopBrowserCamera() {
  clearInterval(browserCameraTimer);
  browserCameraTimer = null;
  browserCameraBusy = false;
  browserCameraStream?.getTracks().forEach((track) => track.stop());
  browserCameraStream = null;
  $("cameraVideo").srcObject = null;
  $("cameraOverlay")
    .getContext("2d")
    .clearRect(0, 0, $("cameraOverlay").width, $("cameraOverlay").height);
  $("cameraPlaceholder").classList.remove("hidden");
  $("startCameraButton").disabled = false;
  $("stopCameraButton").disabled = true;
  await resetBrowserCameraState();
  setCameraStatus("已停止", "cyan");
}

async function startOpenCVCamera() {
  try {
    await api("/api/opencv-camera/start", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        source: $("opencvSource").value.trim() || "0",
        location: $("opencvLocation").value,
        interval_seconds: Number($("opencvInterval").value),
      }),
    });
    $("opencvStream").src = "/api/opencv-camera/stream?t=" + Date.now();
    $("opencvPlaceholder").classList.add("hidden");
    $("startOpenCVButton").disabled = true;
    $("stopOpenCVButton").disabled = false;
    setCameraStatus("OpenCV 巡护中", "green");
    lastOpenCVDetectionId = null;
    openCVTimer = setInterval(pollOpenCVLatest, 2000);
    setTimeout(pollOpenCVLatest, 1200);
  } catch (error) {
    setCameraStatus("OpenCV 启动失败", "red");
    showToast(error.message);
  }
}

async function pollOpenCVLatest() {
  if (openCVBusy || $("startOpenCVButton").disabled === false) return;
  openCVBusy = true;
  try {
    const monitor = await api("/api/opencv-camera/latest");
    if (monitor.last_error) {
      setCameraStatus("等待视频源恢复", "amber");
      $("cameraResult").innerHTML =
        `<p>${esc(monitor.last_error)}</p><p>后端会继续尝试读取或重连 RTSP。</p>`;
    } else if (monitor.latest_result) {
      const detectionId = monitor.latest_result.detection?.id;
      if (detectionId !== lastOpenCVDetectionId) {
        lastOpenCVDetectionId = detectionId;
        renderCameraAnalysis(monitor.latest_result);
      }
      setCameraStatus("OpenCV 后台巡护中", "green");
    } else {
      setCameraStatus("等待首帧分析", "amber");
    }
  } catch (error) {
    setCameraStatus("状态读取失败", "red");
  } finally {
    openCVBusy = false;
  }
}

async function stopOpenCVCamera() {
  clearInterval(openCVTimer);
  openCVTimer = null;
  openCVBusy = false;
  lastOpenCVDetectionId = null;
  try {
    await api("/api/opencv-camera/stop", { method: "POST" });
  } catch (_) {}
  $("opencvStream").removeAttribute("src");
  $("opencvPlaceholder").classList.remove("hidden");
  $("startOpenCVButton").disabled = false;
  $("stopOpenCVButton").disabled = true;
  setCameraStatus("已停止", "cyan");
}

async function restoreOpenCVStatus() {
  try {
    const status = await api("/api/opencv-camera/status");
    if (!status.capture?.running) return;
    await switchCameraMode("opencv");
    $("opencvLocation").value =
      status.capture.location || $("opencvLocation").value;
    $("opencvStream").src = "/api/opencv-camera/stream?t=" + Date.now();
    $("opencvPlaceholder").classList.add("hidden");
    $("startOpenCVButton").disabled = true;
    $("stopOpenCVButton").disabled = false;
    setCameraStatus("OpenCV 后台巡护中", "green");
    openCVTimer = setInterval(pollOpenCVLatest, 2000);
    pollOpenCVLatest();
  } catch (_) {}
}

async function switchCameraMode(mode) {
  const browserMode = mode === "browser";
  if (browserMode) await stopOpenCVCamera();
  else await stopBrowserCamera();
  $("browserCameraPane").classList.toggle("hidden", !browserMode);
  $("opencvCameraPane").classList.toggle("hidden", browserMode);
  $("browserModeButton").classList.toggle("active", browserMode);
  $("opencvModeButton").classList.toggle("active", !browserMode);
}

$("startCameraButton").addEventListener("click", startBrowserCamera);
$("stopCameraButton").addEventListener("click", stopBrowserCamera);
$("startOpenCVButton").addEventListener("click", startOpenCVCamera);
$("stopOpenCVButton").addEventListener("click", stopOpenCVCamera);
$("browserModeButton").addEventListener("click", () =>
  switchCameraMode("browser"),
);
$("opencvModeButton").addEventListener("click", () =>
  switchCameraMode("opencv"),
);
window.addEventListener("beforeunload", () => {
  browserCameraStream?.getTracks().forEach((track) => track.stop());
});

$("imageInput").addEventListener("change", (event) => {
  if (event.target.files[0])
    $("fileName").textContent = event.target.files[0].name;
});
$("detectForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const file = $("imageInput").files[0];
  if (!file) return;
  const button = event.target.querySelector("button");
  button.disabled = true;
  button.textContent = "模型识别中…";
  const form = new FormData();
  form.append("image", file);
  form.append("location", $("location").value);
  try {
    const data = await api("/predict", { method: "POST", body: form });
    const result = $("detectResult");
    const floaterLevel =
      data.floater_level ?? data.garbage_level ?? data.pollution_level;
    const floaterName =
      data.floater_name ?? data.garbage_name ?? data.pollution_name;
    const floaterCount = data.floater_count ?? data.garbage_count ?? 0;
    result.classList.remove("hidden");
    result.innerHTML = `<span class="level ${levelClass(floaterLevel)}">${esc(floaterName)}</span> 识别数量 ${floaterCount} 个 · 置信度 ${(data.confidence * 100).toFixed(0)}%<p><span class="badge ${levelClass(floaterLevel)}">${esc(data.warning_level)}</span></p><p style="color:#9eb9b7">${esc(data.advice)}</p><img src="${esc(data.annotated_image_url || data.image_url)}" alt="识别结果" />`;
    showToast(
      data.event_no
        ? "已创建事件：" + data.event_no
        : "未达到预警阈值，结果已归档",
    );
    loadDashboard();
  } catch (error) {
    showToast(error.message);
  } finally {
    button.disabled = false;
    button.innerHTML = "识别并生成建议 <span>→</span>";
  }
});

document.querySelectorAll(".filter").forEach((button) =>
  button.addEventListener("click", () => {
    document
      .querySelectorAll(".filter")
      .forEach((item) => item.classList.remove("active"));
    button.classList.add("active");
    currentFilter = button.dataset.filter;
    loadEvents();
  }),
);

setInterval(() => {
  $("clock").textContent = new Date().toLocaleString("zh-CN", {
    hour12: false,
  });
}, 1000);
loadDashboard();
restoreOpenCVStatus();

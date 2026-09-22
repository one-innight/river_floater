const $ = (id) => document.getElementById(id);

const state = {
  apiBase: localStorage.getItem("riverPatrolApiBase") || "",
  eventStatus: "",
  previewUrl: "",
};

const STATUS_NEXT = {
  待确认: "已派单",
  已派单: "处理中",
  处理中: "已处理",
  已处理: "复核通过",
  复核通过: "已关闭",
};

function apiUrl(path) {
  const base = state.apiBase.trim().replace(/\/$/, "");
  return `${base}${path}`;
}

function fileUrl(path) {
  if (!path || /^https?:\/\//.test(path)) return path;
  return apiUrl(path);
}

async function api(path, options = {}) {
  const response = await fetch(apiUrl(path), {
    credentials: "include",
    ...options,
  });
  const data =
    response.status === 204 ? null : await response.json().catch(() => ({}));
  if (response.status === 401) {
    const current = "/mobile/";
    window.location.assign(`/login?next=${encodeURIComponent(current)}`);
    throw new Error("登录已失效，请重新登录");
  }
  if (!response.ok)
    throw new Error(data?.detail || "请求失败，请检查网络和服务地址");
  return data;
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>'"]/g, (char) => {
    return {
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      "'": "&#39;",
      '"': "&quot;",
    }[char];
  });
}

function fmtTime(value) {
  if (!value) return "—";
  return new Date(value).toLocaleString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

function floaterLevel(data) {
  return (
    data.floater_level ??
    data.garbage_level ??
    data.pollution_level ??
    data.level ??
    0
  );
}

function floaterName(data) {
  return (
    data.floater_name ??
    data.garbage_name ??
    data.pollution_name ??
    data.level_name ??
    "未发现漂浮物"
  );
}

function floaterCount(data) {
  return (
    data.floater_count ??
    data.garbage_count ??
    data.object_count ??
    data.objects?.length ??
    0
  );
}

function levelClass(level) {
  return `level-${Number(level) || 0}`;
}

async function compressImage(file, maxDimension = 1600, quality = 0.84) {
  if (!file.type.startsWith("image/") || file.size <= 1_500_000) return file;

  const sourceUrl = URL.createObjectURL(file);
  const image = new Image();
  image.src = sourceUrl;
  try {
    await image.decode();
    const scale = Math.min(
      1,
      maxDimension / Math.max(image.naturalWidth, image.naturalHeight),
    );
    const canvas = document.createElement("canvas");
    canvas.width = Math.max(1, Math.round(image.naturalWidth * scale));
    canvas.height = Math.max(1, Math.round(image.naturalHeight * scale));
    canvas.getContext("2d").drawImage(image, 0, 0, canvas.width, canvas.height);
    const blob = await new Promise((resolve) =>
      canvas.toBlob(resolve, "image/jpeg", quality),
    );
    if (!blob || blob.size >= file.size) return file;
    return new File(
      [blob],
      `${file.name.replace(/\.[^.]+$/, "") || "river-photo"}.jpg`,
      {
        type: "image/jpeg",
      },
    );
  } catch {
    return file;
  } finally {
    URL.revokeObjectURL(sourceUrl);
  }
}

function toast(message) {
  const element = $("toast");
  element.textContent = message;
  element.classList.add("show");
  window.clearTimeout(toast.timer);
  toast.timer = window.setTimeout(() => element.classList.remove("show"), 3200);
}

function setConnection(online, label) {
  const element = $("connectionState");
  element.className = `connection ${online ? "online" : "offline"}`;
  element.innerHTML = `<i></i>${escapeHtml(label)}`;
}

async function checkConnection({ notify = false } = {}) {
  try {
    const health = await api("/health");
    setConnection(true, health.model.loaded ? "服务在线" : "服务可用");
    if (notify) toast("已连接到巡护服务");
    return true;
  } catch (error) {
    setConnection(false, "连接失败");
    if (notify) toast(error.message);
    return false;
  }
}

function switchPage(pageId) {
  document
    .querySelectorAll(".page")
    .forEach((page) => page.classList.toggle("active", page.id === pageId));
  document
    .querySelectorAll(".nav-item")
    .forEach((item) =>
      item.classList.toggle("active", item.dataset.page === pageId),
    );
  if (pageId === "eventsPage") loadEvents();
}

function renderDetectResult(data) {
  const level = floaterLevel(data);
  const count = floaterCount(data);
  const element = $("detectResult");
  element.classList.remove("hidden");
  element.innerHTML = `
    <div class="result-head">
      <strong class="result-title">${escapeHtml(floaterName(data))}</strong>
      <span class="badge ${levelClass(level)}">${escapeHtml(data.warning_level)}</span>
    </div>
    <div class="result-meta">识别数量 ${count} 个 · 最高置信度 ${Math.round((data.confidence || 0) * 100)}%</div>
    <p>${escapeHtml(data.advice || "识别结果已归档")}</p>
    ${data.event_no ? `<p>已创建事件：<strong>${escapeHtml(data.event_no)}</strong></p>` : ""}
    <img class="result-image" src="${escapeHtml(fileUrl(data.annotated_image_url || data.image_url))}" alt="漂浮物识别标注结果" />
  `;
}

async function submitDetection(event) {
  event.preventDefault();
  const image = $("imageInput").files[0];
  const location = $("locationInput").value.trim();
  if (!image || !location) return toast("请选择图片并填写河段名称");

  const button = $("detectButton");
  button.disabled = true;
  button.textContent = "正在压缩图片…";
  try {
    const optimizedImage = await compressImage(image);
    const form = new FormData();
    form.append("image", optimizedImage);
    form.append("location", location);
    button.textContent = "正在识别…";
    const data = await api("/api/detections", { method: "POST", body: form });
    renderDetectResult(data);
    toast(
      data.event_no
        ? `已创建预警事件：${data.event_no}`
        : "识别完成，结果已归档",
    );
  } catch (error) {
    toast(error.message);
  } finally {
    button.disabled = false;
    button.innerHTML = "开始识别 <span>→</span>";
  }
}

function renderEvents(events) {
  const target = $("eventsList");
  if (!events.length) {
    target.innerHTML = '<div class="empty-state">暂无符合条件的事件</div>';
    return;
  }
  target.innerHTML = events
    .map(
      (event) => `
        <button class="event-card" type="button" data-event-id="${event.id}">
          <div class="event-top">
            <span class="badge ${levelClass(event.level)}">${escapeHtml(event.warning)}</span>
            <span class="event-time">${fmtTime(event.updated_at)}</span>
          </div>
          <h3>${escapeHtml(event.title)}</h3>
          <div class="event-meta">${escapeHtml(event.location)} · ${escapeHtml(event.status)} · ${Math.round((event.confidence || 0) * 100)}%</div>
        </button>`,
    )
    .join("");
  target.querySelectorAll("[data-event-id]").forEach((item) => {
    item.addEventListener("click", () =>
      showEvent(Number(item.dataset.eventId)),
    );
  });
}

async function loadEvents() {
  const target = $("eventsList");
  target.innerHTML = '<div class="empty-state">正在加载事件…</div>';
  const query = state.eventStatus
    ? `?status=${encodeURIComponent(state.eventStatus)}`
    : "";
  try {
    renderEvents(await api(`/api/events${query}`));
  } catch (error) {
    target.innerHTML = `<div class="empty-state">${escapeHtml(error.message)}</div>`;
  }
}

function eventActions(event) {
  const next = STATUS_NEXT[event.status];
  const sections = [];
  if (next === "已派单") {
    sections.push(
      '<button class="secondary-button" data-action="dispatch">确认并派单</button>',
    );
  } else if (next === "处理中") {
    sections.push(
      '<button class="secondary-button" data-action="advance">开始处理</button>',
    );
  } else if (next === "已处理") {
    sections.push(
      '<button class="secondary-button" data-action="process">提交处理说明</button>',
    );
  } else if (next === "复核通过") {
    sections.push(
      '<button class="secondary-button" data-action="verify">上传复核图片</button>',
    );
    if (event.verification_result === "通过") {
      sections.push(
        '<button class="secondary-button" data-action="advance">确认复核通过</button>',
      );
    }
  } else if (next === "已关闭") {
    sections.push(
      '<button class="secondary-button" data-action="advance">归档事件</button>',
    );
  }
  sections.push(
    '<button class="danger-button" data-action="delete">删除事件</button>',
  );
  return sections.join("");
}

function evidenceCard(label, url) {
  if (!url) return "";
  return `
    <figure class="evidence-card">
      <figcaption>${escapeHtml(label)}</figcaption>
      <img class="evidence-image" loading="lazy" src="${escapeHtml(fileUrl(url))}" alt="${escapeHtml(label)}" />
    </figure>`;
}

function verificationSummary(event, verification) {
  if (!event.verification_result) return "";
  const passed = event.verification_result === "通过";
  const level = event.verification_level ?? verification.level ?? 0;
  const levelName =
    event.verification_name ?? verification.level_name ?? "未发现漂浮物";
  const confidence =
    event.verification_confidence ?? verification.confidence ?? 0;
  const count = verification.objects?.length ?? 0;
  return `
    <div class="detail-section verification-summary ${passed ? "verification-passed" : "verification-failed"}">
      <h3>最近复核</h3>
      <p><span class="badge ${passed ? "status-closed" : levelClass(level)}">复核${escapeHtml(event.verification_result)}</span></p>
      <p>${escapeHtml(levelName)} · ${count} 个漂浮物 · 最高置信度 ${Math.round(confidence * 100)}%</p>
    </div>`;
}

async function showEvent(id) {
  try {
    const event = await api(`/api/events/${id}`);
    const source = event.source_detection || {};
    const verification = event.verification_detection || {};
    const level = event.level;
    $("eventDetail").innerHTML = `
      <div class="detail-header">
        <div><p class="eyebrow">${escapeHtml(event.event_no || `EVENT #${event.id}`)}</p><h2>${escapeHtml(event.title)}</h2></div>
        <button class="dialog-close" data-action="close" type="button" aria-label="关闭">×</button>
      </div>
      <div class="result-head"><span class="badge ${levelClass(level)}">${escapeHtml(event.warning)}</span><span class="badge ${event.status === "已关闭" ? "status-closed" : levelClass(level)}">${escapeHtml(event.status === "已关闭" ? "已归档" : event.status)}</span></div>
      <div class="detail-section"><h3>识别结果</h3><p>${escapeHtml(event.level_name)} · ${source.objects?.length ?? 0} 个漂浮物 · 最高置信度 ${Math.round((event.confidence || 0) * 100)}%</p><div class="evidence-grid">${evidenceCard("原始识别图片", event.image_url)}${evidenceCard("模型标注图片", source.annotated_image_url)}${evidenceCard("复核图片", event.verification_image_url)}${evidenceCard("复核标注图片", verification.annotated_image_url)}</div></div>
      ${verificationSummary(event, verification)}
      <div class="detail-section"><h3>处置建议</h3><p>${escapeHtml(event.advice)}</p></div>
      <div class="detail-section"><h3>事件操作</h3><div class="action-row">${eventActions(event)}</div></div>
    `;
    const dialog = $("eventDialog");
    if (!dialog.open) dialog.showModal();
    $("eventDetail")
      .querySelectorAll("[data-action]")
      .forEach((button) => {
        button.addEventListener("click", () =>
          handleEventAction(event, button.dataset.action),
        );
      });
  } catch (error) {
    toast(error.message);
  }
}

async function updateStatus(event, status, extra = {}) {
  await api(`/api/events/${event.id}/status`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ status, note: "", handler: "", ...extra }),
  });
}

async function handleEventAction(event, action) {
  if (action === "close") return $("eventDialog").close();
  try {
    if (action === "delete") {
      if (
        !window.confirm(
          "确定删除该事件吗？处理日志会一并删除，识别记录会保留。",
        )
      )
        return;
      await api(`/api/events/${event.id}`, { method: "DELETE" });
      $("eventDialog").close();
      toast("事件已删除");
    } else if (action === "dispatch") {
      const handler = window.prompt(
        "请输入处理人员姓名：",
        event.handler || "",
      );
      if (!handler?.trim()) return;
      await updateStatus(event, "已派单", { handler: handler.trim() });
      toast("事件已派单");
    } else if (action === "process") {
      const note = window.prompt(
        "请输入处理说明：",
        event.processing_note || "",
      );
      if (!note?.trim()) return;
      await updateStatus(event, "已处理", { note: note.trim() });
      toast("已标记为已处理");
    } else if (action === "verify") {
      await openVerifyPicker(event);
      return;
    } else {
      await updateStatus(event, STATUS_NEXT[event.status]);
      toast("事件状态已更新");
    }
    await Promise.all([loadEvents(), showEvent(event.id)]);
  } catch (error) {
    toast(error.message);
  }
}

function openVerifyPicker(event) {
  const input = document.createElement("input");
  input.type = "file";
  input.accept = "image/*";
  input.addEventListener("change", async () => {
    const file = input.files[0];
    if (!file) return;
    try {
      toast("正在压缩并上传复核图片…");
      const form = new FormData();
      form.append("image", await compressImage(file));
      const result = await api(`/api/events/${event.id}/verify`, {
        method: "POST",
        body: form,
      });
      toast(result.message);
      await Promise.all([loadEvents(), showEvent(event.id)]);
    } catch (error) {
      toast(error.message);
    }
  });
  input.click();
}

function setPreview() {
  const file = $("imageInput").files[0];
  const preview = $("previewImage");
  if (state.previewUrl) URL.revokeObjectURL(state.previewUrl);
  if (!file) {
    preview.classList.add("hidden");
    $("imageLabel").textContent = "拍照或选择现场图片";
    return;
  }
  state.previewUrl = URL.createObjectURL(file);
  preview.src = state.previewUrl;
  preview.classList.remove("hidden");
  $("imageLabel").textContent = file.name || "已选择现场图片";
}

function bindEvents() {
  $("detectForm").addEventListener("submit", submitDetection);
  $("imageInput").addEventListener("change", setPreview);
  $("refreshEvents").addEventListener("click", loadEvents);
  document
    .querySelectorAll(".nav-item")
    .forEach((item) =>
      item.addEventListener("click", () => switchPage(item.dataset.page)),
    );
  document.querySelectorAll(".filter").forEach((item) => {
    item.addEventListener("click", () => {
      state.eventStatus = item.dataset.status;
      document
        .querySelectorAll(".filter")
        .forEach((button) =>
          button.classList.toggle("active", button === item),
        );
      loadEvents();
    });
  });
  $("apiBaseInput").value = state.apiBase;
  $("settingsForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    state.apiBase = $("apiBaseInput").value.trim().replace(/\/$/, "");
    localStorage.setItem("riverPatrolApiBase", state.apiBase);
    await checkConnection({ notify: true });
  });
  $("eventDialog").addEventListener("click", (event) => {
    if (event.target === $("eventDialog")) $("eventDialog").close();
  });
}

function registerServiceWorker() {
  if ("serviceWorker" in navigator && window.isSecureContext) {
    navigator.serviceWorker.register("/mobile/sw.js").catch(() => undefined);
  }
}

bindEvents();
checkConnection();
registerServiceWorker();

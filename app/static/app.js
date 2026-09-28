const $ = (selector, root = document) => root.querySelector(selector);

const state = {
  file: null,
  duration: null,
  jobs: [],
  polling: null,
};

const elements = {
  systemStatus: $("#systemStatus"),
  dropzone: $("#dropzone"),
  fileInput: $("#fileInput"),
  selectedFile: $("#selectedFile"),
  fileName: $("#fileName"),
  fileInfo: $("#fileInfo"),
  fileKind: $("#fileKind"),
  removeFile: $("#removeFile"),
  speed: $("#speedSelect"),
  trim: $("#trimSilence"),
  context: $("#contextInput"),
  estimate: $("#estimatedDuration"),
  submit: $("#submitButton"),
  uploadProgress: $("#uploadProgress"),
  uploadProgressText: $("#uploadProgressText"),
  uploadProgressBar: $("#uploadProgressBar"),
  formError: $("#formError"),
  emptyState: $("#emptyState"),
  jobsList: $("#jobsList"),
  refresh: $("#refreshJobs"),
  template: $("#jobTemplate"),
};

function formatBytes(bytes) {
  if (!Number.isFinite(bytes)) return "—";
  const units = ["B", "KB", "MB", "GB"];
  let value = bytes;
  let index = 0;
  while (value >= 1024 && index < units.length - 1) { value /= 1024; index += 1; }
  return `${value.toFixed(index ? 1 : 0)} ${units[index]}`;
}

function formatDuration(totalSeconds) {
  if (!Number.isFinite(totalSeconds)) return "—";
  const seconds = Math.max(0, Math.round(totalSeconds));
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const rest = seconds % 60;
  return hours
    ? `${hours}:${String(minutes).padStart(2, "0")}:${String(rest).padStart(2, "0")}`
    : `${minutes}:${String(rest).padStart(2, "0")}`;
}

function setError(message = "") {
  elements.formError.textContent = message;
  elements.formError.classList.toggle("hidden", !message);
}

async function checkHealth() {
  try {
    const response = await fetch("/api/health");
    const health = await response.json();
    elements.systemStatus.className = `system-status ${health.ok ? (health.ai_configured ? "ready" : "warning") : "error"}`;
    $("span:last-child", elements.systemStatus).textContent = !health.ffmpeg_available
      ? "FFmpeg 未就绪"
      : health.ai_configured ? "MiniMax 已就绪" : "待配置 MiniMax 密钥";
  } catch {
    elements.systemStatus.className = "system-status error";
    $("span:last-child", elements.systemStatus).textContent = "服务不可用";
  }
}

function inspectDuration(file) {
  const media = document.createElement(file.type.startsWith("video/") ? "video" : "audio");
  const url = URL.createObjectURL(file);
  media.preload = "metadata";
  media.onloadedmetadata = () => {
    state.duration = Number.isFinite(media.duration) ? media.duration : null;
    URL.revokeObjectURL(url);
    updateEstimate();
    elements.fileInfo.textContent = `${formatBytes(file.size)}${state.duration ? ` · ${formatDuration(state.duration)}` : ""}`;
  };
  media.onerror = () => URL.revokeObjectURL(url);
  media.src = url;
}

function selectFile(file) {
  if (!file) return;
  const extension = file.name.split(".").pop()?.toUpperCase() || "MEDIA";
  state.file = file;
  state.duration = null;
  elements.fileName.textContent = file.name;
  elements.fileInfo.textContent = formatBytes(file.size);
  elements.fileKind.textContent = extension.slice(0, 4);
  elements.dropzone.classList.add("hidden");
  elements.selectedFile.classList.remove("hidden");
  elements.submit.disabled = false;
  setError();
  updateEstimate();
  inspectDuration(file);
}

function clearFile() {
  state.file = null;
  state.duration = null;
  elements.fileInput.value = "";
  elements.dropzone.classList.remove("hidden");
  elements.selectedFile.classList.add("hidden");
  elements.submit.disabled = true;
  elements.estimate.textContent = "选择文件后计算";
}

function updateEstimate() {
  if (!state.duration) {
    elements.estimate.textContent = state.file ? "正在读取时长…" : "选择文件后计算";
    return;
  }
  const speed = Number(elements.speed.value);
  const accelerated = state.duration / speed;
  const estimate = elements.trim.checked ? accelerated * 0.88 : accelerated;
  elements.estimate.textContent = `约 ${formatDuration(estimate)}${elements.trim.checked ? "（含静音预估）" : ""}`;
}

function upload() {
  if (!state.file) return;
  elements.submit.disabled = true;
  setError();
  elements.uploadProgress.classList.remove("hidden");
  const data = new FormData();
  data.append("file", state.file);
  data.append("speed", elements.speed.value);
  data.append("trim_silence", String(elements.trim.checked));
  data.append("context", elements.context.value);

  const request = new XMLHttpRequest();
  request.open("POST", "/api/jobs");
  request.upload.onprogress = (event) => {
    if (!event.lengthComputable) return;
    const percent = Math.round((event.loaded / event.total) * 100);
    elements.uploadProgressText.textContent = `正在上传 ${percent}%`;
    elements.uploadProgressBar.style.width = `${percent}%`;
  };
  request.onload = async () => {
    elements.uploadProgress.classList.add("hidden");
    elements.submit.disabled = !state.file;
    if (request.status >= 200 && request.status < 300) {
      clearFile();
      elements.context.value = "";
      await loadJobs();
      $("#jobsSection").scrollIntoView({ behavior: "smooth", block: "start" });
      startPolling();
    } else {
      try { setError(JSON.parse(request.responseText).detail || "上传失败"); }
      catch { setError("上传失败，请稍后重试"); }
    }
  };
  request.onerror = () => {
    elements.uploadProgress.classList.add("hidden");
    elements.submit.disabled = false;
    setError("网络连接失败，请确认服务正在运行");
  };
  request.send(data);
}

function metric(label, value) {
  return `<span>${label}<strong>${value}</strong></span>`;
}

function renderMarkdown(container, source) {
  container.replaceChildren();
  container.classList.add("markdown");
  const lines = source.split("\n");
  const isTableRule = (line) => /^\s*\|?\s*:?-{3,}/.test(line) && line.includes("|");
  const cells = (line) => line.replace(/^\s*\||\|\s*$/g, "").split("|").map((cell) => cell.trim());
  let index = 0;

  while (index < lines.length) {
    const line = lines[index].trim();
    if (!line) { index += 1; continue; }

    const heading = line.match(/^(#{1,3})\s+(.+)$/);
    if (heading) {
      const element = document.createElement(`h${heading[1].length}`);
      element.textContent = heading[2];
      container.appendChild(element);
      index += 1;
      continue;
    }

    if (line.includes("|") && index + 1 < lines.length && isTableRule(lines[index + 1])) {
      const table = document.createElement("table");
      const thead = document.createElement("thead");
      const headerRow = document.createElement("tr");
      cells(line).forEach((value) => {
        const cell = document.createElement("th");
        cell.textContent = value;
        headerRow.appendChild(cell);
      });
      thead.appendChild(headerRow);
      table.appendChild(thead);
      const tbody = document.createElement("tbody");
      index += 2;
      while (index < lines.length && lines[index].includes("|")) {
        const row = document.createElement("tr");
        cells(lines[index]).forEach((value) => {
          const cell = document.createElement("td");
          cell.textContent = value;
          row.appendChild(cell);
        });
        tbody.appendChild(row);
        index += 1;
      }
      table.appendChild(tbody);
      container.appendChild(table);
      continue;
    }

    if (/^[-*]\s+/.test(line)) {
      const list = document.createElement("ul");
      while (index < lines.length && /^\s*[-*]\s+/.test(lines[index])) {
        const item = document.createElement("li");
        item.textContent = lines[index].replace(/^\s*[-*]\s+/, "");
        list.appendChild(item);
        index += 1;
      }
      container.appendChild(list);
      continue;
    }

    const paragraph = document.createElement("p");
    const paragraphLines = [];
    while (index < lines.length && lines[index].trim()) {
      if (paragraphLines.length && (/^#{1,3}\s+/.test(lines[index]) || /^\s*[-*]\s+/.test(lines[index]))) break;
      paragraphLines.push(lines[index].trim());
      index += 1;
    }
    paragraph.textContent = paragraphLines.join(" ");
    container.appendChild(paragraph);
  }
}

function showResult(content, text, isMinutes) {
  if (isMinutes) {
    renderMarkdown(content, text);
  } else {
    content.classList.remove("markdown");
    content.textContent = text;
  }
}

async function requestJSON(url, options = {}) {
  const response = await fetch(url, options);
  if (!response.ok) {
    let message = "请求失败";
    try { message = (await response.json()).detail || message; }
    catch { /* Use the generic message. */ }
    throw new Error(message);
  }
  return response.json();
}

function renderReviewItem(job, item) {
  const article = document.createElement("article");
  article.className = `review-item ${item.confidence < 0.75 ? "needs-review" : "supported"}`;

  const header = document.createElement("div");
  header.className = "review-item-heading";
  const time = document.createElement("strong");
  time.textContent = `${formatDuration(item.start_seconds)} – ${formatDuration(item.end_seconds)}`;
  const confidence = document.createElement("span");
  confidence.textContent = item.confidence < 0.75
    ? `请人工确认 · ${Math.round(item.confidence * 100)}%`
    : `OCR/上下文支持 · ${Math.round(item.confidence * 100)}%`;
  header.append(time, confidence);
  article.appendChild(header);

  if (item.frame_count) {
    const frames = document.createElement("div");
    frames.className = "review-frames";
    for (let index = 0; index < item.frame_count; index += 1) {
      const image = document.createElement("img");
      image.loading = "lazy";
      image.alt = `${formatDuration(item.start_seconds)} 的原始视频画面`;
      image.src = `/api/jobs/${job.id}/review/${item.id}/frame/${index}`;
      frames.appendChild(image);
    }
    article.appendChild(frames);
  }

  const audio = document.createElement("audio");
  audio.controls = true;
  audio.preload = "none";
  audio.src = `/api/jobs/${job.id}/review/${item.id}/audio`;
  article.appendChild(audio);

  const original = document.createElement("p");
  original.className = "review-original";
  original.textContent = `原速识别：${item.original_text}`;
  article.appendChild(original);

  if (item.ocr_text.length) {
    const ocr = document.createElement("p");
    ocr.className = "review-ocr";
    ocr.textContent = `画面 OCR：${item.ocr_text.join(" · ")}`;
    article.appendChild(ocr);
  }

  const reason = document.createElement("p");
  reason.className = "review-reason";
  reason.textContent = item.reason;
  article.appendChild(reason);

  const label = document.createElement("label");
  label.className = "review-correction-field";
  const labelText = document.createElement("span");
  labelText.textContent = "确认后的完整句子";
  const textarea = document.createElement("textarea");
  textarea.className = "review-correction";
  textarea.dataset.itemId = item.id;
  textarea.dataset.originalText = item.original_text;
  textarea.rows = 3;
  textarea.maxLength = 5000;
  textarea.value = item.correction || item.suggested_text || item.original_text;
  label.append(labelText, textarea);
  article.appendChild(label);

  const keep = document.createElement("button");
  keep.className = "review-keep";
  keep.type = "button";
  keep.textContent = "保留原速识别文本";
  keep.addEventListener("click", () => { textarea.value = item.original_text; });
  article.appendChild(keep);
  return article;
}

function renderReview(job, card) {
  if (job.status !== "completed" || !job.transcript) return;
  const panel = $(".review-panel", card);
  const start = $(".review-start", panel);
  const progress = $(".review-progress", panel);
  const error = $(".review-error", panel);
  const list = $(".review-list", panel);
  const apply = $(".review-apply", panel);
  const status = job.review_status || "idle";
  panel.classList.remove("hidden");

  if (["processing", "applying"].includes(status)) {
    start.classList.add("hidden");
    progress.classList.remove("hidden");
    $("b", progress).style.width = `${job.review_progress || 0}%`;
    $("span", progress).textContent = `${job.review_stage} · ${job.review_progress || 0}%`;
  } else {
    start.classList.toggle("hidden", ["ready", "completed"].includes(status));
  }

  if (status === "failed") {
    error.textContent = job.review_error || "智能校对失败";
    error.classList.remove("hidden");
    start.textContent = "重新运行智能校对 ↻";
  }

  start.addEventListener("click", async () => {
    start.disabled = true;
    start.textContent = "正在启动校对…";
    try {
      await requestJSON(`/api/jobs/${job.id}/review`, { method: "POST" });
      await loadJobs();
      startPolling();
    } catch (requestError) {
      start.disabled = false;
      start.textContent = "智能校对：OCR + 原声";
      error.textContent = requestError.message;
      error.classList.remove("hidden");
    }
  });

  if (["ready", "completed"].includes(status)) {
    if (!job.review_items.length) {
      const empty = document.createElement("p");
      empty.className = "review-empty";
      empty.textContent = "原速音频复核完成，未发现明显需要人工确认的句段。";
      list.appendChild(empty);
    } else {
      job.review_items.forEach((item) => list.appendChild(renderReviewItem(job, item)));
      apply.classList.remove("hidden");
      apply.textContent = status === "completed"
        ? "更新修正并重新生成纪要 →"
        : "应用以上修正并重新生成纪要 →";
      apply.addEventListener("click", async () => {
        const corrections = [...panel.querySelectorAll(".review-correction")].map((field) => ({
          item_id: field.dataset.itemId,
          text: field.value.trim(),
        })).filter((item) => item.text);
        apply.disabled = true;
        apply.textContent = "正在应用修正…";
        try {
          await requestJSON(`/api/jobs/${job.id}/review/apply`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ corrections }),
          });
          await loadJobs();
          startPolling();
        } catch (requestError) {
          apply.disabled = false;
          apply.textContent = "应用以上修正并重新生成纪要 →";
          error.textContent = requestError.message;
          error.classList.remove("hidden");
        }
      });
    }
  }
}

function renderJob(job) {
  const fragment = elements.template.content.cloneNode(true);
  const card = $(".job-card", fragment);
  card.classList.add(job.status);
  $(".job-title strong", card).textContent = job.filename;
  $(".job-title span", card).textContent = new Date(job.created_at).toLocaleString("zh-CN");
  $(".job-state span", card).textContent = job.stage;
  $(".job-progress b", card).style.width = `${job.progress}%`;
  $(".job-progress > span", card).textContent = `${job.progress}%`;
  const extension = job.filename.split(".").pop()?.toUpperCase() || "AU";
  $(".job-file-icon", card).textContent = extension.slice(0, 4);

  const metrics = $(".job-metrics", card);
  const reduction = job.original_duration_seconds && job.compressed_duration_seconds
    ? Math.max(0, Math.round((1 - job.compressed_duration_seconds / job.original_duration_seconds) * 100))
    : null;
  metrics.innerHTML = [
    metric("原始", formatDuration(job.original_duration_seconds)),
    metric("压缩后", formatDuration(job.compressed_duration_seconds)),
    metric("缩短", reduction === null ? "—" : `${reduction}%`),
    metric("音频大小", formatBytes(job.compressed_size_bytes)),
    metric("速度", `${job.speed}×`),
  ].join("");

  if (job.error) {
    const error = $(".job-error", card);
    error.textContent = job.error;
    error.classList.remove("hidden");
  }
  if (job.status === "failed") {
    const retry = $(".retry-button", card);
    retry.classList.remove("hidden");
    retry.addEventListener("click", async () => {
      retry.disabled = true;
      retry.textContent = "正在重新处理…";
      try {
        const response = await fetch(`/api/jobs/${job.id}/retry`, { method: "POST" });
        if (!response.ok) {
          const payload = await response.json();
          throw new Error(payload.detail || "重新处理失败");
        }
        await loadJobs();
        startPolling();
      } catch (error) {
        retry.disabled = false;
        retry.textContent = "重新处理 ↻";
        setError(error.message);
      }
    });
  }

  if (job.minutes || job.transcript) {
    const results = $(".job-results", card);
    const content = $(".result-content", card);
    const tabs = [...card.querySelectorAll(".result-tabs button")];
    results.classList.remove("hidden");
    let current = job.minutes || job.transcript || "";
    let showingMinutes = Boolean(job.minutes);
    showResult(content, current, showingMinutes);
    tabs.forEach((tab) => tab.addEventListener("click", () => {
      tabs.forEach((item) => item.classList.toggle("active", item === tab));
      showingMinutes = tab.dataset.tab === "minutes";
      current = showingMinutes ? (job.minutes || "纪要尚未生成") : (job.transcript || "转写尚未生成");
      showResult(content, current, showingMinutes && Boolean(job.minutes));
    }));
    $(".copy-button", card).addEventListener("click", async (event) => {
      await navigator.clipboard.writeText(current);
      event.currentTarget.textContent = "已复制";
      setTimeout(() => { event.currentTarget.textContent = "复制内容"; }, 1500);
    });
    const minutesLink = $("[data-download='minutes']", card);
    minutesLink.href = `/api/jobs/${job.id}/minutes`;
    if (!job.minutes) minutesLink.classList.add("hidden");
    $("[data-download='audio']", card).href = `/api/jobs/${job.id}/audio`;
  } else if (job.compressed_size_bytes) {
    const results = $(".job-results", card);
    results.classList.remove("hidden");
    $(".result-tabs", card).classList.add("hidden");
    $(".result-content", card).textContent = "压缩音频已生成。配置 API 密钥后可重新上传并生成转写与纪要。";
    $(".copy-button", card).classList.add("hidden");
    $("[data-download='minutes']", card).classList.add("hidden");
    $("[data-download='audio']", card).href = `/api/jobs/${job.id}/audio`;
  }
  renderReview(job, card);
  return fragment;
}

function renderJobs() {
  elements.jobsList.replaceChildren();
  elements.emptyState.classList.toggle("hidden", state.jobs.length > 0);
  for (const job of state.jobs) elements.jobsList.appendChild(renderJob(job));
}

async function loadJobs() {
  try {
    const response = await fetch("/api/jobs", { cache: "no-store" });
    if (!response.ok) throw new Error("load failed");
    state.jobs = await response.json();
    renderJobs();
    if (!state.jobs.some((job) => (
      ["queued", "processing"].includes(job.status)
      || ["processing", "applying"].includes(job.review_status)
    ))) stopPolling();
  } catch { /* Keep the previous list visible during a transient error. */ }
}

function startPolling() {
  if (!state.polling) state.polling = window.setInterval(loadJobs, 1800);
}

function stopPolling() {
  if (state.polling) window.clearInterval(state.polling);
  state.polling = null;
}

elements.fileInput.addEventListener("change", () => selectFile(elements.fileInput.files[0]));
elements.removeFile.addEventListener("click", clearFile);
elements.speed.addEventListener("change", updateEstimate);
elements.trim.addEventListener("change", updateEstimate);
elements.submit.addEventListener("click", upload);
elements.refresh.addEventListener("click", loadJobs);
["dragenter", "dragover"].forEach((name) => elements.dropzone.addEventListener(name, (event) => {
  event.preventDefault(); elements.dropzone.classList.add("dragging");
}));
["dragleave", "drop"].forEach((name) => elements.dropzone.addEventListener(name, (event) => {
  event.preventDefault(); elements.dropzone.classList.remove("dragging");
}));
elements.dropzone.addEventListener("drop", (event) => selectFile(event.dataTransfer.files[0]));

checkHealth();
loadJobs().then(() => {
  if (state.jobs.some((job) => (
    ["queued", "processing"].includes(job.status)
    || ["processing", "applying"].includes(job.review_status)
  ))) startPolling();
});

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
    if (!state.jobs.some((job) => ["queued", "processing"].includes(job.status))) stopPolling();
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
  if (state.jobs.some((job) => ["queued", "processing"].includes(job.status))) startPolling();
});

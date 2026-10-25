const $ = (selector, root = document) => root.querySelector(selector);

const state = {
  file: null,
  duration: null,
  jobs: [],
  polling: null,
  expandedJobId: null,
  usageExpandedJobIds: new Set(),
  selectedMinutesVersions: new Map(),
  comparingJobIds: new Set(),
  jobsInitialized: false,
  chatSessions: [],
  activeChatSessionId: null,
  chatHistorySignature: "",
  selectedChatJobIds: null,
  chatScopeJobsSignature: "",
  chatLoading: false,
  chatNotes: [],
  chatNotesLoading: false,
  chatNoteBusy: false,
  activeChatNoteId: null,
  chatSelection: null,
  desktopView: null,
  renderedChatSessionId: null,
  renderedChatNoteId: null,
  desktopMeetingListSignature: "",
  sourceReturnView: "chat",
  sourceSelectionToken: 0,
};

const desktopMedia = window.matchMedia("(min-width: 1100px)");

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
  desktopMeetingList: $("#desktopMeetingList"),
  desktopMeetingCount: $("#desktopMeetingCount"),
  refresh: $("#refreshJobs"),
  newMeeting: $("#newMeetingToggle"),
  uploadWorkspace: $("#uploadWorkspace"),
  template: $("#jobTemplate"),
  chatSection: $("#chatSection"),
  chatScope: $("#chatScope"),
  chatSessionList: $("#chatSessionList"),
  chatNew: $("#chatNew"),
  chatRename: $("#chatRename"),
  chatDelete: $("#chatDelete"),
  chatSessionId: $("#chatSessionId"),
  chatSessionIdValue: $("#chatSessionIdValue"),
  chatSessionIdCopy: $("#chatSessionIdCopy"),
  chatScopeSummary: $("#chatScopeSummary"),
  chatScopeOptions: $("#chatScopeOptions"),
  chatRecordOpen: $("#chatRecordOpen"),
  chatSelectAll: $("#chatSelectAll"),
  chatSelectNone: $("#chatSelectNone"),
  chatHint: $("#chatHint"),
  chatMessages: $("#chatMessages"),
  sourcePlayer: $("#sourcePlayer"),
  sourcePlayerMeeting: $("#sourcePlayerMeeting"),
  sourcePlayerList: $("#sourcePlayerList"),
  sourcePlayerContext: $("#sourcePlayerContext"),
  sourcePlayerStatus: $("#sourcePlayerStatus"),
  sourcePlayerMedia: $("#sourcePlayerMedia"),
  sourcePlayerOriginal: $("#sourcePlayerOriginal"),
  sourcePlayerClose: $("#sourcePlayerClose"),
  chatForm: $("#chatForm"),
  chatQuestion: $("#chatQuestion"),
  chatSend: $("#chatSend"),
  chatError: $("#chatError"),
  chatNotesToggle: $("#chatNotesToggle"),
  chatNotesCount: $("#chatNotesCount"),
  chatNotesPanel: $("#chatNotesPanel"),
  chatNotesClose: $("#chatNotesClose"),
  chatNotesStatus: $("#chatNotesStatus"),
  chatNotesList: $("#chatNotesList"),
  chatNoteDetail: $("#chatNoteDetail"),
  chatNotePhrase: $("#chatNotePhrase"),
  chatNoteDelete: $("#chatNoteDelete"),
  chatNotePronunciation: $("#chatNotePronunciation"),
  chatNoteIpa: $("#chatNoteIpa"),
  chatNoteSpeak: $("#chatNoteSpeak"),
  chatNoteExcerpt: $("#chatNoteExcerpt"),
  chatNoteExchanges: $("#chatNoteExchanges"),
  chatNoteForm: $("#chatNoteForm"),
  chatNoteQuestion: $("#chatNoteQuestion"),
  chatNoteAsk: $("#chatNoteAsk"),
  chatNotesError: $("#chatNotesError"),
  chatSelectionAction: $("#chatSelectionAction"),
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
      : health.ai_configured ? `${health.ai_provider} 已就绪` : "待配置语音与文本 API";
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
      try {
        const created = JSON.parse(request.responseText);
        state.expandedJobId = created.id;
        state.jobsInitialized = true;
      } catch { /* The next refresh will still show the newest task. */ }
      clearFile();
      elements.context.value = "";
      document.body.classList.remove("show-upload");
      elements.newMeeting.textContent = "新建会议";
      if (desktopMedia.matches) setDesktopView("jobs");
      await loadJobs();
      if (!desktopMedia.matches) $("#jobsSection").scrollIntoView({ behavior: "smooth", block: "start" });
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

const usageOperationLabels = {
  transcription: "语音转写",
  review_transcription: "校对复听转写",
  summary: "生成纪要",
  summary_regeneration: "重新生成纪要",
  review_detection: "校对词语检测",
  review_refinement: "校对结果细化",
  chat: "会议问答",
  chat_title: "对话标题生成",
  chat_note: "词语标注释义",
};

const usageStatusLabels = {
  success: "成功",
  http_error: "HTTP 错误",
  network_error: "网络错误",
  api_error: "API 错误",
  invalid_response: "响应无效",
  mock: "模拟调用（未调用真实 API）",
};

function usageValue(value) {
  return Number.isInteger(value) && value >= 0 ? value.toLocaleString("zh-CN") : "未报告";
}

function usageMetric(label, value) {
  const item = document.createElement("div");
  item.className = "usage-metric";
  const name = document.createElement("span");
  name.textContent = label;
  const number = document.createElement("strong");
  number.textContent = value;
  item.append(name, number);
  return item;
}

function renderUsage(job, card) {
  const panel = $(".usage-panel", card);
  panel.open = state.usageExpandedJobIds.has(job.id);
  panel.addEventListener("toggle", () => {
    if (panel.open) state.usageExpandedJobIds.add(job.id);
    else state.usageExpandedJobIds.delete(job.id);
  });
  const summaryNode = $(".usage-summary", panel);
  const note = $(".usage-note", panel);
  const callsNode = $(".usage-calls", panel);
  const summary = job.usage_summary;
  const calls = Array.isArray(job.usage_calls) ? job.usage_calls : null;

  if (!calls || calls.length === 0) {
    note.textContent = "尚未记录用量；历史任务无法补算。";
    return;
  }

  summaryNode.append(
    usageMetric("已报告 Token", usageValue(summary?.total_tokens)),
    usageMetric("输入 Token", usageValue(summary?.input_tokens)),
    usageMetric("输出 Token", usageValue(summary?.output_tokens)),
    usageMetric("缓存输入 Token", usageValue(summary?.cached_input_tokens)),
    usageMetric("ASR 时长", Number.isFinite(summary?.asr_duration_seconds)
      ? `${formatDuration(summary.asr_duration_seconds)}${summary.missing_asr_duration_calls ? " + 未报告" : ""}`
      : "未报告"),
  );

  const callCount = usageValue(summary?.call_count);
  const textCount = usageValue(summary?.text_call_count);
  const asrCount = usageValue(summary?.asr_call_count);
  const mockCount = usageValue(summary?.mock_call_count);
  const failedCount = usageValue(summary?.failed_call_count);
  const missingText = usageValue(summary?.missing_text_usage_calls);
  const missingAsr = usageValue(summary?.missing_asr_duration_calls);
  note.textContent = `调用 ${callCount} 次（文本 ${textCount} · ASR ${asrCount} · 模拟 ${mockCount}） · 失败 ${failedCount} 次 · 缺少文本 Token 统计 ${missingText} 次 · ASR 时长未报告 ${missingAsr} 次。缓存输入已包含在输入 Token 中；ASR 按音频时长统计。Token 统计不等同于订阅额度扣减或账单金额。`;

  const heading = document.createElement("h3");
  heading.className = "usage-calls-heading";
  heading.textContent = "各阶段调用明细";
  callsNode.appendChild(heading);

  for (const call of calls) {
    const row = document.createElement("article");
    row.className = "usage-call";
    const title = document.createElement("div");
    title.className = "usage-call-title";
    const operation = document.createElement("strong");
    operation.textContent = usageOperationLabels[call.operation] || call.operation || "未知阶段";
    const status = document.createElement("span");
    status.className = `usage-status${call.status === "success" ? " success" : call.status === "mock" ? " mock" : ""}`;
    status.textContent = usageStatusLabels[call.status] || call.status || "状态未知";
    title.append(operation, status);

    const metadata = document.createElement("p");
    metadata.className = "usage-call-meta";
    const kind = call.kind === "asr" ? "ASR" : call.kind === "text" ? "文本" : "类型未知";
    const model = call.model || "模型未记录";
    const attempt = Number.isInteger(call.attempt) && call.attempt > 1 ? ` · 第 ${call.attempt} 次请求（重试）` : "";
    const createdAt = call.created_at ? new Date(call.created_at) : null;
    const time = createdAt && !Number.isNaN(createdAt.getTime())
      ? createdAt.toLocaleString("zh-CN", { timeZone: "Asia/Shanghai", hour12: false }) : "";
    metadata.textContent = `${kind} · ${model}${attempt}${time ? ` · ${time}` : ""}`;

    const values = document.createElement("p");
    values.className = "usage-call-values";
    if (call.kind === "asr") {
      values.textContent = `ASR 时长：${Number.isFinite(call.audio_duration_seconds) ? formatDuration(call.audio_duration_seconds) : "未报告"} · 按音频时长统计`;
    } else {
      values.textContent = `输入：${usageValue(call.input_tokens)} · 输出：${usageValue(call.output_tokens)} · 总计：${usageValue(call.total_tokens)} · 缓存输入：${usageValue(call.cached_input_tokens)}`;
    }
    row.append(title, metadata, values);

    if (call.request_id) {
      const requestId = document.createElement("p");
      requestId.className = "usage-request-id";
      requestId.textContent = `请求 ID：${call.request_id}`;
      row.appendChild(requestId);
    }
    callsNode.appendChild(row);
  }
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

function minutesVersionLabel(version, index, total) {
  const label = version.source === "legacy"
    ? "已保存纪要（历史首次版不可恢复）"
    : index === 0 ? "首次生成" : `第 ${index + 1} 版`;
  const time = new Date(version.created_at).toLocaleString("zh-CN");
  return `${label}${index === total - 1 ? " · 最新" : ""} · ${time}`;
}

function renderDiffCell(cell, side) {
  const element = document.createElement("div");
  element.className = `diff-cell ${side} ${cell?.kind || "empty"}`;
  const gutter = document.createElement("span");
  gutter.className = "diff-gutter";
  const source = document.createElement("span");
  source.className = "diff-source";
  if (cell) {
    const changed = cell.kind === "changed";
    const sign = cell.kind === "removed" || (changed && side === "left")
      ? "−" : cell.kind === "added" || (changed && side === "right") ? "+" : "";
    gutter.textContent = `${sign} ${cell.line_number}`;
    const characters = Array.from(cell.text);
    let cursor = 0;
    for (const [start, end] of cell.highlights) {
      source.appendChild(document.createTextNode(characters.slice(cursor, start).join("")));
      const mark = document.createElement("mark");
      mark.textContent = characters.slice(start, end).join("");
      source.appendChild(mark);
      cursor = end;
    }
    const remaining = characters.slice(cursor).join("");
    if (remaining) source.appendChild(document.createTextNode(remaining));
    if (!source.hasChildNodes()) source.textContent = "\u00a0";
  } else {
    source.textContent = "\u00a0";
  }
  element.append(gutter, source);
  return element;
}

function renderMinutesDiff(container, result) {
  container.replaceChildren();
  for (const row of result.rows) {
    container.append(renderDiffCell(row.left, "left"), renderDiffCell(row.right, "right"));
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
  if (response.status === 204) return null;
  return response.json();
}

function availableChatJobs() {
  return state.jobs.filter((job) => job.status === "completed" && job.minutes && job.transcript);
}

function meetingTitle(job) {
  if (!job.minutes) return "";
  const heading = job.minutes.match(/^\s*#\s+(.+)$/m)?.[1];
  if (heading) return heading.replace(/[\r*_`]/g, "").trim();
  const summary = job.minutes.split("\n").map((line) => line.trim()).find((line) => (
    line && !/^(?:#{1,6}\s|[-*+]\s|\||>|\d+[.)]\s)/.test(line)
  ));
  return summary ? summary.slice(0, 80) : job.context.trim().slice(0, 80);
}

function setDesktopView(view) {
  if (state.desktopView === "source" && view !== "source") {
    state.sourceSelectionToken += 1;
    for (const media of elements.sourcePlayerMedia.querySelectorAll("audio, video")) media.pause();
    elements.sourcePlayerMedia.replaceChildren();
  }
  state.desktopView = view;
  if (view !== "chat") clearChatSelection();
  elements.chatNotesPanel.classList.toggle("hidden", view !== "notes");
  elements.sourcePlayer.classList.toggle("hidden", view !== "source");
  elements.chatNotesToggle.setAttribute("aria-expanded", String(view === "notes"));
  for (const name of ["chat", "jobs", "upload", "notes", "source"]) {
    document.body.classList.toggle(`desktop-view-${name}`, view === name);
  }
  document.body.classList.toggle("show-upload", view === "upload");
  elements.newMeeting.textContent = view === "upload" ? "收起上传" : "新建会议";
  for (const link of document.querySelectorAll("[data-desktop-view]")) {
    if (link.dataset.desktopView === view) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  }
}

function renderDesktopMeetingList() {
  const list = elements.desktopMeetingList;
  const signature = JSON.stringify(state.jobs.map((job) => [
    job.id, job.filename, meetingTitle(job), job.status, job.id === state.expandedJobId,
  ]));
  if (signature === state.desktopMeetingListSignature) return;
  state.desktopMeetingListSignature = signature;
  const previousScroll = list.scrollTop;
  const focusedJobId = list.contains(document.activeElement) ? document.activeElement.dataset.jobId : null;
  list.replaceChildren();
  elements.desktopMeetingCount.textContent = `${state.jobs.length} 场`;
  const statusLabels = { queued: "排队中", processing: "处理中", completed: "已完成", failed: "失败" };
  for (const job of state.jobs) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "desktop-meeting-item";
    button.dataset.jobId = job.id;
    button.classList.toggle("active", job.id === state.expandedJobId);
    if (job.id === state.expandedJobId) button.setAttribute("aria-current", "true");
    const title = document.createElement("strong");
    title.textContent = meetingTitle(job) || job.filename;
    const meta = document.createElement("span");
    meta.textContent = `${job.filename} · ${statusLabels[job.status] || job.status}`;
    button.append(title, meta);
    button.addEventListener("click", () => {
      state.expandedJobId = job.id;
      setDesktopView("jobs");
      renderJobs();
      elements.jobsList.scrollTop = 0;
    });
    list.appendChild(button);
  }
  list.scrollTop = previousScroll;
  if (focusedJobId) list.querySelector(`[data-job-id="${CSS.escape(focusedJobId)}"]`)?.focus({ preventScroll: true });
}

function openMeetingChat(jobId) {
  if (state.chatLoading) return;
  state.selectedChatJobIds = new Set([jobId]);
  clearMismatchedChatSession();
  setChatError();
  renderChatScope();
  if (desktopMedia.matches) setDesktopView("chat");
  else elements.chatSection.scrollIntoView({ behavior: "smooth", block: "start" });
  elements.chatQuestion.focus({ preventScroll: true });
}

function openMeetingRecord(jobId) {
  if (!state.jobs.some((job) => job.id === jobId)) return;
  elements.chatScope.open = false;
  state.expandedJobId = jobId;
  setDesktopView("jobs");
  renderJobs();
  if (desktopMedia.matches) {
    elements.jobsList.scrollTop = 0;
  } else {
    elements.jobsList.querySelector(`[data-job-id="${CSS.escape(jobId)}"]`)
      ?.scrollIntoView({ behavior: "smooth", block: "start" });
  }
}

function setChatError(message = "") {
  elements.chatError.textContent = message;
  elements.chatError.classList.toggle("hidden", !message);
}

function selectedChatIds(jobs = availableChatJobs()) {
  return jobs.filter((job) => (
    state.selectedChatJobIds === null || state.selectedChatJobIds.has(job.id)
  )).map((job) => job.id);
}

function chatScopeKey(jobs = availableChatJobs()) {
  return JSON.stringify(selectedChatIds(jobs).sort());
}

function clearMismatchedChatSession() {
  const session = state.chatSessions.find((item) => item.id === state.activeChatSessionId);
  if (session && JSON.stringify([...session.scope_job_ids].sort()) !== chatScopeKey()) {
    state.activeChatSessionId = null;
  }
}

function renderChatScope() {
  const jobs = availableChatJobs();
  const signature = JSON.stringify(jobs.map((job) => [job.id, job.filename, meetingTitle(job)]));
  if (signature !== state.chatScopeJobsSignature) {
    state.chatScopeJobsSignature = signature;
    elements.chatScopeOptions.replaceChildren();
    for (const job of jobs) {
      const row = document.createElement("div");
      row.className = "chat-scope-option";
      const label = document.createElement("label");
      const checkbox = document.createElement("input");
      checkbox.type = "checkbox";
      checkbox.value = job.id;
      const name = document.createElement("span");
      name.textContent = `${job.filename} · ${meetingTitle(job) || "会议主题未提取"}`;
      label.append(checkbox, name);
      const record = document.createElement("button");
      record.type = "button";
      record.className = "chat-scope-record";
      record.dataset.jobId = job.id;
      record.textContent = "查看记录 ↗";
      record.setAttribute("aria-label", `查看「${meetingTitle(job) || job.filename}」的处理记录`);
      record.addEventListener("click", () => openMeetingRecord(job.id));
      row.append(label, record);
      elements.chatScopeOptions.appendChild(row);
    }
    if (!jobs.length) {
      const empty = document.createElement("p");
      empty.className = "chat-scope-empty";
      empty.textContent = "暂无可询问的会议";
      elements.chatScopeOptions.appendChild(empty);
    }
  }
  const ids = selectedChatIds(jobs);
  const onlySelectedJob = ids.length === 1 ? jobs.find((job) => job.id === ids[0]) : null;
  renderChatSessions();
  elements.chatScopeSummary.textContent = `已选 ${ids.length} / ${jobs.length} 场会议`;
  elements.chatRecordOpen.disabled = jobs.length === 0;
  elements.chatRecordOpen.textContent = onlySelectedJob ? "查看处理记录 ↗" : "选择处理记录 ↗";
  elements.chatRecordOpen.title = onlySelectedJob
    ? `查看「${meetingTitle(onlySelectedJob) || onlySelectedJob.filename}」的处理记录`
    : "从查找范围中选择要打开的会议处理记录";
  elements.chatScopeOptions.querySelectorAll('input[type="checkbox"]').forEach((checkbox) => {
    checkbox.checked = ids.includes(checkbox.value);
    checkbox.disabled = state.chatLoading;
  });
  elements.chatSelectAll.disabled = state.chatLoading || jobs.length === 0 || ids.length === jobs.length;
  elements.chatSelectNone.disabled = state.chatLoading || ids.length === 0;
  elements.chatQuestion.disabled = state.chatLoading || ids.length === 0;
  elements.chatSend.disabled = state.chatLoading || ids.length === 0;
  elements.chatSend.textContent = state.chatLoading ? "查找中…" : "发送 →";
  elements.chatHint.textContent = !jobs.length
    ? "会议完成纪要和转写后，就可以在这里提问。"
    : ids.length
      ? "从所选会议的纪要和完整转写中查找依据，并列出参考会议。"
      : "请先勾选至少一场会议。";
  renderChatMessages();
}

function renderChatSessions() {
  const list = elements.chatSessionList;
  const orderedSessions = [...state.chatSessions].sort((left, right) => (
    new Date(right.updated_at || right.created_at) - new Date(left.updated_at || left.created_at)
  ));
  const signature = JSON.stringify([
    state.activeChatSessionId, state.chatLoading,
    orderedSessions.map((session) => [
      session.id, session.title, session.updated_at, session.scope_job_ids?.length,
      session.title_is_manual,
      session.title_generated_by_ai,
      session.messages?.find((message) => message.role === "user")?.content,
    ]),
  ]);
  if (signature === state.chatHistorySignature) return;
  state.chatHistorySignature = signature;
  const scrollTop = list.scrollTop;
  list.replaceChildren();
  const addItem = (id, title, firstQuestion, meta, active, titleSource = "") => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `chat-session-item${active ? " active" : ""}`;
    button.setAttribute("aria-current", active ? "true" : "false");
    button.disabled = state.chatLoading;
    const titleRow = document.createElement("span");
    titleRow.className = "chat-session-title-row";
    const name = document.createElement("strong");
    name.textContent = title;
    name.title = title;
    titleRow.append(name);
    if (titleSource) {
      const source = document.createElement("span");
      source.className = "chat-session-title-source";
      source.textContent = titleSource;
      titleRow.append(source);
    }
    const question = document.createElement("span");
    question.className = "chat-session-question";
    question.textContent = firstQuestion || "暂无提问";
    question.title = firstQuestion || "暂无提问";
    const details = document.createElement("span");
    details.className = "chat-session-meta";
    details.textContent = meta;
    button.setAttribute("aria-label", `${title}${titleSource ? `，${titleSource}` : ""}。${firstQuestion || "暂无提问"}。${meta}`);
    button.append(titleRow, question, details);
    button.addEventListener("click", () => {
      if (!id) {
        state.activeChatSessionId = null;
        elements.chatQuestion.value = "";
        setChatError();
      } else {
        const session = state.chatSessions.find((item) => item.id === id);
        if (!session) return;
        state.activeChatSessionId = session.id;
        state.selectedChatJobIds = new Set(session.scope_job_ids || []);
      }
      renderChatScope();
    });
    list.appendChild(button);
  };
  addItem(null, "新对话", "尚未提问", "尚未保存", !state.activeChatSessionId);
  for (const session of orderedSessions) {
    const count = (session.scope_job_ids || []).length;
    const timestamp = session.updated_at || session.created_at;
    const date = timestamp ? new Date(timestamp) : null;
    const time = date && !Number.isNaN(date.getTime())
      ? `${date.getMonth() + 1}/${date.getDate()} ${String(date.getHours()).padStart(2, "0")}:${String(date.getMinutes()).padStart(2, "0")}`
      : "";
    const firstQuestion = session.messages?.find((message) => message.role === "user")?.content || "";
    const titleSource = session.title_is_manual
      ? "自定义" : session.title_generated_by_ai ? "AI 生成" : "";
    addItem(session.id, session.title || "新对话", firstQuestion,
      `${count} 场会议${time ? ` · ${time}` : ""}`,
      state.activeChatSessionId === session.id, titleSource);
  }
  list.scrollTop = scrollTop;
  const activeSession = state.chatSessions.find((session) => session.id === state.activeChatSessionId);
  elements.chatSessionId.classList.toggle("hidden", !activeSession);
  elements.chatSessionIdValue.textContent = activeSession?.id || "";
  elements.chatSessionIdValue.title = activeSession?.id || "";
  elements.chatSessionIdCopy.textContent = "复制会话 ID";
  elements.chatSessionIdCopy.setAttribute("aria-label", activeSession
    ? `复制会话 ID：${activeSession.id}` : "复制会话 ID");
  elements.chatNew.disabled = state.chatLoading;
  elements.chatRename.disabled = state.chatLoading || !state.activeChatSessionId;
  elements.chatDelete.disabled = state.chatLoading || !state.activeChatSessionId;
}

async function loadChatSessions() {
  try {
    const sessions = await requestJSON("/api/chat/sessions");
    state.chatSessions = Array.isArray(sessions) ? sessions : [];
    for (const session of state.chatSessions) session.messages ||= [];
    if (!state.activeChatSessionId && state.chatSessions.length) {
      state.activeChatSessionId = state.chatSessions[0].id;
      state.selectedChatJobIds = new Set(state.chatSessions[0].scope_job_ids || []);
    }
    renderChatScope();
  } catch (error) { setChatError(error.message || "无法加载已保存对话"); }
}

function renderAnnotatedMessageBody(body, message) {
  const content = message.content;
  const notes = state.chatNotes.filter((note) => (
    note.message_id === message.id
    && Number.isInteger(note.selection_start)
    && Number.isInteger(note.selection_end)
    && note.selection_start >= 0
    && note.selection_end <= content.length
    && note.selection_end > note.selection_start
    && content.slice(note.selection_start, note.selection_end) === note.phrase
  )).sort((a, b) => a.selection_start - b.selection_start || b.selection_end - a.selection_end);
  let position = 0;
  for (const note of notes) {
    if (note.selection_start < position) continue;
    body.appendChild(document.createTextNode(content.slice(position, note.selection_start)));
    const marker = document.createElement("button");
    marker.type = "button";
    marker.className = "chat-note-marker";
    marker.textContent = note.phrase;
    marker.title = `打开「${note.phrase}」的标注笔记`;
    marker.setAttribute("aria-label", marker.title);
    marker.addEventListener("click", () => openChatNotes(note.id));
    body.appendChild(marker);
    position = note.selection_end;
  }
  body.appendChild(document.createTextNode(content.slice(position)));
}

function sourceTime(seconds) {
  const total = Math.max(0, Math.floor(seconds));
  return `${String(Math.floor(total / 3600)).padStart(2, "0")}:${String(Math.floor(total / 60) % 60).padStart(2, "0")}:${String(total % 60).padStart(2, "0")}`;
}

function sourceTimeRange(passage) {
  if (!Number.isFinite(passage?.start_seconds)) return "点开后定位时间";
  const start = sourceTime(passage.start_seconds);
  return Number.isFinite(passage.end_seconds) && passage.end_seconds > passage.start_seconds
    ? `${start}–${sourceTime(passage.end_seconds)}` : start;
}

async function selectSourcePassage(source, passage, button) {
  const selectionToken = ++state.sourceSelectionToken;
  for (const item of elements.sourcePlayerList.querySelectorAll("button")) {
    item.classList.toggle("active", item === button);
  }
  elements.sourcePlayerMedia.replaceChildren();
  const sourceJob = state.jobs.find((job) => job.id === source.job_id);
  const title = sourceJob ? meetingTitle(sourceJob) : source.filename;
  elements.sourcePlayerMeeting.textContent = `${title || "会议主题未提取"} · ${source.filename}`;
  const mediaURL = `/api/jobs/${encodeURIComponent(source.job_id)}/source`;
  elements.sourcePlayerOriginal.href = mediaURL;
  const hasPassage = Boolean(passage);
  let position = passage || { text: "暂无匹配的转写片段，从原片开头播放。", start_seconds: 0 };
  elements.sourcePlayerContext.textContent = position.text;
  if (hasPassage && !Number.isFinite(position.start_seconds)) {
    elements.sourcePlayerStatus.textContent = "正在从原始音视频定位这段话，首次定位可能需要等待…";
    try {
      position = await requestJSON(`/api/jobs/${encodeURIComponent(source.job_id)}/locate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: passage.text }),
      });
      Object.assign(passage, position);
    } catch (error) {
      if (selectionToken === state.sourceSelectionToken && state.desktopView === "source") {
        elements.sourcePlayerStatus.textContent = error.message || "暂时无法定位，可打开完整原始文件";
      }
      return;
    }
  }
  if (selectionToken !== state.sourceSelectionToken || state.desktopView !== "source") return;
  button.querySelector("span").textContent = sourceTimeRange(position);
  const timeRange = sourceTimeRange(position);
  elements.sourcePlayerContext.textContent = `${timeRange} · ${position.text}`;
  elements.sourcePlayerStatus.textContent = hasPassage
    ? "已定位到原片。可继续播放，查看前后语境。"
    : "暂无可靠的片段位置，现从原片开头播放。";
  const video = /\.(mp4|mov|mpeg|webm|mkv)$/i.test(source.filename);
  const media = document.createElement(video ? "video" : "audio");
  media.controls = true;
  media.preload = "metadata";
  media.setAttribute("aria-label", `原始音视频：${source.filename}`);
  const seekTo = Math.max(0, position.start_seconds - 2);
  media.src = `${mediaURL}#t=${seekTo}`;
  media.addEventListener("loadedmetadata", () => {
    try { media.currentTime = seekTo; } catch { /* Media fragments remain as fallback. */ }
  }, { once: true });
  if (video) {
    media.addEventListener("error", () => {
      if (media.dataset.fallback || selectionToken !== state.sourceSelectionToken) return;
      media.dataset.fallback = "audio";
      elements.sourcePlayerStatus.textContent = "浏览器无法播放此视频格式，已切换到同时间轴的原速音轨。";
      const audio = document.createElement("audio");
      audio.controls = true;
      audio.preload = "metadata";
      audio.src = `/api/jobs/${encodeURIComponent(source.job_id)}/source-audio#t=${seekTo}`;
      audio.addEventListener("loadedmetadata", () => {
        try { audio.currentTime = seekTo; } catch { /* Keep fragment seek. */ }
      }, { once: true });
      elements.sourcePlayerMedia.replaceChildren(audio);
      audio.play().catch(() => {});
    }, { once: true });
  }
  elements.sourcePlayerMedia.appendChild(media);
  media.play().catch(() => {});
}

function renderSourceEvidence(sources) {
  const evidence = document.createElement("div");
  evidence.className = "chat-evidence";
  const count = sources.reduce((sum, source) => sum + (source.passages?.length || 0), 0);
  const preview = document.createElement("span");
  const firstPassage = sources.flatMap((source) => source.passages || [])[0];
  preview.textContent = firstPassage
    ? `${sourceTimeRange(firstPassage)} · ${firstPassage.text}`
    : "可查看完整原始文件";
  const button = document.createElement("button");
  button.type = "button";
  button.textContent = `查看原片与上下文 · ${count} 段 →`;
  button.addEventListener("click", () => openSourceEvidence(sources, button));
  evidence.append(preview, button);
  return evidence;
}

function openSourceEvidence(sources, trigger) {
  state.sourceReturnView = state.desktopView === "notes" ? "notes" : "chat";
  elements.sourcePlayerClose.textContent = state.sourceReturnView === "notes"
    ? "← 返回标注笔记" : "← 返回问会议";
  state.sourceTrigger = trigger;
  elements.sourcePlayerList.replaceChildren();
  const entries = sources.flatMap((source) => (
    source.passages?.length
      ? source.passages.map((passage) => ({ source, passage }))
      : [{ source, passage: null }]
  ));
  for (const { source, passage } of entries) {
    const button = document.createElement("button");
    button.type = "button";
    const job = state.jobs.find((item) => item.id === source.job_id);
    const title = document.createElement("strong");
    title.textContent = job ? meetingTitle(job) || source.filename : source.filename;
    const time = document.createElement("span");
    time.textContent = passage ? sourceTimeRange(passage) : "无引用片段";
    const excerpt = document.createElement("small");
    excerpt.textContent = passage?.text || "查看完整原始文件";
    button.append(title, time, excerpt);
    button.addEventListener("click", () => selectSourcePassage(source, passage, button));
    elements.sourcePlayerList.appendChild(button);
  }
  setDesktopView("source");
  const first = elements.sourcePlayerList.querySelector("button");
  if (first) first.click();
  elements.sourcePlayerClose.focus({ preventScroll: true });
}

function closeSourcePlayer() {
  const returnView = state.sourceReturnView;
  setDesktopView(returnView);
  if (!desktopMedia.matches) {
    (returnView === "notes" ? elements.chatNotesPanel : elements.chatSection)
      .scrollIntoView({ behavior: "auto", block: "start" });
  }
  state.sourceTrigger?.focus({ preventScroll: true });
}

function renderChatMessages() {
  const ids = selectedChatIds();
  const messages = state.chatSessions.find((session) => session.id === state.activeChatSessionId)?.messages || [];
  const previousScroll = elements.chatMessages.scrollTop;
  const wasAtBottom = elements.chatMessages.scrollHeight - previousScroll - elements.chatMessages.clientHeight < 48;
  const changedSession = state.renderedChatSessionId !== state.activeChatSessionId;
  state.renderedChatSessionId = state.activeChatSessionId;
  elements.chatMessages.replaceChildren();
  if (!messages.length && !state.chatLoading) {
    const empty = document.createElement("p");
    empty.className = "chat-empty";
    empty.textContent = !ids.length
      ? "请先选择要查找的会议。"
      : ids.length === 1
        ? "问问这场会议讨论了什么、决定了什么。"
        : "跨会议查找曾经讨论的结论、时间和负责人。";
    elements.chatMessages.appendChild(empty);
  }
  for (const message of messages) {
    const article = document.createElement("article");
    article.className = `chat-message ${message.role === "user" ? "from-user" : "from-assistant"}`;
    const label = document.createElement("span");
    label.className = "chat-message-label";
    label.textContent = message.role === "user" ? "你" : "MeetMind";
    const body = document.createElement("div");
    body.className = "chat-message-body";
    body.dataset.messageId = message.id;
    renderAnnotatedMessageBody(body, message);
    article.append(label, body);
    if (message.role === "assistant" && message.retrieved) {
      const note = document.createElement("p");
      note.className = "chat-retrieval-note";
      note.textContent = "记录较长：回答依据为从完整转写中检索的相关片段及对应纪要。";
      article.appendChild(note);
    }
    if (message.role === "assistant" && message.sources?.length) {
      article.appendChild(renderSourceEvidence(message.sources));
    }
    elements.chatMessages.appendChild(article);
  }
  if (state.chatLoading) {
    const pending = document.createElement("p");
    pending.className = "chat-pending";
    pending.textContent = "正在会议纪要和转写中查找…";
    elements.chatMessages.appendChild(pending);
  }
  elements.chatMessages.scrollTop = changedSession || wasAtBottom
    ? elements.chatMessages.scrollHeight : previousScroll;
}

async function submitChat(event) {
  event.preventDefault();
  const ids = selectedChatIds();
  if (state.chatLoading || !ids.length) return;
  const question = elements.chatQuestion.value.trim();
  if (!question) {
    setChatError("请输入问题");
    elements.chatQuestion.focus();
    return;
  }
  state.chatLoading = true;
  setChatError();
  elements.chatQuestion.value = "";
  renderChatScope();
  try {
    let session = state.chatSessions.find((item) => item.id === state.activeChatSessionId);
    if (session && JSON.stringify([...(session.scope_job_ids || [])].sort()) !== JSON.stringify([...ids].sort())) session = null;
    if (!session) {
      session = await requestJSON("/api/chat/sessions", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ scope_job_ids: ids }) });
      state.chatSessions.unshift(session);
      state.activeChatSessionId = session.id;
    }
    const updated = await requestJSON(`/api/chat/sessions/${encodeURIComponent(session.id)}/messages`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ question }),
    });
    state.chatSessions = state.chatSessions.map((item) => item.id === updated.id ? updated : item);
  } catch (error) {
    elements.chatQuestion.value = question;
    setChatError(error.message || "提问失败，请稍后重试");
  } finally {
    state.chatLoading = false;
    renderChatScope();
    if (elements.chatQuestion.value) elements.chatQuestion.focus();
  }
}

function setChatNotesError(message = "") {
  elements.chatNotesError.textContent = message;
  elements.chatNotesError.classList.toggle("hidden", !message);
}

function clearChatSelection() {
  state.chatSelection = null;
  elements.chatSelectionAction.classList.add("hidden");
}

function updateChatSelection() {
  const selection = window.getSelection();
  if (!selection || selection.rangeCount !== 1 || selection.isCollapsed) {
    clearChatSelection();
    return;
  }
  const range = selection.getRangeAt(0);
  const startElement = range.startContainer.nodeType === Node.ELEMENT_NODE
    ? range.startContainer : range.startContainer.parentElement;
  const body = startElement?.closest(".chat-message-body");
  if (!body || !body.contains(range.endContainer) || !elements.chatMessages.contains(body)) {
    clearChatSelection();
    return;
  }
  const before = range.cloneRange();
  before.selectNodeContents(body);
  before.setEnd(range.startContainer, range.startOffset);
  const raw = range.toString();
  const phrase = raw.trim();
  const start = before.toString().length + raw.length - raw.trimStart().length;
  const end = start + phrase.length;
  const messages = state.chatSessions.find((session) => session.id === state.activeChatSessionId)?.messages || [];
  const message = messages.find((item) => item.id === body.dataset.messageId);
  if (!message || !phrase || phrase.length > 100 || message.content.slice(start, end) !== phrase) {
    clearChatSelection();
    return;
  }
  let excerptStart = Math.max(0, start - Math.floor((500 - phrase.length) / 2));
  const excerptEnd = Math.min(message.content.length, excerptStart + 500);
  excerptStart = Math.max(0, excerptEnd - 500);
  state.chatSelection = {
    phrase,
    message_id: message.id,
    selection_start: start,
    selection_end: end,
    source_excerpt: message.content.slice(excerptStart, excerptEnd),
    scope_job_ids: [...selectedChatIds()],
  };
  const rect = range.getBoundingClientRect();
  const action = elements.chatSelectionAction;
  action.classList.remove("hidden");
  const width = action.offsetWidth;
  action.style.left = `${Math.max(8, Math.min(window.innerWidth - width - 8, rect.left + rect.width / 2 - width / 2))}px`;
  action.style.top = `${Math.max(8, Math.min(window.innerHeight - action.offsetHeight - 8, rect.bottom + 8))}px`;
}

function renderChatNotes() {
  elements.chatNotesCount.textContent = state.chatNotes.length ? `(${state.chatNotes.length})` : "";
  const previousListScroll = elements.chatNotesList.scrollTop;
  elements.chatNotesList.replaceChildren();
  if (state.chatNotesLoading) {
    elements.chatNotesStatus.textContent = "正在加载标注笔记…";
  } else if (!state.chatNotes.length) {
    elements.chatNotesStatus.textContent = "暂无标注。选中对话中的词或短语即可开始。";
  } else {
    elements.chatNotesStatus.textContent = `已保存 ${state.chatNotes.length} 条标注`;
  }
  for (const note of state.chatNotes) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "chat-notes-item";
    button.classList.toggle("active", note.id === state.activeChatNoteId);
    button.setAttribute("aria-pressed", String(note.id === state.activeChatNoteId));
    const phrase = document.createElement("strong");
    phrase.textContent = note.phrase;
    const summary = document.createElement("span");
    summary.textContent = note.exchanges?.at(-1)?.answer?.slice(0, 100) || "等待解释";
    button.append(phrase, summary);
    button.addEventListener("click", () => openChatNotes(note.id));
    elements.chatNotesList.appendChild(button);
  }
  const active = state.chatNotes.find((note) => note.id === state.activeChatNoteId);
  const changedNote = state.renderedChatNoteId !== active?.id;
  state.renderedChatNoteId = active?.id || null;
  elements.chatNotesList.scrollTop = changedNote && active === state.chatNotes[0] ? 0 : previousListScroll;
  elements.chatNoteDetail.classList.toggle("hidden", !active);
  elements.chatNoteForm.classList.toggle("hidden", !active);
  elements.chatNotesPanel.classList.toggle("has-active-note", Boolean(active));
  if (!active) return;
  elements.chatNotePhrase.textContent = active.phrase;
  const pronunciation = active.pronunciation;
  const canSpeak = "speechSynthesis" in window && "SpeechSynthesisUtterance" in window;
  const isEnglishWord = /^[A-Za-z]+(?:['’-][A-Za-z]+)?$/.test(active.phrase.trim());
  elements.chatNotePronunciation.classList.toggle("hidden", !isEnglishWord);
  elements.chatNoteIpa.textContent = pronunciation?.ipa ? `${pronunciation.ipa}${pronunciation.language ? ` · ${pronunciation.language}` : ""}` : (isEnglishWord ? "音标暂不可用" : "");
  elements.chatNoteSpeak.disabled = !canSpeak;
  elements.chatNoteSpeak.title = canSpeak ? "播放英文发音" : "此浏览器不支持语音合成";
  elements.chatNoteExcerpt.textContent = active.source_excerpt ? `原文：${active.source_excerpt}` : "";
  elements.chatNoteExchanges.replaceChildren();
  for (const exchange of active.exchanges || []) {
    const block = document.createElement("div");
    block.className = "chat-note-exchange";
    if (exchange.question) {
      const question = document.createElement("p");
      question.className = "chat-note-exchange-question";
      question.textContent = exchange.question;
      block.appendChild(question);
    }
    const answer = document.createElement("p");
    answer.textContent = exchange.answer || "暂无解释";
    block.appendChild(answer);
    const evidence = exchange.sources?.length ? exchange.sources : active.sources;
    if (evidence?.length) block.appendChild(renderSourceEvidence(evidence));
    elements.chatNoteExchanges.appendChild(block);
  }
  if (!active.exchanges?.length) {
    const empty = document.createElement("p");
    empty.className = "chat-notes-status";
    empty.textContent = "暂无解释，可以在下方提问。";
    elements.chatNoteExchanges.appendChild(empty);
  }
  if (changedNote) elements.chatNoteDetail.scrollTop = 0;
  elements.chatNoteAsk.disabled = state.chatNoteBusy;
  elements.chatNoteQuestion.disabled = state.chatNoteBusy;
  elements.chatNoteAsk.textContent = state.chatNoteBusy ? "解释中…" : "提问 →";
}

function openChatNotes(noteId = null, selectFirst = true) {
  if (noteId) state.activeChatNoteId = noteId;
  else if (selectFirst && !state.chatNotes.some((note) => note.id === state.activeChatNoteId)) {
    state.activeChatNoteId = state.chatNotes[0]?.id || null;
  }
  setDesktopView("notes");
  renderChatNotes();
  if (noteId) elements.chatNoteQuestion.focus({ preventScroll: true });
  else elements.chatNotesClose.focus({ preventScroll: true });
}

function closeChatNotes() {
  setDesktopView("chat");
  if (!desktopMedia.matches) elements.chatSection.scrollIntoView({ behavior: "auto", block: "start" });
  elements.chatNotesToggle.focus({ preventScroll: true });
}

async function loadChatNotes() {
  state.chatNotesLoading = true;
  renderChatNotes();
  try {
    const notes = await requestJSON("/api/chat/notes");
    state.chatNotes = Array.isArray(notes) ? notes : [];
    setChatNotesError();
    renderChatMessages();
  } catch (error) {
    setChatNotesError(error.message || "无法加载标注笔记");
  } finally {
    state.chatNotesLoading = false;
    renderChatNotes();
  }
}

async function createChatNote() {
  const selection = state.chatSelection;
  if (!selection || state.chatNoteBusy) return;
  clearChatSelection();
  window.getSelection()?.removeAllRanges();
  state.activeChatNoteId = null;
  openChatNotes(null, false);
  state.chatNoteBusy = true;
  elements.chatNotesStatus.textContent = `正在解释「${selection.phrase}」…`;
  setChatNotesError();
  try {
    const note = await requestJSON("/api/chat/notes", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...selection, session_id: state.activeChatSessionId }),
    });
    state.chatNotes = [note, ...state.chatNotes.filter((item) => item.id !== note.id)];
    state.activeChatNoteId = note.id;
    renderChatMessages();
  } catch (error) {
    setChatNotesError(error.message || "解释失败，请重新选中后重试");
  } finally {
    state.chatNoteBusy = false;
    renderChatNotes();
  }
}

async function askChatNote(event) {
  event.preventDefault();
  const noteId = state.activeChatNoteId;
  const question = elements.chatNoteQuestion.value.trim();
  if (!noteId || state.chatNoteBusy) return;
  if (!question) {
    setChatNotesError("请输入追问内容");
    elements.chatNoteQuestion.focus();
    return;
  }
  state.chatNoteBusy = true;
  let answered = false;
  setChatNotesError();
  renderChatNotes();
  try {
    const note = await requestJSON(`/api/chat/notes/${encodeURIComponent(noteId)}/ask`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question }),
    });
    state.chatNotes = [note, ...state.chatNotes.filter((item) => item.id !== note.id)];
    elements.chatNoteQuestion.value = "";
    answered = true;
  } catch (error) {
    setChatNotesError(error.message || "追问失败，请稍后重试");
  } finally {
    state.chatNoteBusy = false;
    renderChatNotes();
    if (answered) {
      elements.chatNotesList.scrollTop = 0;
      elements.chatNoteDetail.scrollTop = elements.chatNoteDetail.scrollHeight;
    }
    elements.chatNoteQuestion.focus();
  }
}

function appendHighlightedContext(container, contextText, originalTerm, termStart = null) {
  const termIndex = Number.isInteger(termStart)
    && contextText.slice(termStart, termStart + originalTerm.length) === originalTerm
    ? termStart : contextText.indexOf(originalTerm);
  if (termIndex < 0) {
    container.appendChild(document.createTextNode(contextText.slice(0, 60)));
    return;
  }
  const contextStart = Math.max(0, termIndex - 24);
  const contextEnd = Math.min(
    contextText.length,
    termIndex + originalTerm.length + 24,
  );
  const before = `${contextStart ? "…" : ""}${contextText.slice(contextStart, termIndex)}`;
  const after = `${contextText.slice(
    termIndex + originalTerm.length,
    contextEnd,
  )}${contextEnd < contextText.length ? "…" : ""}`;
  container.appendChild(document.createTextNode(before));
  const mark = document.createElement("mark");
  mark.textContent = originalTerm;
  container.appendChild(mark);
  container.appendChild(document.createTextNode(after));
}

function renderReviewItem(job, item) {
  const article = document.createElement("article");
  const pending = item.correction_term == null;
  article.className = `review-item ${pending ? "needs-review" : "supported"}`;

  const header = document.createElement("div");
  header.className = "review-item-heading";
  const time = document.createElement("strong");
  time.textContent = `${formatDuration(item.start_seconds)} – ${formatDuration(item.end_seconds)}`;
  const confidence = document.createElement("span");
  confidence.textContent = pending
    ? item.source === "agent"
      ? "Agent 标记 · 待人工确认"
      : item.requires_confirmation
        ? "两版转写冲突 · 待人工确认"
      : `待确认 · AI 估值 ${Math.round(item.confidence * 100)}%`
    : "已确认";
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
  const prefix = document.createElement("span");
  prefix.textContent = "附近上下文：";
  original.appendChild(prefix);
  appendHighlightedContext(original, item.context_text, item.original_term, item.term_start);
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
  labelText.textContent = `只确认这个词（原识别：${item.original_term}）`;
  const input = document.createElement("input");
  input.className = "review-correction";
  input.dataset.itemId = item.id;
  input.type = "text";
  input.maxLength = 100;
  input.autocomplete = "off";
  input.value = item.correction_term || "";
  input.placeholder = item.suggested_term
    ? `AI 建议：${item.suggested_term}`
    : "输入确认后的词";
  label.append(labelText, input);
  article.appendChild(label);

  const actions = document.createElement("div");
  actions.className = "review-item-actions";
  if (pending && item.source === "ai" && item.suggested_term) {
    const suggestion = document.createElement("button");
    suggestion.className = "review-suggestion";
    suggestion.type = "button";
    suggestion.textContent = `填入 AI 建议：${item.suggested_term}`;
    suggestion.addEventListener("click", () => {
      input.value = item.suggested_term;
      input.focus();
    });
    actions.appendChild(suggestion);
  }

  const keep = document.createElement("button");
  keep.className = "review-keep";
  keep.type = "button";
  keep.textContent = "保留原词";
  keep.addEventListener("click", () => { input.value = item.original_term; });
  actions.appendChild(keep);
  article.appendChild(actions);
  return article;
}

function addManualPending(container, correction, apply, contextText = "") {
  const selector = [
    `.manual-pending-item[data-segment-index="${correction.segment_index}"]`,
    `[data-term-start="${correction.term_start}"]`,
  ].join("");
  const existing = container.querySelector(selector);
  if (existing) {
    $("input", existing).value = correction.replacement;
    return;
  }

  const row = document.createElement("div");
  row.className = "manual-pending-item";
  row.dataset.segmentIndex = correction.segment_index;
  row.dataset.termStart = correction.term_start;
  row.dataset.originalTerm = correction.original_term;

  const copy = document.createElement("div");
  const title = document.createElement("strong");
  title.textContent = `${correction.original_term} →`;
  const replacement = document.createElement("input");
  replacement.type = "text";
  replacement.maxLength = 100;
  replacement.value = correction.replacement;
  replacement.setAttribute("aria-label", `把 ${correction.original_term} 修改为`);
  copy.append(title, replacement);
  if (contextText) {
    const context = document.createElement("p");
    appendHighlightedContext(context, contextText, correction.original_term, correction.term_start);
    copy.appendChild(context);
  }

  const remove = document.createElement("button");
  remove.type = "button";
  remove.textContent = "移除";
  remove.addEventListener("click", () => {
    row.remove();
    const hasAICorrections = Boolean(
      container.closest(".review-panel").querySelector(".review-correction"),
    );
    apply.classList.toggle("hidden", !container.children.length && !hasAICorrections);
  });
  row.append(copy, remove);
  container.appendChild(row);
  apply.classList.remove("hidden");
}

function setupManualReview(job, panel, apply) {
  const section = $(".manual-review", panel);
  const form = $(".manual-review-form", section);
  const original = $(".manual-original", form);
  const replacement = $(".manual-replacement", form);
  const error = $(".manual-review-error", section);
  const results = $(".manual-review-results", section);
  const pending = $(".manual-review-pending", section);
  section.classList.remove("hidden");

  (job.review_manual_corrections || []).forEach((correction) => {
    addManualPending(pending, correction, apply);
  });

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const originalTerm = original.value.trim();
    const replacementTerm = replacement.value.trim();
    error.classList.add("hidden");
    results.replaceChildren();
    if (!originalTerm || !replacementTerm) {
      error.textContent = "请同时填写原词和正确写法";
      error.classList.remove("hidden");
      return;
    }

    const button = $("button[type='submit']", form);
    button.disabled = true;
    button.textContent = "正在查找…";
    try {
      const matches = await requestJSON(
        `/api/jobs/${job.id}/review/search?term=${encodeURIComponent(originalTerm)}`,
      );
      if (!matches.length) {
        error.textContent = "词级转写中没有找到这个原词，请检查文字是否完全一致";
        error.classList.remove("hidden");
        return;
      }
      const selection = document.createElement("div");
      selection.className = "manual-review-selection";
      const selectAllLabel = document.createElement("label");
      const selectAll = document.createElement("input");
      selectAll.type = "checkbox";
      selectAllLabel.append(selectAll, document.createTextNode("全选当前结果"));
      const count = document.createElement("span");
      const addSelected = document.createElement("button");
      addSelected.type = "button";
      selection.append(selectAllLabel, count, addSelected);

      const list = document.createElement("div");
      list.className = "manual-review-match-list";
      const choices = matches.map((match, index) => {
        const row = document.createElement("label");
        row.className = "manual-review-match";
        const checkbox = document.createElement("input");
        checkbox.type = "checkbox";
        const time = document.createElement("strong");
        time.textContent = `第 ${index + 1} 处 · ${formatDuration(match.start_seconds)}`;
        const context = document.createElement("span");
        appendHighlightedContext(context, match.context_text, match.original_term, match.term_start);
        row.append(checkbox, time, context);
        checkbox.addEventListener("change", updateSelection);
        list.appendChild(row);
        return { match, checkbox };
      });

      function updateSelection() {
        const selectedCount = choices.filter(({ checkbox }) => checkbox.checked).length;
        selectAll.checked = selectedCount === choices.length;
        selectAll.indeterminate = selectedCount > 0 && selectedCount < choices.length;
        count.textContent = `已选 ${selectedCount} / ${choices.length}`;
        addSelected.textContent = `加入选中位置（${selectedCount}）`;
        addSelected.disabled = selectedCount === 0;
      }

      selectAll.addEventListener("change", () => {
        choices.forEach(({ checkbox }) => { checkbox.checked = selectAll.checked; });
        updateSelection();
      });
      addSelected.addEventListener("click", () => {
        choices.filter(({ checkbox }) => checkbox.checked).forEach(({ match }) => {
          addManualPending(
            pending,
            {
              segment_index: match.segment_index,
              term_start: match.term_start,
              original_term: match.original_term,
              replacement: replacementTerm,
            },
            apply,
            match.context_text,
          );
        });
        original.value = "";
        replacement.value = "";
        results.replaceChildren();
      });
      updateSelection();
      results.append(selection, list);
    } catch (requestError) {
      error.textContent = requestError.message;
      error.classList.remove("hidden");
    } finally {
      button.disabled = false;
      button.textContent = "查找位置";
    }
  });
}

function renderReview(job, card) {
  if (job.status !== "completed" || !job.transcript) return;
  const panel = $(".review-panel", card);
  const start = $(".review-start", panel);
  const progress = $(".review-progress", panel);
  const error = $(".review-error", panel);
  const list = $(".review-list", panel);
  const apply = $(".review-apply", panel);
  const fillAll = $(".review-fill-all", panel);
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
    state.expandedJobId = job.id;
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
    const listHeading = $(".review-list-heading", panel);
    if (!job.review_items.length) {
      const empty = document.createElement("p");
      empty.className = "review-empty";
      empty.textContent = "原速音频复核完成，未发现明显需要人工确认的词。";
      list.appendChild(empty);
    } else {
      const pendingCount = job.review_items.filter((item) => item.correction_term == null).length;
      const suggestedItems = job.review_items.filter((item) => (
        item.source === "ai" && !item.requires_confirmation
        && item.correction_term == null && item.suggested_term.trim()
      ));
      $("strong", listHeading).textContent = `疑似词 · 待确认 ${pendingCount} / ${job.review_items.length}`;
      listHeading.classList.remove("hidden");
      if (suggestedItems.length) {
        fillAll.classList.remove("hidden");
        fillAll.textContent = `一键填入 ${suggestedItems.length} 条 AI 建议`;
        fillAll.addEventListener("click", () => {
          const fields = new Map(
            [...panel.querySelectorAll(".review-correction")].map((field) => [
              field.dataset.itemId, field,
            ]),
          );
          suggestedItems.forEach((item) => {
            const field = fields.get(item.id);
            if (field) field.value = item.suggested_term.trim();
          });
          fillAll.textContent = `已填入 ${suggestedItems.length} 条 AI 建议`;
        });
      }
      job.review_items.forEach((item) => list.appendChild(renderReviewItem(job, item)));
      apply.classList.remove("hidden");
    }
    setupManualReview(job, panel, apply);
    apply.textContent = status === "completed"
      ? "更新修正并重新生成纪要 →"
      : "应用以上修正并重新生成纪要 →";
    async function submitReview() {
      state.expandedJobId = job.id;
      const corrections = [...panel.querySelectorAll(".review-correction")].map((field) => ({
        item_id: field.dataset.itemId,
        replacement: field.value.trim(),
      })).filter((item) => item.replacement);
      const manualCorrections = [...panel.querySelectorAll(".manual-pending-item")].map((row) => ({
        segment_index: Number(row.dataset.segmentIndex),
        term_start: Number(row.dataset.termStart),
        original_term: row.dataset.originalTerm,
        replacement: $("input", row).value.trim(),
      })).filter((item) => item.replacement);
      if (!corrections.length && !manualCorrections.length) {
        error.textContent = "请先确认一个疑似词，或主动搜索并添加一处纠偏。";
        error.classList.remove("hidden");
        return;
      }
      apply.disabled = true;
      fillAll.disabled = true;
      apply.textContent = "正在应用修正…";
      try {
        await requestJSON(`/api/jobs/${job.id}/review/apply`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            corrections,
            manual_corrections: manualCorrections,
          }),
        });
        await loadJobs();
        startPolling();
      } catch (requestError) {
        apply.disabled = false;
        fillAll.disabled = false;
        apply.textContent = status === "completed"
          ? "更新修正并重新生成纪要 →"
          : "应用以上修正并重新生成纪要 →";
        error.textContent = requestError.message;
        error.classList.remove("hidden");
      }
    }
    apply.addEventListener("click", submitReview);
  }
}

function renderJob(job) {
  const fragment = elements.template.content.cloneNode(true);
  const card = $(".job-card", fragment);
  const toggle = $(".job-toggle", card);
  const expanded = state.expandedJobId === job.id;
  card.dataset.jobId = job.id;
  card.classList.add(job.status);
  card.classList.toggle("expanded", expanded);
  toggle.setAttribute("aria-expanded", String(expanded));
  $("span", toggle).textContent = expanded ? "收起" : "展开";
  toggle.addEventListener("click", () => {
    if (desktopMedia.matches) return;
    const shouldExpand = !card.classList.contains("expanded");
    document.querySelectorAll(".job-card.expanded").forEach((otherCard) => {
      if (otherCard === card) return;
      otherCard.classList.remove("expanded");
      const otherToggle = $(".job-toggle", otherCard);
      otherToggle.setAttribute("aria-expanded", "false");
      $("span", otherToggle).textContent = "展开";
      otherCard.querySelectorAll("audio").forEach((audio) => audio.pause());
    });
    card.classList.toggle("expanded", shouldExpand);
    toggle.setAttribute("aria-expanded", String(shouldExpand));
    $("span", toggle).textContent = shouldExpand ? "收起" : "展开";
    state.expandedJobId = shouldExpand ? job.id : null;
    if (!shouldExpand) card.querySelectorAll("audio").forEach((audio) => audio.pause());
  });
  const title = meetingTitle(job);
  const createdAt = new Date(job.created_at).toLocaleString("zh-CN");
  $(".job-title strong", card).textContent = title || job.filename;
  $(".job-title span", card).textContent = title
    ? `${job.filename} · ${createdAt}` : createdAt;
  const jobId = $(".job-id code", card);
  jobId.textContent = `会议 ID：${job.id}`;
  jobId.title = job.id;
  const copyJobId = $(".job-id button", card);
  copyJobId.textContent = "复制会议 ID";
  copyJobId.setAttribute("aria-label", `复制会议 ID：${job.id}`);
  copyJobId.addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(`会议 ID：${job.id}`);
      copyJobId.textContent = "已复制会议 ID ✓";
    } catch {
      copyJobId.textContent = "复制失败";
    }
    window.setTimeout(() => { copyJobId.textContent = "复制会议 ID"; }, 1800);
  });
  const chatShortcut = $(".job-chat", card);
  const canChat = job.status === "completed" && job.minutes && job.transcript;
  chatShortcut.disabled = !canChat;
  chatShortcut.title = canChat ? `询问：${title || job.filename}` : "会议完成后可询问";
  chatShortcut.setAttribute("aria-label", chatShortcut.title);
  if (canChat) chatShortcut.addEventListener("click", () => openMeetingChat(job.id));
  $(".job-state span", card).textContent = job.stage;
  $(".job-progress b", card).style.width = `${job.progress}%`;
  $(".job-progress > span", card).textContent = `${job.progress}%`;
  renderUsage(job, card);
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
      state.expandedJobId = job.id;
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
    const versions = job.minutes_versions || [];
    const versionTools = $(".result-version-tools", card);
    const versionSelect = $(".result-version-select", card);
    const compareToggle = $(".compare-toggle", card);
    const compare = $(".result-compare", card);
    const actions = $(".result-actions", card);
    const minutesLink = $("[data-download='minutes']", card);
    let selectedVersion = state.selectedMinutesVersions.get(job.id) || versions.length;
    if (selectedVersion > versions.length) selectedVersion = versions.length;
    let showingMinutes = Boolean(job.minutes);
    let comparing = state.comparingJobIds.has(job.id) && versions.length > 1;
    let current = "";
    versions.forEach((version, index) => {
      const option = document.createElement("option");
      option.value = String(index + 1);
      option.textContent = minutesVersionLabel(version, index, versions.length);
      versionSelect.appendChild(option);
    });
    if (versions.length) versionSelect.value = String(selectedVersion);
    versionTools.classList.toggle("hidden", versions.length === 0);
    compareToggle.classList.toggle("hidden", versions.length < 2);
    const refreshResult = () => {
      const canCompare = showingMinutes && comparing && versions.length > 1;
      $(".job-content-grid", card).classList.toggle("comparing", canCompare);
      content.classList.toggle("hidden", canCompare);
      compare.classList.toggle("hidden", !canCompare);
      actions.classList.toggle("hidden", canCompare);
      versionTools.classList.toggle("hidden", !showingMinutes || versions.length === 0);
      compareToggle.setAttribute("aria-pressed", String(canCompare));
      compareToggle.textContent = canCompare ? "退出差异对比" : versions[0]?.source === "legacy"
        ? "对比最早保存版与最新版差异" : "对比首次版与最新版差异";
      if (canCompare) {
        const first = versions[0];
        const latest = versions[versions.length - 1];
        $(".compare-first-title", compare).textContent = minutesVersionLabel(first, 0, versions.length);
        $(".compare-latest-title", compare).textContent = minutesVersionLabel(latest, versions.length - 1, versions.length);
        $(".compare-first-download", compare).href = `/api/jobs/${job.id}/minutes/1`;
        $(".compare-latest-download", compare).href = `/api/jobs/${job.id}/minutes/${versions.length}`;
        const status = $(".compare-status", compare);
        const diff = $(".compare-diff", compare);
        const result = window.MeetMindDiff.buildMinutesDiff(first.content, latest.content);
        renderMinutesDiff(diff, result);
        status.textContent = result.change_count
          ? `${result.change_count} 行有变化 · 红色为原版，绿色为新版；深色标出改动文字`
          : "两个版本内容相同";
        return;
      }
      current = showingMinutes
        ? (versions[selectedVersion - 1]?.content || job.minutes || "纪要尚未生成")
        : (job.transcript || "转写尚未生成");
      showResult(content, current, showingMinutes && Boolean(job.minutes));
      minutesLink.href = versions.length
        ? `/api/jobs/${job.id}/minutes/${selectedVersion}`
        : `/api/jobs/${job.id}/minutes`;
    };
    results.classList.remove("hidden");
    refreshResult();
    tabs.forEach((tab) => tab.addEventListener("click", () => {
      tabs.forEach((item) => item.classList.toggle("active", item === tab));
      showingMinutes = tab.dataset.tab === "minutes";
      refreshResult();
    }));
    versionSelect.addEventListener("change", () => {
      selectedVersion = Number(versionSelect.value);
      state.selectedMinutesVersions.set(job.id, selectedVersion);
      refreshResult();
    });
    compareToggle.addEventListener("click", () => {
      comparing = !comparing;
      if (comparing) state.comparingJobIds.add(job.id);
      else state.comparingJobIds.delete(job.id);
      refreshResult();
    });
    $(".copy-button", card).addEventListener("click", async (event) => {
      await navigator.clipboard.writeText(current);
      event.currentTarget.textContent = "已复制";
      setTimeout(() => { event.currentTarget.textContent = "复制内容"; }, 1500);
    });
    if (!job.minutes) minutesLink.classList.add("hidden");
    $("[data-download='audio']", card).href = `/api/jobs/${job.id}/audio`;
    const askMeeting = $(".ask-meeting", card);
    if (job.status === "completed" && job.minutes && job.transcript) {
      askMeeting.addEventListener("click", () => openMeetingChat(job.id));
    } else {
      askMeeting.classList.add("hidden");
    }
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
  const contentGrid = $(".job-content-grid", card);
  const reviewPanel = $(".review-panel", card);
  const hasResults = !$(".job-results", card).classList.contains("hidden");
  const hasReview = !reviewPanel.classList.contains("hidden");
  contentGrid.classList.toggle("hidden", !hasResults && !hasReview);
  contentGrid.classList.toggle("single-pane", !hasReview);
  return fragment;
}

function renderJobs() {
  if (!state.jobsInitialized) {
    const active = state.jobs.find((job) => (
      ["queued", "processing"].includes(job.status)
      || ["processing", "applying"].includes(job.review_status)
    ));
    state.expandedJobId = active?.id || state.jobs[0]?.id || null;
    state.jobsInitialized = true;
  } else if (
    state.expandedJobId
    && !state.jobs.some((job) => job.id === state.expandedJobId)
  ) {
    state.expandedJobId = state.jobs[0]?.id || null;
  }
  if (desktopMedia.matches && !state.expandedJobId && state.jobs.length) {
    state.expandedJobId = state.jobs[0].id;
  }
  const hasJobs = state.jobs.length > 0;
  document.body.classList.toggle("has-jobs", hasJobs);
  elements.newMeeting.classList.toggle("hidden", !hasJobs && !desktopMedia.matches);
  const previousScroll = elements.jobsList.scrollTop;
  elements.jobsList.replaceChildren();
  elements.emptyState.classList.toggle("hidden", hasJobs);
  const visibleJobs = desktopMedia.matches
    ? state.jobs.filter((job) => job.id === state.expandedJobId)
    : state.jobs;
  for (const job of visibleJobs) elements.jobsList.appendChild(renderJob(job));
  if (desktopMedia.matches) elements.jobsList.scrollTop = previousScroll;
  renderDesktopMeetingList();
  renderChatScope();
}

async function loadJobs() {
  try {
    const response = await fetch("/api/jobs", { cache: "no-store" });
    if (!response.ok) throw new Error("load failed");
    state.jobs = await response.json();
    if (desktopMedia.matches && state.desktopView === null) {
      const fromHash = window.location.hash === "#jobsSection" ? "jobs" : "chat";
      setDesktopView(state.jobs.length ? fromHash : "upload");
    }
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
elements.chatRecordOpen.addEventListener("click", () => {
  const ids = selectedChatIds();
  if (ids.length === 1) {
    openMeetingRecord(ids[0]);
    return;
  }
  elements.chatScope.open = true;
  const records = [...elements.chatScopeOptions.querySelectorAll(".chat-scope-record")];
  (records.find((record) => ids.includes(record.dataset.jobId)) || records[0])
    ?.focus({ preventScroll: true });
});
elements.chatScopeOptions.addEventListener("change", (event) => {
  if (state.chatLoading || event.target.type !== "checkbox") return;
  if (state.selectedChatJobIds === null) state.selectedChatJobIds = new Set(selectedChatIds());
  if (event.target.checked) state.selectedChatJobIds.add(event.target.value);
  else state.selectedChatJobIds.delete(event.target.value);
  if (selectedChatIds().length === availableChatJobs().length) state.selectedChatJobIds = null;
  clearMismatchedChatSession();
  setChatError();
  renderChatScope();
});
elements.chatSelectAll.addEventListener("click", () => {
  state.selectedChatJobIds = null;
  clearMismatchedChatSession();
  setChatError();
  renderChatScope();
});
elements.chatSelectNone.addEventListener("click", () => {
  state.selectedChatJobIds = new Set();
  clearMismatchedChatSession();
  setChatError();
  renderChatScope();
});
elements.chatForm.addEventListener("submit", submitChat);
elements.chatNew.addEventListener("click", () => {
  state.activeChatSessionId = null;
  elements.chatQuestion.value = "";
  setChatError();
  renderChatScope();
  elements.chatQuestion.focus();
});
elements.chatSessionIdCopy.addEventListener("click", async () => {
  const session = state.chatSessions.find((item) => item.id === state.activeChatSessionId);
  if (!session) return;
  try {
    await navigator.clipboard.writeText(`会话 ID：${session.id}`);
    elements.chatSessionIdCopy.textContent = "已复制会话 ID ✓";
  } catch {
    elements.chatSessionIdCopy.textContent = "复制失败";
  }
  window.setTimeout(() => { elements.chatSessionIdCopy.textContent = "复制会话 ID"; }, 1800);
});
elements.chatRename.addEventListener("click", async () => {
  const session = state.chatSessions.find((item) => item.id === state.activeChatSessionId);
  if (!session) return;
  const title = window.prompt("对话名称", session.title || "新对话");
  if (!title?.trim()) return;
  try {
    const updated = await requestJSON(`/api/chat/sessions/${encodeURIComponent(session.id)}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ title: title.trim() }) });
    state.chatSessions = state.chatSessions.map((item) => item.id === updated.id ? updated : item);
    renderChatSessions();
  } catch (error) { setChatError(error.message || "重命名失败"); }
});
elements.chatDelete.addEventListener("click", async () => {
  const id = state.activeChatSessionId;
  if (!id || !window.confirm("删除这段已保存对话？此操作无法撤销。")) return;
  try {
    await requestJSON(`/api/chat/sessions/${encodeURIComponent(id)}`, { method: "DELETE" });
    state.chatSessions = state.chatSessions.filter((item) => item.id !== id);
    state.activeChatSessionId = null;
    renderChatScope();
  } catch (error) { setChatError(error.message || "删除失败"); }
});
elements.chatNoteSpeak.addEventListener("click", () => {
  const note = state.chatNotes.find((item) => item.id === state.activeChatNoteId);
  if (!note?.phrase || !("speechSynthesis" in window)) return;
  window.speechSynthesis.cancel();
  const utterance = new SpeechSynthesisUtterance(note.phrase);
  utterance.lang = note.pronunciation?.language || "en-US";
  window.speechSynthesis.speak(utterance);
});
elements.chatNoteDelete.addEventListener("click", async () => {
  const id = state.activeChatNoteId;
  if (!id || !window.confirm("删除这条标注笔记？此操作无法撤销。")) return;
  try {
    await requestJSON(`/api/chat/notes/${encodeURIComponent(id)}`, { method: "DELETE" });
    state.chatNotes = state.chatNotes.filter((note) => note.id !== id);
    state.activeChatNoteId = state.chatNotes[0]?.id || null;
    renderChatNotes();
    renderChatMessages();
  } catch (error) { setChatNotesError(error.message || "删除标注失败"); }
});
elements.chatMessages.addEventListener("pointerup", () => window.setTimeout(updateChatSelection, 0));
elements.chatMessages.addEventListener("keyup", updateChatSelection);
elements.chatMessages.addEventListener("keydown", (event) => {
  if ((event.ctrlKey || event.metaKey) && event.key === "Enter" && state.chatSelection) {
    event.preventDefault();
    createChatNote();
  }
});
document.addEventListener("selectionchange", () => window.setTimeout(updateChatSelection, 0));
elements.chatSelectionAction.addEventListener("pointerdown", (event) => event.preventDefault());
elements.chatSelectionAction.addEventListener("click", createChatNote);
elements.chatNotesToggle.addEventListener("click", () => openChatNotes());
elements.chatNotesClose.addEventListener("click", closeChatNotes);
elements.sourcePlayerClose.addEventListener("click", closeSourcePlayer);
elements.chatNotesPanel.addEventListener("keydown", (event) => {
  if (event.key === "Escape") closeChatNotes();
});
elements.chatNoteForm.addEventListener("submit", askChatNote);
elements.chatQuestion.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
    event.preventDefault();
    elements.chatForm.requestSubmit();
  }
});
elements.newMeeting.addEventListener("click", () => {
  if (desktopMedia.matches) {
    setDesktopView(state.desktopView === "upload" ? (state.jobs.length ? "jobs" : "chat") : "upload");
    return;
  }
  if (state.desktopView === "notes") setDesktopView("chat");
  const show = !document.body.classList.contains("show-upload");
  document.body.classList.toggle("show-upload", show);
  elements.newMeeting.textContent = show ? "收起上传" : "新建会议";
  if (show) elements.uploadWorkspace.scrollIntoView({ behavior: "smooth", block: "start" });
});
for (const link of document.querySelectorAll("[data-desktop-view]")) {
  link.addEventListener("click", (event) => {
    const view = link.dataset.desktopView;
    if (view === "notes") {
      event.preventDefault();
      openChatNotes();
    } else if (desktopMedia.matches) {
      event.preventDefault();
      setDesktopView(view);
    } else if (state.desktopView === "notes") {
      setDesktopView(view);
    }
  });
}
desktopMedia.addEventListener("change", () => {
  if (desktopMedia.matches) {
    setDesktopView(state.desktopView || (state.jobs.length ? "chat" : "upload"));
  } else if (state.desktopView !== "notes") {
    document.body.classList.remove("desktop-view-chat", "desktop-view-jobs", "desktop-view-upload", "show-upload");
    elements.newMeeting.textContent = "新建会议";
  }
  renderJobs();
});
["dragenter", "dragover"].forEach((name) => elements.dropzone.addEventListener(name, (event) => {
  event.preventDefault(); elements.dropzone.classList.add("dragging");
}));
["dragleave", "drop"].forEach((name) => elements.dropzone.addEventListener(name, (event) => {
  event.preventDefault(); elements.dropzone.classList.remove("dragging");
}));
elements.dropzone.addEventListener("drop", (event) => selectFile(event.dataTransfer.files[0]));

checkHealth();
renderChatScope();
loadChatSessions();
loadChatNotes();
loadJobs().then(() => {
  if (state.jobs.some((job) => (
    ["queued", "processing"].includes(job.status)
    || ["processing", "applying"].includes(job.review_status)
  ))) startPolling();
});

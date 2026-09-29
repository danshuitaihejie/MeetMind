const $ = (selector, root = document) => root.querySelector(selector);

const state = {
  file: null,
  duration: null,
  jobs: [],
  polling: null,
  expandedJobId: null,
  jobsInitialized: false,
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
  newMeeting: $("#newMeetingToggle"),
  uploadWorkspace: $("#uploadWorkspace"),
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
      try {
        const created = JSON.parse(request.responseText);
        state.expandedJobId = created.id;
        state.jobsInitialized = true;
      } catch { /* The next refresh will still show the newest task. */ }
      clearFile();
      elements.context.value = "";
      document.body.classList.remove("show-upload");
      elements.newMeeting.textContent = "新建会议";
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

function appendHighlightedContext(container, contextText, originalTerm) {
  const termIndex = contextText.indexOf(originalTerm);
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
  const prefix = document.createElement("span");
  prefix.textContent = "附近上下文：";
  original.appendChild(prefix);
  appendHighlightedContext(original, item.context_text, item.original_term);
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
  input.value = item.correction_term || item.suggested_term || item.original_term;
  label.append(labelText, input);
  article.appendChild(label);

  const keep = document.createElement("button");
  keep.className = "review-keep";
  keep.type = "button";
  keep.textContent = "保留原词";
  keep.addEventListener("click", () => { input.value = item.original_term; });
  article.appendChild(keep);
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
    appendHighlightedContext(context, contextText, correction.original_term);
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
      matches.forEach((match) => {
        const row = document.createElement("button");
        row.className = "manual-review-match";
        row.type = "button";
        const time = document.createElement("strong");
        time.textContent = `${formatDuration(match.start_seconds)} 选择此处`;
        const context = document.createElement("span");
        appendHighlightedContext(context, match.context_text, match.original_term);
        row.append(time, context);
        row.addEventListener("click", () => {
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
          original.value = "";
          replacement.value = "";
          results.replaceChildren();
        });
        results.appendChild(row);
      });
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
      $("strong", listHeading).textContent = `AI 标记的词 · ${job.review_items.length}`;
      listHeading.classList.remove("hidden");
      job.review_items.forEach((item) => list.appendChild(renderReviewItem(job, item)));
      apply.classList.remove("hidden");
    }
    setupManualReview(job, panel, apply);
    apply.textContent = status === "completed"
      ? "更新修正并重新生成纪要 →"
      : "应用以上修正并重新生成纪要 →";
    apply.addEventListener("click", async () => {
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
      apply.disabled = true;
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
        apply.textContent = "应用以上修正并重新生成纪要 →";
        error.textContent = requestError.message;
        error.classList.remove("hidden");
      }
    });
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
  const hasJobs = state.jobs.length > 0;
  document.body.classList.toggle("has-jobs", hasJobs);
  elements.newMeeting.classList.toggle("hidden", !hasJobs);
  elements.jobsList.replaceChildren();
  elements.emptyState.classList.toggle("hidden", hasJobs);
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
elements.newMeeting.addEventListener("click", () => {
  const show = !document.body.classList.contains("show-upload");
  document.body.classList.toggle("show-upload", show);
  elements.newMeeting.textContent = show ? "收起上传" : "新建会议";
  if (show) elements.uploadWorkspace.scrollIntoView({ behavior: "smooth", block: "start" });
});
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

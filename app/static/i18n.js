(() => {
  const LANGUAGE_KEY = "meetmind-language";
  const language = localStorage.getItem(LANGUAGE_KEY) === "zh" ? "zh" : "en";
  const exact = {
    "FFmpeg 未就绪": "FFmpeg is unavailable",
    "待配置语音与文本 API": "Configure speech and text APIs",
    "服务不可用": "Service unavailable",
    "选择文件后计算": "Calculated after file selection",
    "正在读取时长…": "Reading duration…",
    "（含静音预估）": " (including silence estimate)",
    "新建会议": "New meeting",
    "收起上传": "Close upload",
    "上传失败": "Upload failed",
    "上传失败，请稍后重试": "Upload failed. Please try again.",
    "网络连接失败，请确认服务正在运行": "Network error. Check that the service is running.",
    "语音转写": "Transcription",
    "校对复听转写": "Review transcription",
    "生成纪要": "Generate minutes",
    "重新生成纪要": "Regenerate minutes",
    "校对词语检测": "Review detection",
    "校对结果细化": "Review refinement",
    "会议问答": "Meeting Q&A",
    "对话标题生成": "Chat title generation",
    "词语标注释义": "Annotation explanation",
    "成功": "Success",
    "HTTP 错误": "HTTP error",
    "网络错误": "Network error",
    "API 错误": "API error",
    "响应无效": "Invalid response",
    "模拟调用（未调用真实 API）": "Mock call (no real API used)",
    "未报告": "Not reported",
    "尚未记录用量；历史任务无法补算。": "No usage recorded. Historical usage cannot be reconstructed.",
    "已报告 Token": "Reported tokens",
    "输入 Token": "Input tokens",
    "输出 Token": "Output tokens",
    "缓存输入 Token": "Cached input tokens",
    "ASR 时长": "ASR duration",
    "+ 未报告": "+ unreported",
    "· 最新": "· Latest",
    "语音 / 文本 API": "Speech / text APIs",
    "各阶段调用明细": "Calls by stage",
    "未知阶段": "Unknown stage",
    "状态未知": "Unknown status",
    "文本": "Text",
    "类型未知": "Unknown type",
    "模型未记录": "Model not recorded",
    "已保存纪要（历史首次版不可恢复）": "Saved minutes (original version unavailable)",
    "首次生成": "First version",
    "最新": "Latest",
    "请求失败": "Request failed",
    "排队中": "Queued",
    "处理中": "Processing",
    "已完成": "Completed",
    "失败": "Failed",
    "会议主题未提取": "Meeting title unavailable",
    "查看记录 ↗": "View record ↗",
    "暂无可询问的会议": "No completed meetings available",
    "查看处理记录 ↗": "View meeting record ↗",
    "选择处理记录 ↗": "Choose a meeting record ↗",
    "从查找范围中选择要打开的会议处理记录": "Choose a meeting record from the search scope",
    "查找中…": "Searching…",
    "发送 →": "Send →",
    "会议完成纪要和转写后，就可以在这里提问。": "Ask questions here after a meeting has minutes and a transcript.",
    "从所选会议的纪要和完整转写中查找依据，并列出参考会议。": "Find evidence in the selected meetings' minutes and transcripts.",
    "请先勾选至少一场会议。": "Select at least one meeting first.",
    "暂无提问": "No questions yet",
    "新对话": "New chat",
    "尚未提问": "No questions yet",
    "尚未保存": "Not saved yet",
    "自定义": "Custom",
    "AI 生成": "AI generated",
    "复制会话 ID": "Copy chat ID",
    "无法加载已保存对话": "Could not load saved chats",
    "点开后定位时间": "Locate when opened",
    "暂无匹配的转写片段，从原片开头播放。": "No matching transcript passage. Playing from the start.",
    "正在从原始音视频定位这段话，首次定位可能需要等待…": "Locating this passage in the original recording…",
    "暂时无法定位，可打开完整原始文件": "Could not locate this passage. Open the full recording instead.",
    "已定位到原片。可继续播放，查看前后语境。": "Located in the original recording. Play on to hear the context.",
    "暂无可靠的片段位置，现从原片开头播放。": "No reliable position found. Playing from the start.",
    "浏览器无法播放此视频格式，已切换到同时间轴的原速音轨。": "This video format is unsupported. Playing its original-speed audio instead.",
    "可查看完整原始文件": "Open the full original file",
    "← 返回标注笔记": "← Back to notes",
    "← 返回问会议": "← Back to chat",
    "无引用片段": "No cited passage",
    "查看完整原始文件": "Open full original file",
    "请先选择要查找的会议。": "Select meetings to search first.",
    "问问这场会议讨论了什么、决定了什么。": "Ask what this meeting discussed or decided.",
    "跨会议查找曾经讨论的结论、时间和负责人。": "Find decisions, dates, and owners across meetings.",
    "你": "You",
    "记录较长：回答依据为从完整转写中检索的相关片段及对应纪要。": "Long record: the answer uses retrieved transcript passages and related minutes.",
    "正在会议纪要和转写中查找…": "Searching minutes and transcripts…",
    "请输入问题": "Enter a question",
    "提问失败，请稍后重试": "Could not answer. Please try again.",
    "正在加载标注笔记…": "Loading notes…",
    "暂无标注。选中对话中的词或短语即可开始。": "No notes yet. Select a phrase in a chat answer to begin.",
    "等待解释": "Awaiting explanation",
    "音标暂不可用": "Pronunciation unavailable",
    "播放英文发音": "Play English pronunciation",
    "此浏览器不支持语音合成": "Speech synthesis is not supported in this browser",
    "暂无解释": "No explanation yet",
    "暂无解释，可以在下方提问。": "No explanation yet. Ask a question below.",
    "解释中…": "Explaining…",
    "提问 →": "Ask →",
    "无法加载标注笔记": "Could not load notes",
    "解释失败，请重新选中后重试": "Explanation failed. Select the phrase and try again.",
    "请输入追问内容": "Enter a follow-up question",
    "追问失败，请稍后重试": "Follow-up failed. Please try again.",
    "Agent 标记 · 待人工确认": "Agent flag · Needs confirmation",
    "两版转写冲突 · 待人工确认": "ASR conflict · Needs confirmation",
    "已确认": "Confirmed",
    "附近上下文：": "Nearby context: ",
    "输入确认后的词": "Enter the confirmed term",
    "保留原词": "Keep original term",
    "移除": "Remove",
    "请同时填写原词和正确写法": "Enter both the original and replacement terms",
    "正在查找…": "Searching…",
    "词级转写中没有找到这个原词，请检查文字是否完全一致": "Term not found in the word-timed transcript. Check the spelling.",
    "全选当前结果": "Select all results",
    "查找位置": "Find occurrences",
    "智能校对失败": "Review failed",
    "重新运行智能校对 ↻": "Run review again ↻",
    "正在启动校对…": "Starting review…",
    "智能校对：OCR + 原声": "Review with OCR + original audio",
    "原速音频复核完成，未发现明显需要人工确认的词。": "Original-speed review found no clear terms requiring confirmation.",
    "更新修正并重新生成纪要 →": "Update corrections and regenerate minutes →",
    "应用以上修正并重新生成纪要 →": "Apply corrections and regenerate minutes →",
    "请先确认一个疑似词，或主动搜索并添加一处纠偏。": "Confirm a suspect term or search for a term to correct.",
    "正在应用修正…": "Applying corrections…",
    "收起": "Collapse",
    "展开": "Expand",
    "复制会议 ID": "Copy meeting ID",
    "已复制会议 ID ✓": "Meeting ID copied ✓",
    "复制失败": "Copy failed",
    "会议完成后可询问": "Ask after processing completes",
    "原始": "Original",
    "压缩后": "Compressed",
    "缩短": "Reduced",
    "音频大小": "Audio size",
    "速度": "Speed",
    "正在重新处理…": "Retrying…",
    "重新处理失败": "Retry failed",
    "重新处理 ↻": "Retry ↻",
    "退出差异对比": "Close comparison",
    "对比最早保存版与最新版差异": "Compare earliest saved and latest",
    "对比首次版与最新版差异": "Compare first and latest",
    "两个版本内容相同": "Both versions are identical",
    "纪要尚未生成": "Minutes not generated yet",
    "转写尚未生成": "Transcript not generated yet",
    "已复制": "Copied",
    "复制内容": "Copy content",
    "压缩音频已生成。配置 API 密钥后可重新上传并生成转写与纪要。": "Compressed audio is ready. Configure API credentials and retry to generate a transcript and minutes.",
    "已复制会话 ID ✓": "Chat ID copied ✓",
    "对话名称": "Chat name",
    "重命名失败": "Rename failed",
    "删除这段已保存对话？此操作无法撤销。": "Delete this saved chat? This cannot be undone.",
    "删除失败": "Delete failed",
    "删除这条标注笔记？此操作无法撤销。": "Delete this note? This cannot be undone.",
    "删除标注失败": "Could not delete the note",
    "读取媒体信息": "Reading media information",
    "提取并压缩音频": "Extracting and compressing audio",
    "准备语音转写": "Preparing transcription",
    "应用已确认的词语纠正": "Applying confirmed terminology corrections",
    "整理会议纪要": "Writing meeting minutes",
    "处理完成": "Processing complete",
    "处理失败": "Processing failed",
    "等待处理": "Queued",
    "等待重新处理": "Queued for retry",
    "准备智能校对": "Preparing review",
    "准备应用修正": "Preparing corrections",
    "提取原速音频": "Extracting original-speed audio",
    "定位疑似错字": "Locating suspect terms",
    "融合 OCR 结果": "Combining OCR evidence",
    "等待人工确认": "Awaiting human confirmation",
    "未发现明显疑似错字": "No clear suspect terms found",
    "应用人工修正": "Applying manual corrections",
    "根据修正重新生成纪要": "Regenerating minutes from corrections",
    "校对已应用": "Corrections applied",
    "应用修正失败": "Applying corrections failed",
    "需重新运行词级校对": "Word-level review must be rerun",
    "服务器未安装 FFmpeg/FFprobe": "FFmpeg/FFprobe is not installed on the server",
    "不支持此文件格式": "Unsupported file format",
    "加速倍率必须是 1、1.25、1.5、1.75 或 2": "Speed must be 1, 1.25, 1.5, 1.75, or 2",
    "会议背景不能超过 4000 个字符": "Meeting context cannot exceed 4,000 characters",
    "请至少选择一场会议": "Select at least one meeting",
    "会议不存在": "Meeting not found",
    "所选范围内还没有已完成的会议纪要和转写": "No completed meeting notes and transcript in the selected scope",
    "所选会议中有尚未完成纪要和转写的会议": "Some selected meetings do not have completed notes and transcripts",
    "不能同时指定 job_id 和 job_ids": "Specify either job_id or job_ids",
    "对话不存在": "Chat not found",
    "请输入对话名称": "Enter a chat name",
    "请选择要标注的词语": "Select a phrase to annotate",
    "标注范围与对话不一致": "The selection does not match the chat",
    "标注内容与对话不一致": "The selected text does not match the chat",
    "标注不存在": "Note not found",
    "请输入追问": "Enter a follow-up question",
    "这条标注的追问已达到上限": "This note has reached its follow-up limit",
    "任务不存在": "Meeting record not found",
    "只有失败的任务可以重新处理": "Only failed jobs can be retried",
    "原始文件已不存在，请重新上传": "The original file is missing. Upload it again",
    "会议完成转写后才能进行智能校对": "Finish transcription before starting review",
    "智能校对正在处理中": "Review is already running",
    "原始文件已不存在，无法校对": "The original file is missing and cannot be reviewed",
    "请先运行智能校对以生成词级时间轴": "Run review to create a word-level timeline first",
    "请输入要查找的原词": "Enter the original term to find",
    "当前没有可应用的校对结果": "No review corrections are ready to apply",
    "校对项不存在或已过期": "Review item not found or expired",
    "未能在原媒体中准确定位这段话": "Could not locate this passage precisely in the original recording",
    "原始音视频文件不存在": "The original recording is missing",
    "文件尚未生成": "The file has not been generated",
    "原始文件不存在": "The original file is missing",
    "纪要版本不存在": "Notes version not found",
    "校对片段不存在": "Review clip not found",
    "原声片段尚未生成": "Original audio clip has not been generated",
    "校对画面不存在": "Review frame not found",
    "校对画面尚未生成": "Review frame has not been generated",
  };

  const patterns = [
    [/^(.+) 已就绪$/, ([, provider]) => `${translate(provider)} ready`],
    [/^约 (.+)（含静音预估）$/, ([, duration]) => `About ${duration} (silence estimated)`],
    [/^约 (.+)$/, ([, duration]) => `About ${duration}`],
    [/^正在上传 (\d+)%$/, ([, percent]) => `Uploading ${percent}%`],
    [/^第 (\d+) 版$/, ([, number]) => `Version ${number}`],
    [/^(.+) · 最新$/, ([, label]) => `${translate(label)} · Latest`],
    [/^(.+) 场$/, ([, count]) => `${count} ${count === "1" ? "meeting" : "meetings"}`],
    [/^已选 (\d+) \/ (\d+) 场会议$/, ([, selected, total]) => `${selected} of ${total} ${total === "1" ? "meeting" : "meetings"} selected`],
    [/^(\d+) 场会议(.*)$/, ([, count, rest]) => `${count} ${count === "1" ? "meeting" : "meetings"}${rest}`],
    [/^查看「(.+)」的处理记录$/, ([, title]) => `View meeting record for ${title}`],
    [/^打开「(.+)」的标注笔记$/, ([, phrase]) => `Open note for ${phrase}`],
    [/^查看「(.+)」的处理记录$/, ([, title]) => `View record for ${title}`],
    [/^查看「(.+)」的标注笔记$/, ([, title]) => `Open note for ${title}`],
    [/^复制会话 ID：(.+)$/, ([, id]) => `Copy chat ID: ${id}`],
    [/^会话 ID：(.+)$/, ([, id]) => `Chat ID: ${id}`],
    [/^会议 ID：(.+)$/, ([, id]) => `Meeting ID: ${id}`],
    [/^复制会议 ID：(.+)$/, ([, id]) => `Copy meeting ID: ${id}`],
    [/^已保存 (\d+) 条标注$/, ([, count]) => `${count} saved ${count === "1" ? "note" : "notes"}`],
    [/^正在解释「(.+)」…$/, ([, phrase]) => `Explaining “${phrase}”…`],
    [/^原文：(.*)$/, ([, excerpt]) => `Excerpt: ${excerpt}`],
    [/^文件不能超过 (\d+) MB$/, ([, limit]) => `File cannot exceed ${limit} MB`],
    [/^(.+) 的原始视频画面$/, ([, time]) => `Original video frame at ${time}`],
    [/^待确认 · AI 估值 (\d+)%$/, ([, score]) => `Needs review · AI estimate ${score}%`],
    [/^画面 OCR：(.*)$/, ([, text]) => `On-screen OCR: ${text}`],
    [/^只确认这个词（原识别：(.+)）$/, ([, term]) => `Confirm only this term (ASR: ${term})`],
    [/^AI 建议：(.*)$/, ([, term]) => `AI suggestion: ${term}`],
    [/^填入 AI 建议：(.*)$/, ([, term]) => `Use AI suggestion: ${term}`],
    [/^把 (.+) 修改为$/, ([, term]) => `Replace ${term} with`],
    [/^第 (\d+) 处 · (.*)$/, ([, index, time]) => `Occurrence ${index} · ${time}`],
    [/^已选 (\d+) \/ (\d+)$/, ([, selected, total]) => `${selected} of ${total} selected`],
    [/^加入选中位置（(\d+)）$/, ([, count]) => `Add selected occurrences (${count})`],
    [/^疑似词 · 待确认 (\d+) \/ (\d+)$/, ([, pending, total]) => `Suspect terms · ${pending} of ${total} pending`],
    [/^一键填入 (\d+) 条 AI 建议$/, ([, count]) => `Fill ${count} AI suggestions`],
    [/^已填入 (\d+) 条 AI 建议$/, ([, count]) => `Filled ${count} AI suggestions`],
    [/^(\d+) 行有变化 · 红色为原版，绿色为新版；深色标出改动文字$/, ([, count]) => `${count} changed lines · red: original, green: new; darker text marks edits`],
    [/^查看原片与上下文 · (\d+) 段 →$/, ([, count]) => `View original and context · ${count} passages →`],
    [/^原始音视频：(.*)$/, ([, filename]) => `Original recording: ${filename}`],
    [/^询问：(.*)$/, ([, title]) => `Ask about: ${title}`],
    [/^第 (\d+) 次请求（重试）$/, ([, attempt]) => `Attempt ${attempt} (retry)`],
    [/^请求 ID：(.*)$/, ([, id]) => `Request ID: ${id}`],
    [/^ASR 时长：(.*) · 按音频时长统计$/, ([, duration]) => `ASR duration: ${translate(duration)} · measured by audio length`],
    [/^输入：(.*) · 输出：(.*) · 总计：(.*) · 缓存输入：(.*)$/, ([, input, output, total, cached]) => `Input: ${translate(input)} · Output: ${translate(output)} · Total: ${translate(total)} · Cached input: ${translate(cached)}`],
    [/^语音转写 (\d+\/\d+)$/, ([, progress]) => `Transcribing ${progress}`],
    [/^原速音频对齐 (\d+\/\d+)$/, ([, progress]) => `Aligning original-speed audio ${progress}`],
    [/^生成核对片段 (\d+\/\d+)$/, ([, progress]) => `Creating review clips ${progress}`],
    [/^请先确认 (\d+) 处两版转写冲突$/, ([, count]) => `Confirm ${count} ASR conflicts first`],
    [/^已应用修正，仍有 (\d+) 项待确认$/, ([, count]) => `Corrections applied; ${count} items still pending`],
  ];

  function translate(value) {
    if (language === "zh" || typeof value !== "string" || !/[\u3400-\u9fff]/u.test(value)) return value;
    const leading = value.match(/^\s*/u)?.[0] || "";
    const trailing = value.match(/\s*$/u)?.[0] || "";
    const core = value.trim();
    if (Object.hasOwn(exact, core)) return `${leading}${exact[core]}${trailing}`;
    for (const [pattern, render] of patterns) {
      const match = core.match(pattern);
      if (match) return `${leading}${render(match)}${trailing}`;
    }
    return value;
  }

  const contentSelectors = [
    ".result-content", ".compare-diff", ".chat-message-body", ".chat-note-excerpt",
    ".source-player-workspace #sourcePlayerContext", ".review-reason", ".review-ocr",
    ".review-original", ".manual-review-match", ".manual-pending-item p",
    ".chat-evidence > span", ".source-player-sidebar small", ".job-title strong",
    ".chat-session-item strong", ".chat-session-question", ".chat-note-exchange p",
  ].join(",");

  function isContent(node) {
    return node.parentElement?.closest(contentSelectors);
  }

  function localizeNode(node) {
    if (language !== "en") return;
    if (node.nodeType === Node.TEXT_NODE) {
      if (isContent(node)) return;
      const result = translate(node.nodeValue);
      if (result !== node.nodeValue) node.nodeValue = result;
      return;
    }
    if (node.nodeType !== Node.ELEMENT_NODE) return;
    if (node.matches(contentSelectors)) return;
    for (const name of ["aria-label", "title", "placeholder", "alt"]) {
      if (!node.hasAttribute(name)) continue;
      const current = node.getAttribute(name);
      const result = translate(current);
      if (result !== current) node.setAttribute(name, result);
    }
    for (const child of node.childNodes) localizeNode(child);
  }

  function applyStaticChinese() {
    if (language !== "zh") return;
    document.documentElement.lang = "zh-CN";
    const roots = [document, ...[...document.querySelectorAll("template")].map(
      (template) => template.content,
    )];
    for (const element of roots.flatMap((root) => [...root.querySelectorAll("[data-zh]")])) {
      element.textContent = element.dataset.zh;
    }
    for (const attribute of ["aria-label", "placeholder", "title", "content"]) {
      const key = `zh${attribute.replace(/-([a-z])/g, (_, letter) => letter.toUpperCase()).replace(/^./, (letter) => letter.toUpperCase())}`;
      for (const element of roots.flatMap((root) => [
        ...root.querySelectorAll(`[data-zh-${attribute}]`),
      ])) {
        element.setAttribute(attribute, element.dataset[key]);
      }
    }
  }

  function start() {
    applyStaticChinese();
    const toggle = document.getElementById("languageToggle");
    toggle.textContent = language === "en" ? "中文" : "English";
    toggle.setAttribute("aria-label", language === "en" ? "Switch to Chinese" : "切换为英文");
    toggle.setAttribute("aria-pressed", String(language === "zh"));
    toggle.addEventListener("click", () => {
      localStorage.setItem(LANGUAGE_KEY, language === "en" ? "zh" : "en");
      window.location.reload();
    });
    if (language === "en") {
      localizeNode(document.body);
      const observer = new MutationObserver((mutations) => {
        for (const mutation of mutations) {
          if (mutation.type === "characterData") localizeNode(mutation.target);
          else if (mutation.type === "attributes") localizeNode(mutation.target);
          else for (const node of mutation.addedNodes) localizeNode(node);
        }
      });
      observer.observe(document.body, {
        subtree: true, childList: true, characterData: true, attributes: true,
        attributeFilter: ["aria-label", "title", "placeholder", "alt"],
      });
    }
  }

  window.MeetMindI18n = { language, translate, start };
})();

# MeetMind

把会议视频或音频变成更短的语音、完整转写和结构化会议纪要。

## 能做什么

- 支持 MP4、MOV、MKV、WebM、MP3、WAV、M4A、AAC、FLAC、OGG 等常见格式。
- 默认流程只提取视频的第一个音轨，不上传画面。
- 通过 FFmpeg 删除长静音，并以 1×–2× 保音高加速。
- 输出 16kHz、单声道、32kbps MP3，显著减少传输体积。
- 使用 MiniMax `asr-1.0` 转写，使用 MiniMax 文本模型生成中文 Markdown 会议纪要。
- 压缩音频超过 300 秒时自动分段转写，为 MiniMax ASR 的 500 秒限制留出余量。
- 任务状态和结果保存到本地 `data/jobs/`，重启服务后仍可查看。
- MiniMax 遇到临时 429/5xx 会自动退避重试三次；失败任务可在页面直接重新处理。
- 每场会议的“AI 用量”会保存文本模型返回的输入、输出、总 token 和缓存输入，
  并列出转写、纪要、校对、重新生成和重试的逐次调用；记录不会随重试清零。
- 对结果不满意时可按需启动智能校对：以原速音频取得词级时间戳，用本地 RapidOCR
  读取对应视频画面，只高亮低置信度词或短语，让用户结合原声片段确认，不必重审整句。
- AI 没标出的高置信度错词也可手动搜索；出现多次时先用短上下文选择准确位置，
  再只替换该处词语，避免误改其他同名词。
- 用户确认修正后，会保留原转写备份，并自动重新生成会议纪要。
- 校对面板可一键填入所有待确认的 AI 建议，供人工检查或修改；只有点击应用修正按钮后才会保存并重新生成纪要。Agent 标记的待确认项不会自动填入。
- 每次成功生成的会议纪要都会作为版本保存在任务记录中。网页可切换任意版本，或用逐行差异视图对比首次版与最新版，并可分别下载；`minutes.md` 始终是最新版。升级前已有的任务只能保留当时的现存纪要，无法恢复此前被覆盖的版本。
- 确认的词语修正会持久保存到 `data/corrections.sqlite3`（目录受 `MEETMIND_DATA_DIR` 配置），记录原词、修正词、上下文、来源任务和时间。
- 后续转写和智能校对会在生成纪要前自动应用无冲突的精确词语映射。同一原词若对应多个不同修正，则不自动替换，留待人工确认；单字规则不自动应用，英文词按完整词边界匹配。

> 1.5× 会把 30 分钟压到约 20 分钟；启用静音删除后通常还能更短。2× 可压到约 15 分钟，但语速越快，极端口音、多人抢话场景的转写准确率越可能下降。

## 本地运行

依赖 Python 3.11+、[uv](https://docs.astral.sh/uv/) 和 FFmpeg。

```bash
cp .env.example .env
# 在 .env 中填写 MINIMAX_API_KEY

uv sync
set -a && source .env && set +a
uv run uvicorn app.main:app --reload
```

打开 <http://127.0.0.1:8000>。

### 问会议

页面的「问会议」可勾选一场、几场或全部已完成的会议，连续询问结论、负责人、日期等问题。查找范围和会议卡片会同时显示原文件名与从纪要提取的会议主题；每条会议卡片旁的对话图标可直达该会议的问答，未处理完成时图标不可用。回答会列出参考会议，点击可跳转到原记录。问答使用所选会议的最新纪要和完整转写作为资料；资料能放入一次模型请求时会完整提供，历史记录较长时会先在所选会议的转写中检索相关片段，再连同对应纪要提供给模型，并在回答下方提示。没有证据的问题应明确回答未找到。对话连同查询范围、问题、回答和来源保存在 `data/chat_sessions.json`。左侧列表显示随问答更新的标题和首次提问；AI 生成的标题带「AI 生成」标识，手动重命名后显示「自定义」且标题不再自动更新。可切换或删除会话，开始新对话会保留旧对话。标题生成会额外调用一次文本模型，其用量单独记录为 `chat_title`。单场问答用量记在该会议下；跨会议问答用量单独保存在 `data/chat_usage.jsonl`。

在对话中选中不理解的词或短语，可点击「解释并标记」。侧边窗口会区分通用词义和会议中的具体含义，并可继续追问。单个英文单词的释义还包含音标、词性、例句及用法，发音按钮使用浏览器英语语音朗读。标注词语会在原对话中高亮；笔记连同原文摘录、所选会议及追问记录保存在 `data/chat_notes.json`，刷新页面后仍可打开，也可删除。

## 命令行调用（MCP / Skill）

`meetmind` 现在也能直接处理本地文件，无需先启动网页服务。推荐通过 `uv run` 调用：

```bash
uv run meetmind process /absolute/path/meeting.mp4 --speed 1.5 --context "项目周会"
uv run meetmind show <任务ID>
uv run meetmind list
```

`process` 会同步运行至成功或失败；数据子命令返回任务时，标准输出是一行 JSON，包含任务状态、转写、纪要、AI 用量，以及 `artifacts` 中已生成文件的绝对路径。调用错误只写入标准错误，格式也是 JSON。退出码 `0` 表示命令成功，`1` 表示处理或校对任务失败，`2` 表示参数、输入文件或任务 ID 等调用错误。MCP 工具或 Skill 可直接解析标准输出和退出码。输出较大时可从 `artifacts` 路径读取所需文件。

```bash
# 关闭静音删除；背景文字也可放在 UTF-8 文件中
uv run meetmind process /absolute/path/meeting.wav --no-trim-silence --context-file context.txt

# 使用独立的数据目录；--data-dir 必须放在子命令之前
uv run meetmind --data-dir /absolute/path/meetmind-data process /absolute/path/meeting.mp4

# 可选的校对流程
uv run meetmind review <任务ID>
uv run meetmind pending <任务ID>
uv run meetmind search <任务ID> "待核对词"
uv run meetmind flag <任务ID> "待核对词" --segment-index 0 --term-start 12 --reason "原声仍无法确认"
uv run meetmind apply <任务ID> --input corrections.json
```

`review` / `show` 的 JSON 包含每个疑似词的上下文、AI 建议、置信度、OCR 文字，以及 `evidence.audio` / `evidence.frames` 的本地路径。`pending` 只返回尚未确认的词和证据，避免重复读取完整转写与纪要。`search` 会返回词语出现的位置、时间范围和原速音频路径，便于 agent 主动检查 AI 没标出的错词。`pending_review_count` 表示仍待确认的疑似词数量。

Agent 应只提交已核实的纠偏；拿不准的 `item_id` 不写入 `corrections`，会继续保持待确认状态，并在网页校对面板提示用户处理。对主动搜索发现但无法确定的词，使用 `flag` 把 `search` 返回的 `segment_index` 和 `term_start` 所指位置加入人工待确认列表；`--suggested` 可附候选写法，但不会自动应用。确认原词正确时，把 `replacement` 设为 `original_term`；这会标记为已确认，但不会记入词语纠正库。后续 CLI `apply` 可以只提交新确认的项，先前修正会自动保留。用户也可以在网页端主动搜索并修正 AI 没标出的词。

`apply` 的输入格式与网页 API 的校对提交格式一致，例如：

```json
{
  "corrections": [{"item_id": "校对项ID", "replacement": "确认后的词"}],
  "manual_corrections": []
}
```

`--context-file -` 和 `--input -` 可以从标准输入读取背景文字或 JSON。`retry <任务ID>` 可重新处理失败任务；`uv run meetmind serve` 启动网页服务，`--host`、`--port`、`--reload` 可配置服务。运行前仍需配置 `MINIMAX_API_KEY`，以及安装 FFmpeg/FFprobe。

macOS 安装 FFmpeg：

```bash
brew install ffmpeg
```

## 配置

| 环境变量 | 默认值 | 说明 |
| --- | --- | --- |
| `MINIMAX_API_KEY` | 空 | 转写和纪要所需的 MiniMax API 密钥 |
| `MEETMIND_MINIMAX_BASE_URL` | `https://api.minimaxi.com` | MiniMax 国内接口地址；国际账号可设为 `https://api.minimax.io` |
| `MEETMIND_TRANSCRIPTION_MODEL` | `asr-1.0` | MiniMax 语音识别模型 |
| `MEETMIND_SUMMARY_MODEL` | `MiniMax-M2.7` | MiniMax 会议纪要模型 |
| `MEETMIND_DATA_DIR` | `./data` | 上传文件和结果目录 |
| `MEETMIND_MAX_UPLOAD_MB` | `2048` | 单个源文件上限 |

MiniMax ASR 单个音频文件限制为 50MB、500 秒。MeetMind 会先把音轨压缩成 32kbps MP3，再自动切成不超过 300 秒的片段依次转写，因此可直接处理 30 分钟或更长会议。

MiniMax ASR 会提供词级时间戳和说话人，但不提供原生置信度。页面中的校对置信度是文本模型根据原速转写、上下文和 OCR 证据给出的估值，并会明确提示人工确认。

文本 token 按 MiniMax API 返回的 `usage` 统计，缓存输入已经包含在输入 token 中，
不会重复相加。ASR 不返回文本 token，单独累计成功响应报告的音频秒数。
没有返回的用量以及失败请求的未知消耗会明确标注；历史任务无法补算，模拟调用不算真实消耗。
这些用量保存在任务的 `job.json`，服务重启后仍可查看。Token 总量与 Token Plan/M Plan
的套餐额度扣减、积分扣减和实际账单金额不同；是否使用订阅额度取决于配置的 Key 和套餐覆盖范围。

## 测试与检查

```bash
uv run pytest
uv run ruff check .
```

测试使用本地模拟 AI，不会消耗 API 额度。生产运行时默认不会启用模拟模式。

## 处理流程

```text
音频 / 视频
    ↓ FFmpeg 提取第一个音轨
删除长静音 → 保音高加速 → 16kHz 单声道 MP3
    ↓
MiniMax ASR（长音频自动分段）
    ↓
MiniMax 文本模型整理：摘要 / 关键结论 / 讨论要点 / 行动项 / 待确认事项
    ↓ 可选：用户点击“智能校对”
原速词级时间轴 + 本地视频 OCR → 仅确认疑似词/短语 → 重新生成纪要
```

## 数据说明

- 原始文件、压缩音频、转写和纪要都会保存在运行机器的 `data/jobs/<任务ID>/`。
- 默认流程只有压缩后的音频会发送给转写 API；会议文本会发送给纪要模型。
- 智能校对按需启动，届时原速音频会发送给 MiniMax 以获得准确时间戳；视频帧仅在本地由 RapidOCR 识别，不会上传。
- 当前是适合单机试用的版本。正式多用户部署前，应补充登录、访问控制、自动清理、对象存储和任务队列。

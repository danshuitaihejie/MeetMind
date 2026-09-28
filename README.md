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
- 对结果不满意时可按需启动智能校对：以原速音频重新对齐句段，用本地 RapidOCR
  读取对应视频画面，再把低置信度项连同原声片段交给用户确认。
- 用户确认修正后，会保留原转写备份，并自动重新生成会议纪要。

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

MiniMax ASR 会提供句段时间戳和说话人，但不提供原生置信度。页面中的校对置信度是文本模型根据原速转写、上下文和 OCR 证据给出的估值，并会明确提示人工确认。

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
原速音频时间轴 + 本地视频 OCR → 原声片段人工确认 → 重新生成纪要
```

## 数据说明

- 原始文件、压缩音频、转写和纪要都会保存在运行机器的 `data/jobs/<任务ID>/`。
- 默认流程只有压缩后的音频会发送给转写 API；会议文本会发送给纪要模型。
- 智能校对按需启动，届时原速音频会发送给 MiniMax 以获得准确时间戳；视频帧仅在本地由 RapidOCR 识别，不会上传。
- 当前是适合单机试用的版本。正式多用户部署前，应补充登录、访问控制、自动清理、对象存储和任务队列。

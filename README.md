# MeetMind

把会议视频或音频变成更短的语音、完整转写和结构化会议纪要。

## 能做什么

- 支持 MP4、MOV、MKV、WebM、MP3、WAV、M4A、AAC、FLAC、OGG 等常见格式。
- 视频只提取第一个音轨，不处理或上传画面。
- 通过 FFmpeg 删除长静音，并以 1×–2× 保音高加速。
- 输出 16kHz、单声道、32kbps MP3，显著减少传输体积。
- 使用 MiniMax `asr-1.0` 转写，使用 MiniMax 文本模型生成中文 Markdown 会议纪要。
- 压缩音频超过 480 秒时自动分段转写，适配 MiniMax ASR 的 500 秒限制。
- 任务状态和结果保存到本地 `data/jobs/`，重启服务后仍可查看。

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

MiniMax ASR 单个音频文件限制为 50MB、500 秒。MeetMind 会先把音轨压缩成 32kbps MP3，再自动切成不超过 480 秒的片段依次转写，因此可直接处理 30 分钟或更长会议。

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
```

## 数据说明

- 原始文件、压缩音频、转写和纪要都会保存在运行机器的 `data/jobs/<任务ID>/`。
- 只有压缩后的音频会发送给转写 API；会议文本会发送给纪要模型。
- 当前是适合单机试用的版本。正式多用户部署前，应补充登录、访问控制、自动清理、对象存储和任务队列。

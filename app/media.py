from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path


class MediaProcessingError(RuntimeError):
    pass


def build_audio_filter(speed: float, trim_silence: bool) -> str:
    if speed < 1.0 or speed > 2.0:
        raise ValueError("speed must be between 1.0 and 2.0")

    filters = ["highpass=f=80", "lowpass=f=7600"]
    if trim_silence:
        filters.append(
            "silenceremove="
            "start_periods=1:start_duration=0.20:start_threshold=-42dB:"
            "start_silence=0.12:stop_periods=-1:stop_duration=0.55:"
            "stop_threshold=-42dB:stop_silence=0.18"
        )
    if speed != 1.0:
        filters.append(f"atempo={speed:g}")
    return ",".join(filters)


class MediaProcessor:
    @staticmethod
    def available() -> bool:
        return bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))

    @staticmethod
    def probe_duration(path: Path) -> float:
        command = [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "json",
            str(path),
        ]
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            raise MediaProcessingError(result.stderr.strip() or "无法读取媒体时长")
        try:
            return float(json.loads(result.stdout)["format"]["duration"])
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise MediaProcessingError("媒体文件缺少可读取的音轨") from exc

    @staticmethod
    def compress(input_path: Path, output_path: Path, speed: float, trim_silence: bool) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        command = [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-i",
            str(input_path),
            "-map",
            "0:a:0",
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-af",
            build_audio_filter(speed, trim_silence),
            "-codec:a",
            "libmp3lame",
            "-b:a",
            "32k",
            str(output_path),
        ]
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            message = (
                result.stderr.strip().splitlines()[-1] if result.stderr.strip() else "未知错误"
            )
            raise MediaProcessingError(f"音频提取或压缩失败：{message}")

    @staticmethod
    def split_for_transcription(
        input_path: Path,
        output_dir: Path,
        duration_seconds: float,
        segment_seconds: float = 480,
    ) -> list[Path]:
        """Split MP3 below MiniMax's 500-second ASR limit, with safety headroom."""
        if duration_seconds <= segment_seconds:
            return [input_path]
        if segment_seconds <= 0 or segment_seconds >= 500:
            raise ValueError("segment_seconds must be between 0 and 500")

        output_dir.mkdir(parents=True, exist_ok=True)
        output_pattern = output_dir / "chunk_%03d.mp3"
        command = [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-i",
            str(input_path),
            "-map",
            "0:a:0",
            "-f",
            "segment",
            "-segment_time",
            f"{segment_seconds:g}",
            "-reset_timestamps",
            "1",
            "-codec:a",
            "copy",
            str(output_pattern),
        ]
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        chunks = sorted(output_dir.glob("chunk_*.mp3"))
        if result.returncode != 0 or not chunks:
            message = (
                result.stderr.strip().splitlines()[-1] if result.stderr.strip() else "未知错误"
            )
            raise MediaProcessingError(f"长音频自动分段失败：{message}")
        return chunks

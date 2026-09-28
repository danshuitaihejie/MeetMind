import shutil
import wave
from pathlib import Path

import pytest

from app.media import MediaProcessor, build_audio_filter


def test_build_audio_filter_balanced_mode() -> None:
    result = build_audio_filter(1.5, True)
    assert "silenceremove=" in result
    assert result.endswith("atempo=1.5")


def test_build_audio_filter_original_speed_without_silence_trim() -> None:
    result = build_audio_filter(1.0, False)
    assert "silenceremove=" not in result
    assert "atempo=" not in result


@pytest.mark.parametrize("speed", [0.9, 2.1])
def test_build_audio_filter_rejects_unsafe_speed(speed: float) -> None:
    with pytest.raises(ValueError):
        build_audio_filter(speed, True)


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="FFmpeg is not installed")
def test_split_for_transcription_keeps_chunks_below_limit(tmp_path: Path) -> None:
    source = tmp_path / "source.wav"
    with wave.open(str(source), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(16000)
        audio.writeframes(b"\x01\x00" * 16000 * 3)

    compressed = tmp_path / "compressed.mp3"
    MediaProcessor.compress(source, compressed, speed=1.0, trim_silence=False)
    duration = MediaProcessor.probe_duration(compressed)
    chunks = MediaProcessor.split_for_transcription(
        compressed,
        tmp_path / "chunks",
        duration,
        segment_seconds=1.0,
    )
    assert len(chunks) >= 2
    assert all(MediaProcessor.probe_duration(chunk) < 1.2 for chunk in chunks)

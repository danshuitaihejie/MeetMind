from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any


class OCRProcessingError(RuntimeError):
    pass


class OCRService:
    """Lazy local OCR wrapper so normal transcription does not load ONNX models."""

    def __init__(self, engine_factory: Callable[[], Any] | None = None) -> None:
        self.engine_factory = engine_factory
        self._engine: Any | None = None

    def _get_engine(self) -> Any:
        if self._engine is None:
            if self.engine_factory:
                self._engine = self.engine_factory()
            else:
                try:
                    from rapidocr import RapidOCR
                except ImportError as exc:
                    raise OCRProcessingError(
                        "本地 OCR 未安装，请运行 uv sync 后重试"
                    ) from exc
                self._engine = RapidOCR()
        return self._engine

    def recognize(self, image_path: Path, minimum_score: float = 0.45) -> list[str]:
        if not image_path.is_file():
            return []
        try:
            result = self._get_engine()(str(image_path))
        except Exception as exc:
            raise OCRProcessingError(f"本地 OCR 识别失败：{exc}") from exc
        if result is None:
            return []

        texts = getattr(result, "txts", None)
        scores = getattr(result, "scores", None)
        if texts is not None:
            score_values = list(scores) if scores is not None else [1.0] * len(texts)
            return [
                str(text).strip()
                for text, score in zip(texts, score_values, strict=False)
                if str(text).strip() and float(score) >= minimum_score
            ]

        # Compatibility with RapidOCR 1.x/2.x tuple output.
        legacy = result[0] if isinstance(result, tuple) else result
        if not isinstance(legacy, list):
            return []
        recognized: list[str] = []
        for item in legacy:
            if not isinstance(item, list | tuple) or len(item) < 2:
                continue
            text = str(item[1]).strip()
            score = float(item[2]) if len(item) > 2 else 1.0
            if text and score >= minimum_score:
                recognized.append(text)
        return recognized

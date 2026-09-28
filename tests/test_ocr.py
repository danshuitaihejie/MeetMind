from pathlib import Path
from types import SimpleNamespace

from app.ocr import OCRService


def test_ocr_filters_low_confidence_and_empty_text(tmp_path: Path) -> None:
    image = tmp_path / "frame.jpg"
    image.write_bytes(b"fake-image")
    output = SimpleNamespace(
        txts=("MeetMind", "模糊文字", ""),
        scores=(0.98, 0.2, 0.99),
    )
    service = OCRService(engine_factory=lambda: lambda _: output)

    assert service.recognize(image) == ["MeetMind"]

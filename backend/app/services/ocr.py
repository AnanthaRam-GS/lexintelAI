"""Tesseract OCR for scanned PDF pages (RAG-005).

``ocr_page`` renders one PyMuPDF page at the configured DPI, runs Tesseract
once (``image_to_data``) and rebuilds the text with Tesseract's own block,
paragraph and line structure, so a blank line separates paragraphs exactly as
the native-text path expects. It also returns the mean word confidence.

``tesseract_status`` reports whether the binary and the configured language
are usable; ``/health`` shows it. Errors here are low-level; the document
parser turns them into OCR_UNAVAILABLE / OCR_LIMIT_EXCEEDED.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import io
import statistics
import time
from typing import Any

from backend.app.core.config import Settings

DEFAULT_TESSERACT_CMD = "tesseract"  # found on PATH


class OcrEngineUnavailable(RuntimeError):
    """Tesseract (or pytesseract, or the configured language) cannot be used."""


class OcrPageTimeout(RuntimeError):
    """Tesseract did not finish a page within its time limit."""


@dataclass(frozen=True)
class OcrPageResult:
    text: str
    mean_confidence: float | None
    word_count: int
    seconds: float


def _pytesseract(settings: Settings) -> Any:
    try:
        import pytesseract
    except ImportError as exc:
        raise OcrEngineUnavailable("pytesseract is not installed") from exc
    # pytesseract keeps the binary path in a module global: always set it, so one override never leaks.
    pytesseract.pytesseract.tesseract_cmd = settings.tesseract_cmd.strip() or DEFAULT_TESSERACT_CMD
    return pytesseract


@lru_cache(maxsize=8)
def _probe(tesseract_cmd: str, language: str) -> dict[str, Any]:
    settings = Settings(tesseract_cmd=tesseract_cmd, ocr_language=language)
    try:
        pytesseract = _pytesseract(settings)
        version = str(pytesseract.get_tesseract_version())
        languages = sorted(pytesseract.get_languages(config=""))
    except OcrEngineUnavailable as exc:
        return {"available": False, "reason": str(exc)}
    except Exception as exc:  # binary missing or unrunnable
        return {"available": False, "reason": f"tesseract binary not usable ({type(exc).__name__})"}
    missing = [code for code in language.split("+") if code and code not in languages]
    if missing:
        return {"available": False, "version": version, "languages": languages, "reason": f"language data missing: {'+'.join(missing)}"}
    return {"available": True, "version": version, "languages": languages, "language": language}


def tesseract_status(settings: Settings | None = None) -> dict[str, Any]:
    """{available, version, languages, language | reason}; cached per binary and language."""
    settings = settings or Settings()
    if not settings.ocr_enabled:
        return {"available": False, "enabled": False, "reason": "OCR is disabled (OCR_ENABLED=false)"}
    return {"enabled": True, **_probe(settings.tesseract_cmd.strip(), settings.ocr_language.strip() or "eng")}


def clear_tesseract_status_cache() -> None:
    _probe.cache_clear()


def _rebuild_text(data: dict[str, list[Any]]) -> tuple[str, list[float]]:
    paragraphs: dict[tuple[int, int], dict[int, list[str]]] = {}
    confidences: list[float] = []
    for index, word in enumerate(data["text"]):
        word = (word or "").strip()
        if not word:
            continue
        key = (int(data["block_num"][index]), int(data["par_num"][index]))
        paragraphs.setdefault(key, {}).setdefault(int(data["line_num"][index]), []).append(word)
        confidence = float(data["conf"][index])
        if confidence >= 0:
            confidences.append(confidence)
    text = "\n\n".join(
        "\n".join(" ".join(words) for _line, words in sorted(lines.items())) for _key, lines in sorted(paragraphs.items())
    )
    return text, confidences


def ocr_page(page: Any, settings: Settings, *, timeout_seconds: float) -> OcrPageResult:
    """OCR one PyMuPDF page. Raises OcrEngineUnavailable or OcrPageTimeout."""
    pytesseract = _pytesseract(settings)
    from PIL import Image

    started = time.perf_counter()
    pixmap = page.get_pixmap(dpi=settings.ocr_dpi, colorspace="gray", alpha=False)
    image = Image.open(io.BytesIO(pixmap.tobytes("png")))
    try:
        data = pytesseract.image_to_data(
            image,
            lang=settings.ocr_language.strip() or "eng",
            output_type=pytesseract.Output.DICT,
            timeout=max(1.0, timeout_seconds),
        )
    except RuntimeError as exc:
        if "timeout" in str(exc).lower():
            raise OcrPageTimeout("Tesseract page timeout") from exc
        raise OcrEngineUnavailable(f"tesseract failed ({type(exc).__name__})") from exc
    except pytesseract.TesseractNotFoundError as exc:
        raise OcrEngineUnavailable("tesseract binary not found") from exc
    except pytesseract.TesseractError as exc:
        raise OcrEngineUnavailable("tesseract could not process the page") from exc
    text, confidences = _rebuild_text(data)
    mean = round(statistics.fmean(confidences), 1) if confidences else None
    return OcrPageResult(text=text, mean_confidence=mean, word_count=len(confidences), seconds=round(time.perf_counter() - started, 3))

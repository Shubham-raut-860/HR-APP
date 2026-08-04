from __future__ import annotations

from app.services import file_service


class _FakePage:
    def __init__(self, text: str) -> None:
        self._text = text

    def extract_text(self, **_: object) -> str:
        return self._text


class _FakePdf:
    def __init__(self, texts: list[str]) -> None:
        self.pages = [_FakePage(text) for text in texts]

    def __enter__(self) -> "_FakePdf":
        return self

    def __exit__(self, *_: object) -> None:
        return None


def test_mixed_pdf_ocrs_single_weak_page_even_when_most_pages_are_digital(monkeypatch):
    good_page = (
        "Name Candidate Email [email-redacted] Summary experienced backend engineer "
        "with Python FastAPI PostgreSQL Redis Docker Kubernetes Education Bachelor Skills "
        "Python FastAPI PostgreSQL Redis Docker Kubernetes Projects APIs services automation "
        "Experience five years building production systems."
    )
    page_texts = [good_page for _ in range(10)]
    page_texts[1] = ""

    monkeypatch.setattr(
        file_service.pdfplumber,
        "open",
        lambda *_args, **_kwargs: _FakePdf(page_texts),
    )
    monkeypatch.setattr(
        file_service,
        "_ocr_pdf_pages",
        lambda _content, page_indices=None: ({1: "Certificate AWS Certified Solutions Architect"}, False),
    )
    monkeypatch.setattr(file_service.settings, "OCR_MIXED_PDF_WEAK_PAGES_ENABLED", True)

    text = file_service.extract_text_from_pdf(b"%PDF fake")

    assert "Certificate AWS Certified Solutions Architect" in text
    assert "experienced backend engineer" in text

"""FileExtractionAgent — validates, reads, and extracts plain text from any resume file."""
from __future__ import annotations
from typing import Any
from app.agents.base import BaseAgent
from app.services import file_service


class FileExtractionAgent(BaseAgent):
    name = "file_extraction_agent"

    async def run(self, state: dict[str, Any]) -> dict[str, Any]:
        filename: str = state.get("filename") or "resume.pdf"
        content: bytes | None = state.get("content") or state.get("file_bytes")
        if not content:
            raise ValueError("FileExtractionAgent: 'content' or 'file_bytes' is required in state")

        text = await file_service.extract_text_from_bytes(filename, content)
        return {"text": text, "filename": filename}

    async def health(self) -> dict[str, Any]:
        return {"agent": self.name, "status": "ok", "note": "Tesseract OCR availability checked at service level"}

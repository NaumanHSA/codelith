from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pdfplumber
import structlog

logger = structlog.get_logger(__name__)


@dataclass
class ParsedPdfDoc:
    path: str
    text: str
    page_count: int


class PdfParser:
    def parse_directory(self, root: Path) -> list[ParsedPdfDoc]:
        results: list[ParsedPdfDoc] = []
        for pdf_path in root.rglob("*.pdf"):
            if any(p in {".git", "node_modules", "__pycache__"} for p in pdf_path.parts):
                continue
            if pdf_path.stat().st_size > 50 * 1024 * 1024:  # skip >50 MB
                continue
            parsed = self._parse(pdf_path, root)
            if parsed:
                results.append(parsed)
        return results

    def _parse(self, path: Path, root: Path) -> ParsedPdfDoc | None:
        try:
            with pdfplumber.open(path) as pdf:
                pages = [page.extract_text() or "" for page in pdf.pages]
                text = "\n\n".join(p for p in pages if p.strip())
                if not text.strip():
                    return None
                return ParsedPdfDoc(
                    path=path.relative_to(root).as_posix(),
                    text=text,
                    page_count=len(pdf.pages),
                )
        except Exception as exc:
            logger.warning("pdf_parse_failed", path=str(path), error=str(exc))
            return None

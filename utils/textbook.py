"""Lehrbuch je Modul: hochgeladene Buchkapitel ergänzen die Folien – nur für Karteikarten und den Tutor.

Welche Buchkapitel zu einer Vorlesung gehören, erkennt die App am Vorlesungsthema („Berk/DeMarzo Kap. 4, 5“,
„Kap. 2 und 3: …“). Auf der Vorlesungsseite lässt sich die Zuordnung von Hand ändern.
"""

from __future__ import annotations

import re
from pathlib import PurePosixPath

from utils.storage import get_document_text

DOC_TYPE = "lehrbuch"
MAX_BOOK_CHARS = 250_000  # Obergrenze für den Tutor bei vielen Vorlesungen

_KAP = re.compile(r"Kap(?:itel|\.)?\s*((?:\d{1,2}\s*(?:[–\-,]|und|bis)?\s*)+)", re.IGNORECASE)
_FILE_NR = re.compile(r"(?:kap(?:itel)?|chapter|ch)[\s_.\-]*0*(\d{1,2})(?!\d)", re.IGNORECASE)


def chapters_from_text(text: str) -> list[int]:
    """„Kap. 1–3“ → [1, 2, 3]; „Kap. 4, 5“ → [4, 5]; „Kap. 2 und 3“ → [2, 3]."""
    numbers: list[int] = []
    for match in _KAP.finditer(text or ""):
        part = match.group(1)
        for a, b in re.findall(r"(\d{1,2})\s*(?:[–\-]|bis)\s*(\d{1,2})", part):
            numbers += list(range(int(a), int(b) + 1))
        part = re.sub(r"\d{1,2}\s*(?:[–\-]|bis)\s*\d{1,2}", " ", part)
        numbers += [int(n) for n in re.findall(r"\d{1,2}", part)]
    return sorted(set(n for n in numbers if 0 < n < 60))


def guess_chapter_from_filename(name: str) -> int | None:
    stem = PurePosixPath(name).stem
    match = _FILE_NR.search(stem) or re.search(r"(?<!\d)(\d{1,2})(?!\d)", stem)
    return int(match.group(1)) if match else None


def book_docs(data: dict) -> list[dict]:
    return sorted((d for d in data["documents"] if d["doc_type"] == DOC_TYPE),
                  key=lambda d: (d.get("book_chapter") or 999, d["filename"]))


def lecture_chapters(data: dict, lec: dict) -> list[int]:
    """Buchkapitel einer Vorlesung: von Hand gewählt oder aus dem Vorlesungsthema erkannt."""
    manual = data.get("lecture_book", {}).get(lec["id"])
    if manual is not None:
        return manual
    return chapters_from_text(lec.get("topic", ""))


def material_for_chapters(data: dict, chapters: list[int], limit: int | None = None) -> str:
    """Text der passenden Buchkapitel als KI-Kontext (leer, wenn nichts hochgeladen ist)."""
    parts, size = [], 0
    for doc in book_docs(data):
        if doc.get("book_chapter") not in chapters:
            continue
        text = get_document_text(doc, label="Buchseite")
        if not text.strip():
            continue
        if limit and size + len(text) > limit:
            break
        parts.append(f"<lehrbuch kapitel=\"{doc['book_chapter']}\" datei=\"{doc['filename']}\">\n{text}\n</lehrbuch>")
        size += len(text)
    return "\n\n".join(parts)


def material_for_lecture(data: dict, lec: dict) -> str:
    return material_for_chapters(data, lecture_chapters(data, lec))

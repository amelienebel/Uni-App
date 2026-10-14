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


# ---------------------------------------------------------------------------
# Ganzes Buch hochladen → automatisch in Kapitel aufteilen
# ---------------------------------------------------------------------------

_OUTLINE_NR = re.compile(r"^\s*(?:Kapitel|Chapter|Kap\.)?\s*(\d{1,2})(?:[.:\s]|$)\s*(.*)", re.IGNORECASE)
_PAGE_HEAD = re.compile(r"^\s*Kapitel\s+(\d{1,2})\b[\s:.\-–]*(.{0,80})", re.IGNORECASE | re.MULTILINE)


def _outline_chapters(reader) -> list[dict]:
    found = []

    def walk(items, depth):
        for item in items:
            if isinstance(item, list):
                if depth < 1:  # Unterkapitel ignorieren, nur oberste Ebene (+ Teile/Parts eine Ebene tiefer)
                    walk(item, depth + 1)
                continue
            match = _OUTLINE_NR.match(getattr(item, "title", "") or "")
            if match:
                try:
                    page = reader.get_destination_page_number(item)
                except Exception:  # noqa: BLE001
                    continue
                found.append({"nr": int(match.group(1)), "title": match.group(2).strip()[:80], "start": page + 1})

    try:
        walk(reader.outline, 0)
    except Exception:  # noqa: BLE001 - kaputtes Inhaltsverzeichnis
        return []
    return found


def _text_chapters(reader) -> list[dict]:
    """Fallback ohne Lesezeichen: Seiten, die oben mit „Kapitel N“ beginnen."""
    found, seen = [], set()
    for i, page in enumerate(reader.pages):
        try:
            head = (page.extract_text() or "")[:300]
        except Exception:  # noqa: BLE001
            continue
        match = _PAGE_HEAD.search(head)
        if match and int(match.group(1)) not in seen:
            seen.add(int(match.group(1)))
            found.append({"nr": int(match.group(1)), "title": match.group(2).strip().split("\n")[0][:80],
                          "start": i + 1})
    return found


def detect_chapters(content: bytes) -> tuple[list[dict], int]:
    """Kapitelanfänge (Seitenzahl ab 1) aus Lesezeichen oder Seitenköpfen; dazu die Gesamtseitenzahl."""
    import io

    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(content))
    total = len(reader.pages)
    chapters = _outline_chapters(reader) or _text_chapters(reader)
    # aufsteigend nach Seite, je Kapitelnummer nur der erste Treffer
    result, seen = [], set()
    for ch in sorted(chapters, key=lambda c: c["start"]):
        if ch["nr"] not in seen:
            seen.add(ch["nr"])
            result.append(ch)
    return result, total


def split_book(module_id: str, filename: str, content: bytes, chapters: list[dict]) -> int:
    """Speichert jedes Kapitel als eigenes Lehrbuch-PDF. chapters: [{nr, title, start}] (Seiten ab 1)."""
    import gc
    import io

    from pypdf import PdfReader, PdfWriter

    from utils.storage import add_document, load_module, save_module

    reader = PdfReader(io.BytesIO(content))
    total = len(reader.pages)
    chapters = sorted((c for c in chapters if c.get("nr") and c.get("start")), key=lambda c: int(c["start"]))
    stem = PurePosixPath(filename).stem
    created = 0
    for i, ch in enumerate(chapters):
        start = max(1, int(ch["start"]))
        end = int(chapters[i + 1]["start"]) - 1 if i + 1 < len(chapters) else total
        if end < start:
            continue
        writer = PdfWriter()
        for p in range(start - 1, min(end, total)):
            writer.add_page(reader.pages[p])
        buf = io.BytesIO()
        writer.write(buf)
        title = f" – {ch['title']}" if ch.get("title") else ""
        doc = add_document(module_id, f"{stem} – Kapitel {ch['nr']}{title}.pdf", buf.getvalue(), DOC_TYPE, None)
        doc.update({"book_chapter": int(ch["nr"]), "book_pages": f"{start}–{end}"})
        created += 1
        del writer, buf
        gc.collect()
    save_module(module_id)
    load_module(module_id)
    return created

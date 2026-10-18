"""Skript je Modul: ein ganzes Skript hochladen → die App teilt es in die Abschnitte der einzelnen Vorlesungen auf.

Welche Abschnitte zu einer Vorlesung gehören, erkennt die App am Vorlesungsthema („Skript 1.1–1.4“,
„Skript Abschnitt 3“). Die Abschnittsanfänge kommen aus den Lesezeichen des PDFs oder aus den Überschriften im
Text. Jede Vorlesung bekommt ihren Teil als eigenes PDF (Typ „skript“) – damit fließt er in Vorbereitung,
Karteikarten, Quiz und Tutor ein.
"""

from __future__ import annotations

import re
from pathlib import PurePosixPath

from utils.storage import get_document_pages

DOC_TYPE = "skript"
MAX_PREP_CHARS = 120_000  # Obergrenze für den Skript-Teil in der Vorbereitung

_NR = r"\d{1,2}(?:\.\d{1,2}){0,3}"
_TOPIC = re.compile(rf"Skript\s*(?:Abschnitt|Kap(?:itel|\.)?)?\s*({_NR})(?:\s*(?:[–\-]|bis)\s*({_NR}))?",
                    re.IGNORECASE)
_HEADING = re.compile(rf"^\s*({_NR})\.?\s+([A-ZÄÖÜ][^\n]{{2,90}})$")
_TOC_LINE = re.compile(r"(?:\.{3,}|…+|\s)\s*\d{1,3}\s*$")


def _key(nr: str) -> tuple[int, ...]:
    return tuple(int(x) for x in nr.split("."))


def _within(nr: str, parent: str) -> bool:
    return nr == parent or nr.startswith(parent + ".")


def sections_from_topic(topic: str) -> tuple[str, str] | None:
    """„Skript 1.1–1.4“ → ("1.1", "1.4"); „Skript Abschnitt 3“ → ("3", "3")."""
    match = _TOPIC.search(topic or "")
    if not match:
        return None
    return match.group(1), match.group(2) or match.group(1)


def _outline_sections(reader) -> list[dict]:
    found = []

    def walk(items):
        for item in items:
            if isinstance(item, list):
                walk(item)
                continue
            match = re.match(rf"^\s*({_NR})\.?\s+(.*)", getattr(item, "title", "") or "")
            if match:
                try:
                    page = reader.get_destination_page_number(item)
                except Exception:  # noqa: BLE001
                    continue
                found.append({"nr": match.group(1), "title": match.group(2).strip()[:80], "start": page + 1})

    try:
        walk(reader.outline)
    except Exception:  # noqa: BLE001 - kaputtes Inhaltsverzeichnis
        return []
    return found


def _text_sections(pages: list[str]) -> list[dict]:
    """Fallback ohne Lesezeichen: Zeilen wie „1.2 Bilanz und GuV“ (Inhaltsverzeichnis-Seiten werden übersprungen)."""
    found = []
    for i, text in enumerate(pages, start=1):
        hits = []
        for line in (text or "").splitlines():
            match = _HEADING.match(line)
            if match and not _TOC_LINE.search(line) and _key(match.group(1))[0] > 0:
                hits.append({"nr": match.group(1), "title": match.group(2).strip()[:80], "start": i})
        if len(hits) < 6:  # viele Treffer auf einer Seite ⇒ Inhaltsverzeichnis
            found += hits
    return found


def detect_sections(content: bytes, pages: list[str]) -> tuple[list[dict], int]:
    """Abschnittsanfänge (Seitenzahl ab 1), je Nummer der erste Treffer, nach Seite sortiert; dazu die Seitenzahl."""
    import io

    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(content))
    total = len(reader.pages)
    sections = _outline_sections(reader) or _text_sections(pages)
    result, seen = [], set()
    for sec in sorted(sections, key=lambda s: s["start"]):
        if sec["nr"] not in seen:
            seen.add(sec["nr"])
            result.append(sec)
    return result, total


def page_range(sections: list[dict], first: str, last: str, total: int) -> tuple[int, int] | None:
    """Seiten von Abschnitt first bis einschließlich last. Die Seite, auf der der nächste Abschnitt beginnt,
    gehört mit dazu (der vorige Abschnitt endet oft mitten auf der Seite)."""
    starts = [s["start"] for s in sections if _within(s["nr"], first)]
    if not starts:
        return None
    start = min(starts)
    later = [s["start"] for s in sections
             if s["start"] >= start and _key(s["nr"]) > _key(last) and not _within(s["nr"], last)]
    end = min(later) if later else total
    return start, max(start, min(end, total))


def proposal(lectures: list[dict], sections: list[dict], total: int) -> list[dict]:
    """Vorschlag je Vorlesung mit „Skript …“ im Thema: Abschnitte und Seitenbereich."""
    rows = []
    for lec in lectures:
        found = sections_from_topic(lec.get("topic", ""))
        if not found:
            continue
        label = found[0] if found[0] == found[1] else f"{found[0]}–{found[1]}"
        pages = page_range(sections, found[0], found[1], total)
        rows.append({"unit": lec["id"], "lecture": f"VL {lec['nr']} ({lec['date']:%d.%m.})", "sections": label,
                     "start": pages[0] if pages else None, "end": pages[1] if pages else None})
    return rows


def split_script(module_id: str, filename: str, content: bytes, rows: list[dict], chapters: dict) -> int:
    """Speichert je Vorlesung ihren Teil des Skripts als eigenes PDF. rows: [{unit, sections, start, end}].
    Frühere automatisch aufgeteilte Teile derselben Vorlesungen werden ersetzt."""
    import gc
    import io

    from pypdf import PdfReader, PdfWriter

    from utils.storage import add_document, delete_document, load_module, save_module

    reader = PdfReader(io.BytesIO(content))
    total = len(reader.pages)
    data = load_module(module_id)
    units = {r["unit"] for r in rows}
    for doc in list(data["documents"]):
        if doc.get("script_split") and doc.get("unit") in units:
            delete_document(module_id, doc["id"])
    stem = PurePosixPath(filename).stem
    created = 0
    for row in rows:
        start, end = max(1, int(row["start"])), min(int(row["end"]), total)
        if end < start:
            continue
        writer = PdfWriter()
        for p in range(start - 1, end):
            writer.add_page(reader.pages[p])
        buf = io.BytesIO()
        writer.write(buf)
        name = f"{stem} – Abschnitt {row['sections']}.pdf" if row.get("sections") else f"{stem} – S. {start}–{end}.pdf"
        doc = add_document(module_id, name, buf.getvalue(), DOC_TYPE, chapters.get(row["unit"]), unit=row["unit"])
        doc.update({"script_split": True, "script_sections": row.get("sections", ""), "script_start": start,
                    "script_pages": f"{start}–{end}"})
        created += 1
        del writer, buf
        gc.collect()
    save_module(module_id)
    load_module(module_id)
    return created


def prep_text(docs: list[dict]) -> str:
    """Skript-Teile einer Vorlesung für die Vorbereitung – Seiten mit der Seitenzahl im ganzen Skript."""
    blocks, size = [], 0
    for doc in docs:
        offset = int(doc.get("script_start") or 1) - 1
        pages = [f"--- Skript S. {offset + i} ---\n{text}" for i, text in enumerate(get_document_pages(doc), start=1)]
        text = "\n\n".join(pages)
        if not text.strip() or size + len(text) > MAX_PREP_CHARS:
            continue
        sections = f" abschnitte=\"{doc['script_sections']}\"" if doc.get("script_sections") else ""
        blocks.append(f"<skript name=\"{doc['filename']}\"{sections}>\n{text}\n</skript>")
        size += len(text)
    return "\n\n".join(blocks)

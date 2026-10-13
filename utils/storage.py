"""Persistenz: alle Daten liegen als strukturierte JSON-Dateien im Ordner data/.

Struktur:
    data/settings.json              Klausurtermine, Stundenplan, KI-Einstellungen
    data/todos.json                 Erledigt-Status der generierten To-dos
    data/modules/<modul>.json       Kapitel, Dokumente, Notizen, Lernkarten, Formeln, Quiz, Chat
    data/texts/<dokument-id>.json   Extrahierter Text eines PDFs (seitenweise)
    data/uploads/<modul>/...        Hochgeladene PDFs und Bilder

Zur Laufzeit werden die Daten in st.session_state gehalten und bei jeder
Änderung sofort zurückgeschrieben.
"""

from __future__ import annotations

import copy
import json
import os
import re
import tempfile
import uuid
from datetime import date, datetime
from pathlib import Path

import streamlit as st

from utils import cloud_sync
from utils.config import BASE_DIR, get_module, load_config

DATA_DIR = BASE_DIR / "data"
MODULE_DIR = DATA_DIR / "modules"
TEXT_DIR = DATA_DIR / "texts"
UPLOAD_DIR = DATA_DIR / "uploads"
SETTINGS_PATH = DATA_DIR / "settings.json"
TODOS_PATH = DATA_DIR / "todos.json"

CHAPTER_STATUS_FIELDS = {
    "vorbereitet": "Vorbereitet",
    "nachbereitet": "Nachbereitet",
    "uebung": "Übung gelöst",
}

DEFAULT_SETTINGS = {
    "semester_start": None,
    "semester_end": None,
    "exam_dates": {},  # modul_id -> {"date": "YYYY-MM-DD", "time": "", "room": ""}
    "schedule": None,  # None = Stundenplan aus config.json
    "ai": {"model": "claude-opus-5-5", "effort": "medium"},
    "learning": {"daily_review_limit": 60, "prep_days_before": 1, "review_days_after": 2},
}


def ensure_dirs() -> None:
    for d in (DATA_DIR, MODULE_DIR, TEXT_DIR, UPLOAD_DIR):
        d.mkdir(parents=True, exist_ok=True)


def new_id() -> str:
    return uuid.uuid4().hex[:12]


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def today() -> date:
    return date.today()


def _read_json(path: Path, default):
    if not path.exists():
        return copy.deepcopy(default)
    try:
        with path.open(encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        # Defekte Datei nicht überschreiben, sondern sichern
        backup = path.with_suffix(path.suffix + f".defekt-{datetime.now():%Y%m%d%H%M%S}")
        try:
            path.rename(backup)
        except OSError:
            pass
        return copy.deepcopy(default)


def _write_json(path: Path, data) -> None:
    """Atomares Schreiben: erst in eine temporäre Datei, dann ersetzen."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2, default=str)
        os.replace(tmp, path)
        cloud_sync.notify_changed(path)
    except BaseException:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


# ---------------------------------------------------------------------------
# Einstellungen
# ---------------------------------------------------------------------------

def load_settings() -> dict:
    if "_settings" not in st.session_state:
        ensure_dirs()
        data = _read_json(SETTINGS_PATH, DEFAULT_SETTINGS)
        for key, value in DEFAULT_SETTINGS.items():
            if key not in data:
                data[key] = copy.deepcopy(value)
            elif isinstance(value, dict) and isinstance(data[key], dict) and key != "exam_dates":
                for sub_key, sub_value in value.items():
                    data[key].setdefault(sub_key, sub_value)
        st.session_state["_settings"] = data
    return st.session_state["_settings"]


def save_settings() -> None:
    _write_json(SETTINGS_PATH, load_settings())


def semester_dates(cfg: dict | None = None) -> tuple[date, date]:
    cfg = cfg or load_config()
    settings = load_settings()
    start = settings.get("semester_start") or cfg["app"].get("semester_start")
    end = settings.get("semester_end") or cfg["app"].get("semester_end")
    return date.fromisoformat(start), date.fromisoformat(end)


def get_schedule(cfg: dict | None = None) -> list[dict]:
    """Stundenplan: individuell in den Einstellungen gespeichert oder aus config.json."""
    cfg = cfg or load_config()
    settings = load_settings()
    if settings.get("schedule"):
        return [{**e, "room": room_label(e.get("room", ""))} for e in settings["schedule"]]
    schedule = []
    for module in cfg["modules"]:
        for event in module["schedule"]:
            schedule.append({"module_id": module["id"], **event})
    return schedule


def room_label(room: str) -> str:
    """Kurze Raumangabe: alles im Audimax heißt einfach „Audimax“."""
    return "Audimax" if re.search(r"audi\s*max", room or "", re.IGNORECASE) else (room or "")


def get_exam_date(module_id: str) -> date | None:
    """Klausurtermin aus den Einstellungen, sonst Vorgabe aus config.json (Feld exam_date)."""
    entry = load_settings().get("exam_dates", {}).get(module_id) or {}
    value = entry.get("date")
    if not value:
        try:
            value = get_module(load_config(), module_id).get("exam_date")
        except KeyError:
            value = None
    if value:
        try:
            return date.fromisoformat(value)
        except ValueError:
            return None
    return None


def lecture_breaks(cfg: dict | None = None) -> list[tuple[date, date, str]]:
    """Vorlesungsfreie Zeiten (z. B. Weihnachtsferien) aus config.json."""
    cfg = cfg or load_config()
    breaks = []
    for b in cfg["app"].get("lecture_breaks", []):
        try:
            breaks.append((date.fromisoformat(b["start"]), date.fromisoformat(b["end"]), b.get("name", "vorlesungsfrei")))
        except (KeyError, ValueError):
            continue
    return breaks


def days_until_exam(module_id: str, ref: date | None = None) -> int | None:
    exam = get_exam_date(module_id)
    if exam is None:
        return None
    return (exam - (ref or today())).days


# ---------------------------------------------------------------------------
# Moduldaten
# ---------------------------------------------------------------------------

def _default_module_data(module_cfg: dict) -> dict:
    chapters = []
    for ch in module_cfg["chapters"]:
        chapters.append({
            "id": ch["id"],
            "title": ch["title"],
            "week": ch.get("week"),
            "status": {key: False for key in CHAPTER_STATUS_FIELDS},
        })
    formulas = []
    for f in module_cfg.get("base_formulas", []):
        formulas.append({
            "id": new_id(),
            "name": f["name"],
            "latex": f["latex"],
            "explanation": f.get("explanation", ""),
            "chapter_id": f.get("chapter_id"),
            "source": "Basis (config.json)",
        })
    return {
        "module_id": module_cfg["id"],
        "chapters": chapters,
        "documents": [],
        "notes": {},
        "cards": [],
        "formulas": formulas,
        "quizzes": [],
        "exam_analyses": [],
        "chat": [],
        "syllabus_version": int(module_cfg.get("syllabus_version", 0)),
        "created_at": now_iso(),
    }


def _apply_syllabus_update(data: dict, module_cfg: dict, default: dict) -> bool:
    """Übernimmt eine neue Kapitelstruktur aus config.json (wenn syllabus_version erhöht wurde).

    Erledigt-Status bleibt für gleichnamige Kapitel-IDs erhalten. Unterlagen, Karten und Formeln,
    deren Kapitel es nicht mehr gibt, werden „ohne Kapitel“ geführt. Basisformeln werden erneuert.
    """
    version = int(module_cfg.get("syllabus_version", 0))
    if version <= int(data.get("syllabus_version", 0)):
        return False
    old_status = {ch["id"]: ch.get("status", {}) for ch in data["chapters"]}
    data["chapters"] = default["chapters"]
    for ch in data["chapters"]:
        ch["status"].update({k: v for k, v in old_status.get(ch["id"], {}).items() if k in CHAPTER_STATUS_FIELDS})
    valid = {ch["id"] for ch in data["chapters"]}
    for collection in ("documents", "cards", "formulas"):
        for item in data.get(collection, []):
            if item.get("chapter_id") not in valid:
                item["chapter_id"] = None
    base_source = "Basis (config.json)"
    data["formulas"] = [f for f in data["formulas"] if f.get("source") != base_source] + \
        [f for f in default["formulas"] if f.get("source") == base_source]
    data["removed_chapters"] = []
    data["syllabus_version"] = version
    return True


def load_module(module_id: str) -> dict:
    key = f"_module_{module_id}"
    if key not in st.session_state:
        ensure_dirs()
        module_cfg = get_module(load_config(), module_id)
        default = _default_module_data(module_cfg)
        data = _read_json(MODULE_DIR / f"{module_id}.json", default)
        data.setdefault("chapters", [])
        data.setdefault("formulas", [])
        migrated = _apply_syllabus_update(data, module_cfg, default)
        for field, value in default.items():
            data.setdefault(field, value)
        # Neue Kapitel aus config.json ergänzen (Erweiterbarkeit)
        known = {c["id"] for c in data["chapters"]} | set(data.get("removed_chapters", []))
        for ch in default["chapters"]:
            if ch["id"] not in known:
                data["chapters"].append(ch)
        for ch in data["chapters"]:
            ch.setdefault("status", {})
            for status_key in CHAPTER_STATUS_FIELDS:
                ch["status"].setdefault(status_key, False)
        st.session_state[key] = data
        if migrated or not (MODULE_DIR / f"{module_id}.json").exists():
            save_module(module_id)
    return st.session_state[key]


def save_module(module_id: str) -> None:
    data = st.session_state.get(f"_module_{module_id}")
    if data is not None:
        _write_json(MODULE_DIR / f"{module_id}.json", data)


def reload_all() -> None:
    """Verwirft den Laufzeit-Cache (z. B. nach dem Wiederherstellen eines Backups)."""
    for key in list(st.session_state.keys()):
        if key.startswith(("_module_", "_extra_")) or key in ("_settings", "_todos"):
            del st.session_state[key]


def chapter_by_id(module_data: dict, chapter_id: str | None) -> dict | None:
    for ch in module_data["chapters"]:
        if ch["id"] == chapter_id:
            return ch
    return None


def chapter_label(module_data: dict, chapter_id: str | None) -> str:
    ch = chapter_by_id(module_data, chapter_id)
    if ch is None:
        return "— ohne Kapitel —"
    idx = module_data["chapters"].index(ch) + 1
    return f"Kap. {idx}: {ch['title']}"


# ---------------------------------------------------------------------------
# Uploads & Dokumente
# ---------------------------------------------------------------------------

def safe_filename(name: str) -> str:
    name = Path(name).name
    name = re.sub(r"[^\w.\- äöüÄÖÜß()]", "_", name).strip() or "datei"
    return name[:120]


def save_upload(module_id: str, filename: str, content: bytes, subdir: str = "pdf") -> str:
    """Speichert eine Datei und gibt den Pfad relativ zu data/ zurück."""
    target_dir = UPLOAD_DIR / module_id / subdir
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / f"{new_id()}_{safe_filename(filename)}"
    path.write_bytes(content)
    cloud_sync.notify_changed(path)
    return str(path.relative_to(DATA_DIR))


def abs_data_path(rel_path: str) -> Path:
    path = (DATA_DIR / rel_path).resolve()
    if DATA_DIR.resolve() not in path.parents:
        raise ValueError("Ungültiger Pfad")
    return path


def delete_data_file(rel_path: str | None) -> None:
    if not rel_path:
        return
    try:
        path = abs_data_path(rel_path)
        path.unlink(missing_ok=True)
        cloud_sync.notify_changed(path)
    except (ValueError, OSError):
        pass


def add_document(module_id: str, filename: str, content: bytes, doc_type: str,
                 chapter_id: str | None, extracted: dict | None = None, unit: str | None = None) -> dict:
    """Legt ein PDF-Dokument an: Datei speichern, Text extrahieren, Metadaten anlegen."""
    from utils.pdf_parser import extract_pdf  # lokaler Import vermeidet Zyklen

    data = load_module(module_id)
    rel_path = save_upload(module_id, filename, content, "pdf")
    extracted = extracted or extract_pdf(content)
    doc_id = new_id()
    _write_json(TEXT_DIR / f"{doc_id}.json", {"pages": extracted["pages"], "method": extracted["method"]})
    doc = {
        "id": doc_id,
        "filename": filename,
        "path": rel_path,
        "doc_type": doc_type,
        "chapter_id": chapter_id,
        "unit": unit,
        "n_pages": len(extracted["pages"]),
        "n_chars": sum(len(p) for p in extracted["pages"]),
        "uploaded_at": now_iso(),
        "analysis": None,
    }
    data["documents"].append(doc)
    save_module(module_id)
    return doc


IMAGE_TYPES = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "webp": "image/webp",
               "gif": "image/gif"}


def add_file(module_id: str, filename: str, content: bytes, doc_type: str, chapter_id: str | None,
             unit: str | None) -> dict:
    """PDF (mit Textextraktion) oder Foto (z. B. handschriftliche Lösung) einer Einheit hinzufügen."""
    ext = Path(filename).suffix.lower().lstrip(".")
    if ext not in IMAGE_TYPES:
        return add_document(module_id, filename, content, doc_type, chapter_id, unit=unit)
    data = load_module(module_id)
    doc = {"id": new_id(), "filename": filename, "path": save_upload(module_id, filename, content, "images"),
           "doc_type": doc_type, "chapter_id": chapter_id, "unit": unit, "kind": "image",
           "mime": IMAGE_TYPES[ext], "n_pages": 0, "n_chars": 0, "uploaded_at": now_iso(), "analysis": None}
    data["documents"].append(doc)
    save_module(module_id)
    return doc


def get_document_pages(doc: dict) -> list[str]:
    return _read_json(TEXT_DIR / f"{doc['id']}.json", {"pages": []}).get("pages", [])


def get_document_text(doc: dict, with_page_markers: bool = True, label: str = "Seite") -> str:
    pages = get_document_pages(doc)
    if not with_page_markers:
        return "\n\n".join(pages)
    return "\n\n".join(f"--- {label} {i} ---\n{text}" for i, text in enumerate(pages, start=1))


def delete_document(module_id: str, doc_id: str) -> None:
    data = load_module(module_id)
    for doc in list(data["documents"]):
        if doc["id"] == doc_id:
            delete_data_file(doc.get("path"))
            (TEXT_DIR / f"{doc_id}.json").unlink(missing_ok=True)
            cloud_sync.notify_changed(TEXT_DIR / f"{doc_id}.json")
            data["documents"].remove(doc)
    save_module(module_id)


def documents_of(module_data: dict, doc_types: tuple[str, ...] | None = None,
                 chapter_id: str | None = None) -> list[dict]:
    docs = module_data["documents"]
    if doc_types:
        docs = [d for d in docs if d["doc_type"] in doc_types]
    if chapter_id:
        docs = [d for d in docs if d.get("chapter_id") == chapter_id]
    return docs


# ---------------------------------------------------------------------------
# Notizen, Formeln, Karten
# ---------------------------------------------------------------------------

def get_notes(module_data: dict, chapter_id: str) -> dict:
    notes = module_data["notes"].setdefault(chapter_id, {})
    for field in ("text", "emphasized", "briefly", "examples", "pitch"):
        notes.setdefault(field, "")
    notes.setdefault("images", [])
    return notes


def add_formulas(module_id: str, formulas: list[dict], source: str, chapter_id: str | None = None) -> int:
    """Fügt Formeln hinzu (Duplikate anhand des normalisierten LaTeX werden übersprungen)."""
    data = load_module(module_id)

    def norm(latex: str) -> str:
        return re.sub(r"\s+", "", latex or "")

    existing = {norm(f["latex"]) for f in data["formulas"]}
    added = 0
    for f in formulas:
        latex = (f.get("latex") or "").strip()
        if not latex or norm(latex) in existing:
            continue
        data["formulas"].append({
            "id": new_id(),
            "name": (f.get("name") or "Formel").strip(),
            "latex": latex,
            "explanation": (f.get("explanation") or "").strip(),
            "chapter_id": f.get("chapter_id") or chapter_id,
            "source": source,
            "page": f.get("page"),
        })
        existing.add(norm(latex))
        added += 1
    save_module(module_id)
    return added


def suggest_formulas(module_id: str, formulas: list[dict], source: str, chapter_id: str | None = None) -> int:
    """Legt Formeln als Vorschläge ab – sie landen erst nach deiner Prüfung in der Formelsammlung."""
    data = load_module(module_id)
    inbox = data.setdefault("formula_inbox", [])

    def norm(latex: str) -> str:
        return re.sub(r"\s+", "", latex or "")

    known = {norm(f["latex"]) for f in data["formulas"]} | {norm(f["latex"]) for f in inbox}
    added = 0
    for f in formulas:
        latex = (f.get("latex") or "").strip()
        if not latex or norm(latex) in known:
            continue
        inbox.append({"id": new_id(), "name": (f.get("name") or "Formel").strip(), "latex": latex,
                      "explanation": (f.get("explanation") or "").strip(),
                      "chapter_id": f.get("chapter_id") or chapter_id, "source": source, "page": f.get("page")})
        known.add(norm(latex))
        added += 1
    save_module(module_id)
    return added


# ---------------------------------------------------------------------------
# To-dos
# ---------------------------------------------------------------------------

def load_todos() -> dict:
    if "_todos" not in st.session_state:
        st.session_state["_todos"] = _read_json(TODOS_PATH, {})
    return st.session_state["_todos"]


def save_todos() -> None:
    _write_json(TODOS_PATH, load_todos())


# ---------------------------------------------------------------------------
# Weitere Datenbereiche (Podcasts, Klausur-Lernplan, Erinnerungen)
# ---------------------------------------------------------------------------

def load_extra(name: str) -> dict:
    """Lädt data/<name>.json (z. B. podcasts, exam_plan) und hält es im Sitzungsspeicher."""
    key = f"_extra_{name}"
    if key not in st.session_state:
        st.session_state[key] = _read_json(DATA_DIR / f"{name}.json", {})
    return st.session_state[key]


def save_extra(name: str) -> None:
    _write_json(DATA_DIR / f"{name}.json", load_extra(name))

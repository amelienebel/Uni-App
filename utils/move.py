"""Eine versehentlich falsch hochgeladene Vorlesung samt Minithemen in ein anderes Modul / eine andere VL verschieben."""

from __future__ import annotations

from datetime import date

from utils import planner, topics
from utils.config import get_module, load_config
from utils.storage import load_module, load_todos, save_module, save_todos

_NOTE_TEXT_FIELDS = ("text", "emphasized", "briefly", "skip", "card_hint", "examples")


def _merge_notes(src: dict, dst: dict) -> dict:
    merged = dict(dst)
    for field in _NOTE_TEXT_FIELDS:
        a, b = (dst.get(field) or "").strip(), (src.get(field) or "").strip()
        merged[field] = b if not a else (a if not b or b in a else f"{a}\n{b}")
    merged["images"] = list(dst.get("images") or []) + list(src.get("images") or [])
    scopes = dict(dst.get("scopes") or {})
    scopes.update(src.get("scopes") or {})
    if scopes:
        merged["scopes"] = scopes
    for key, value in src.items():
        merged.setdefault(key, value)
    return merged


def move_lecture(src_module: str, src_lec: dict, dst_module: str, dst_lec: dict,
                 doc_ids: list[str] | None = None) -> dict:
    """Verschiebt Dateien, Hinweise, Minithemen, Definitionen, Wissensstand, Fragen und den Erledigt-Stand.

    Gibt zurück, wie viel verschoben wurde."""
    src_id, dst_id = src_lec["id"], dst_lec["id"]
    if (src_module, src_id) == (dst_module, dst_id):
        return {"docs": 0, "minitopics": 0}
    src, dst = load_module(src_module), load_module(dst_module)
    same = src is dst

    # Dateien (Text und PDF bleiben unter ihrer ID gespeichert, nur die Zuordnung wandert)
    docs = [d for d in src["documents"] if d.get("unit") == src_id and (doc_ids is None or d["id"] in doc_ids)]
    for doc in docs:
        doc["unit"], doc["chapter_id"] = dst_id, dst_lec.get("chapter_id")
        doc.pop("shared_units", None)
        if not same:
            src["documents"].remove(doc)
            dst["documents"].append(doc)

    # Hinweise / Notizen inkl. Umfang je Datei
    src_notes = src.setdefault("lecture_notes", {}).pop(src_id, None)
    if src_notes:
        dst_notes = dst.setdefault("lecture_notes", {}).get(dst_id) or {}
        dst["lecture_notes"][dst_id] = _merge_notes(src_notes, dst_notes)

    # Minithemen
    entry = src.setdefault("topics", {}).pop(src_id, None)
    mt_ids = {m["id"] for t in (entry or {}).get("topics", []) for m in t.get("minitopics", [])}
    if entry:
        dst.setdefault("topics", {})[dst_id] = entry

    # Wissensstand, Fragen, Zuordnung alter Karten (die gehören zum alten Modul → Verweis löschen)
    for mt_id in mt_ids:
        if mt_id in src.get("mastery", {}):
            dst.setdefault("mastery", {})[mt_id] = src["mastery"].pop(mt_id)
    moved_q = [q for q in src.get("questions", []) if q.get("minitopic_id") in mt_ids]
    for q in moved_q:
        q["lecture_id"] = dst_id
        if not same:
            src["questions"].remove(q)
            dst.setdefault("questions", []).append(q)
    amap = src.get("archive_map") or {}
    for card_id in [c for c, m in amap.items() if m in mt_ids]:
        if not same:
            del amap[card_id]

    # Definitionen aus dieser Vorlesung
    defs = [d for d in src.get("definitions", []) if d.get("unit") == src_id]
    for d in defs:
        d["unit"], d["chapter_id"] = dst_id, dst_lec.get("chapter_id")
        if not same:
            src["definitions"].remove(d)
            dst.setdefault("definitions", []).append(d)

    # Vorlesungs-Checks dieser Vorlesung
    for s in [s for s in src.get("sessions", []) if s.get("lecture_id") == src_id]:
        s["lecture_id"] = dst_id
        for item in s.get("items", []):
            if item.get("lecture_id") == src_id:
                item["lecture_id"] = dst_id
        if not same:
            src["sessions"].remove(s)
            dst.setdefault("sessions", []).append(s)

    # Zusammenfassung aus der Nacharbeit
    nach = (src.get("nacharbeit") or {}).pop(src_id, None)
    if nach:
        dst.setdefault("nacharbeit", {})[dst_id] = nach

    if src_id in (src.get("legacy_lectures") or []) and not same:
        src["legacy_lectures"].remove(src_id)

    # Erledigt-Stand (Upload, Nacharbeit, Check 1 und 2) wandert mit
    state = load_todos()
    src_date = src_lec["date"] if isinstance(src_lec["date"], date) else date.fromisoformat(src_lec["date"])
    dst_date = dst_lec["date"] if isinstance(dst_lec["date"], date) else date.fromisoformat(dst_lec["date"])
    for field in ("nachbereitet", "nacharbeit", "check", "check2"):
        old = planner.lecture_key(src_module, src_date, field)
        if state.get(old):
            state[planner.lecture_key(dst_module, dst_date, field)] = state[old]
            state.pop(old, None)
    save_todos()
    cfg = load_config()
    planner.sync_chapter_status(get_module(cfg, src_module), src, src_lec.get("chapter_id"), "nachbereitet", state)
    planner.sync_chapter_status(get_module(cfg, dst_module), dst, dst_lec.get("chapter_id"), "nachbereitet", state)

    save_module(src_module)
    if not same:
        save_module(dst_module)
    return {"docs": len(docs), "minitopics": len(mt_ids), "definitions": len(defs)}


def movable(data: dict, lec: dict) -> bool:
    """Gibt es zu dieser Vorlesung etwas zu verschieben?"""
    return bool([d for d in data["documents"] if d.get("unit") == lec["id"]] or topics.lecture_topics(data, lec["id"]))

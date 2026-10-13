"""Lerneinheiten eines Moduls: Vorlesungen und Übungen (inkl. Tutorium) mit Zuordnung zueinander.

- Jede Vorlesung hat die ID „vl:<Datum>“, jede Übung „ex:<Woche>:<Nr>“.
- Eine Übung gehört zu einem Kapitel (laut Kursplan, von Hand geändert oder automatisch: Kapitel der
  letzten Vorlesung vor der Übung) und damit zu den Vorlesungen dieses Kapitels.
- Dateien, Notizen, Fragen und Lernkarten tragen die ID ihrer Einheit im Feld „unit“.
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import PurePosixPath

from utils import planner
from utils.config import WEEKDAYS_SHORT
from utils.storage import get_schedule, lecture_breaks

LECTURE_DOC_TYPES = ("folien", "skript", "sonstiges")
EXERCISE_DOC_TYPES = ("uebung", "loesung", "eigene_loesung")
SESSION_TYPES = ("Übung", "Tutorium")


def lecture_unit_id(d: date) -> str:
    return f"vl:{d.isoformat()}"


def exercise_unit_id(ex: dict) -> str:
    return f"ex:{ex['week_of'].isoformat()}:{ex['index']}"


def lectures(cfg: dict, module_cfg: dict) -> list[dict]:
    breaks = lecture_breaks(cfg)
    result = []
    for nr, lec in enumerate(planner.lectures_of(module_cfg), start=1):
        result.append({**lec, "kind": "lecture", "id": lecture_unit_id(lec["date"]), "nr": nr,
                       "is_break": bool(planner.break_for(lec["date"], breaks))})
    return result


def _sessions(module_id: str, ex: dict, session: date, schedule: list[dict], breaks) -> list[dict]:
    """Übung und Tutorium, in denen das Blatt besprochen wird (Woche des Besprechungstermins)."""
    events = [e for e in planner.week_events(schedule, planner.monday_of(session))
              if e.get("module_id") == module_id and e.get("type") in SESSION_TYPES
              and e["date"] >= session and not planner.break_for(e["date"], breaks)]
    if not any(e["date"] == session for e in events):
        # Sondertermin (z. B. einmalig mittwochs statt donnerstags)
        events = [{"module_id": module_id, "type": "Übung", "date": session, "start": ex.get("start", ""),
                   "end": ex.get("end", ""), "room": ex.get("room", "")}]
    return events


def exercises(cfg: dict, module_cfg: dict, data: dict, lecture_list: list[dict] | None = None) -> list[dict]:
    module_id = module_cfg["id"]
    schedule = get_schedule(cfg)
    breaks = lecture_breaks(cfg)
    lecture_list = lecture_list if lecture_list is not None else lectures(cfg, module_cfg)
    overrides = data.get("exercise_chapters", {})
    result = []
    for ex in planner.exercises_of(module_cfg):
        uid = exercise_unit_id(ex)
        session = planner.exercise_session(module_id, ex, schedule, breaks)
        chapter_id, auto = overrides.get(uid) or ex.get("chapter_id"), False
        if not chapter_id:
            before = [lec for lec in lecture_list if lec["date"] < session and lec.get("chapter_id")]
            chapter_id, auto = (before[-1]["chapter_id"] if before else None), True
        result.append({**ex, "kind": "exercise", "id": uid, "session": session, "chapter_id": chapter_id,
                       "chapter_auto": auto, "plan_key": planner.exercise_key(module_id, ex),
                       "sessions": _sessions(module_id, ex, session, schedule, breaks)})
    return result


def all_units(cfg: dict, module_cfg: dict, data: dict) -> tuple[list[dict], list[dict]]:
    lecs = lectures(cfg, module_cfg)
    return lecs, exercises(cfg, module_cfg, data, lecs)


def find_unit(cfg: dict, module_cfg: dict, data: dict, unit_id: str) -> dict | None:
    lecs, exs = all_units(cfg, module_cfg, data)
    return next((u for u in lecs + exs if u["id"] == unit_id), None)


def unit_for_event(cfg: dict, module_cfg: dict, data: dict, ev_type: str, ev_date: date) -> str | None:
    """Klick im Stundenplan → passende Vorlesung bzw. Übung."""
    lecs, exs = all_units(cfg, module_cfg, data)
    if ev_type == "Vorlesung":
        return next((lec["id"] for lec in lecs if lec["date"] == ev_date), None)
    match = next((ex for ex in exs if ex["session"] == ev_date), None) \
        or next((ex for ex in exs if any(s["date"] == ev_date for s in ex["sessions"])), None)
    return match["id"] if match else None


def short_label(unit: dict) -> str:
    if unit["kind"] == "lecture":
        d = unit["date"]
        return f"VL {unit['nr']} · {WEEKDAYS_SHORT[d.weekday()]} {d:%d.%m.}"
    d = unit["session"]
    return f"Übung · {WEEKDAYS_SHORT[d.weekday()]} {d:%d.%m.}"


def session_text(ex: dict) -> str:
    parts = []
    for s in ex["sessions"]:
        when = f"{WEEKDAYS_SHORT[s['date'].weekday()]} {s['date']:%d.%m.}"
        parts.append(f"{s.get('type', 'Übung')} {when}" + (f" {s['start']}" if s.get("start") else ""))
    return " · ".join(parts)


def related_lectures(ex: dict, lecture_list: list[dict]) -> list[dict]:
    return [lec for lec in lecture_list if ex.get("chapter_id") and lec.get("chapter_id") == ex["chapter_id"]]


def related_exercises(lec: dict, exercise_list: list[dict]) -> list[dict]:
    return [ex for ex in exercise_list if lec.get("chapter_id") and ex.get("chapter_id") == lec["chapter_id"]]


# ---------------------------------------------------------------------------
# Inhalte einer Einheit
# ---------------------------------------------------------------------------

def unit_docs(data: dict, unit: dict) -> list[dict]:
    """Dateien dieser Einheit – plus ältere Dateien ohne Einheit, die nur einem Kapitel zugeordnet sind."""
    types = LECTURE_DOC_TYPES if unit["kind"] == "lecture" else EXERCISE_DOC_TYPES
    own = [d for d in data["documents"] if d.get("unit") == unit["id"]]
    legacy = [d for d in data["documents"] if not d.get("unit") and unit.get("chapter_id")
              and d.get("chapter_id") == unit["chapter_id"] and d["doc_type"] in types]
    return own + legacy


def lecture_notes(data: dict, unit_id: str) -> dict:
    notes = data.setdefault("lecture_notes", {}).setdefault(unit_id, {})
    for field in ("text", "emphasized", "briefly", "examples"):
        notes.setdefault(field, "")
    notes.setdefault("images", [])
    return notes


def has_notes(data: dict, unit_id: str) -> bool:
    notes = data.get("lecture_notes", {}).get(unit_id) or {}
    return any((notes.get(k) or "").strip() for k in ("text", "emphasized", "briefly", "examples")) \
        or any(img.get("transcript") for img in notes.get("images", []))


def unit_cards(data: dict, unit: dict) -> list[dict]:
    """Lernkarten einer Einheit (ältere Karten ohne Einheit zählen über ihr Kapitel zur Vorlesung)."""
    return [c for c in data["cards"] if c.get("unit") == unit["id"]
            or (not c.get("unit") and unit["kind"] == "lecture" and unit.get("chapter_id")
                and c.get("chapter_id") == unit["chapter_id"])]


def scope_cards(data: dict, lecture_ids: set[str], exercise_list: list[dict], lecture_list: list[dict]) -> list[dict]:
    """Karten der ausgewählten Vorlesungen inkl. der zugehörigen Übungen."""
    chapters = {lec.get("chapter_id") for lec in lecture_list if lec["id"] in lecture_ids} - {None}
    ex_ids = {ex["id"] for ex in exercise_list if ex.get("chapter_id") in chapters}
    return [c for c in data["cards"] if c.get("unit") in lecture_ids or c.get("unit") in ex_ids
            or (not c.get("unit") and c.get("chapter_id") in chapters)]


# ---------------------------------------------------------------------------
# Automatische Zuordnung beim Bulk-Upload
# ---------------------------------------------------------------------------

_LECTURE_NR = re.compile(r"(?:(?<!\d)(\d{1,2})\.?[\s_\-]*(?:vorlesung|vl\b|lecture))|"
                         r"(?:(?:vorlesung|vl|lecture)[\s_.\-]*0*(\d{1,2})(?!\d))", re.IGNORECASE)
_SHEET_NR = re.compile(r"(?:(?:ü|ue|u)bungsblatt|blatt|sheet|problem[\s_\-]?set)[\s_.\-]*0*(\d{1,2})(?!\d)",
                       re.IGNORECASE)


def guess_unit(path: str, doc_type: str, chapter_id: str | None, lecture_list: list[dict],
               exercise_list: list[dict]) -> str | None:
    name = PurePosixPath(path).name
    if doc_type in EXERCISE_DOC_TYPES:
        sheet = _SHEET_NR.search(name)
        if sheet:
            pattern = re.compile(rf"blatt\s*{int(sheet.group(1))}\b", re.IGNORECASE)
            match = next((ex for ex in exercise_list if pattern.search(ex["title"])), None)
            if match:
                return match["id"]
        match = next((ex for ex in exercise_list if chapter_id and ex.get("chapter_id") == chapter_id), None)
        return match["id"] if match else None
    if doc_type not in LECTURE_DOC_TYPES:
        return None
    number = _LECTURE_NR.search(name)
    if number:
        nr = int(number.group(1) or number.group(2))
        by_topic = next((lec for lec in lecture_list if re.match(rf"{nr}\.\s", lec.get("topic", ""))), None)
        if by_topic:
            return by_topic["id"]
        if 1 <= nr <= len(lecture_list):
            return lecture_list[nr - 1]["id"]
    match = next((lec for lec in lecture_list if chapter_id and lec.get("chapter_id") == chapter_id), None)
    return match["id"] if match else None


def open_tasks(cfg: dict, module_cfg: dict, lecture_list: list[dict], exercise_list: list[dict], state: dict,
               sem_start: date) -> list[dict]:
    """Offene Aufgaben eines Moduls (vor-/nachbereiten, Blatt lösen), nach Frist sortiert."""
    module_id = module_cfg["id"]
    schedule, breaks = get_schedule(cfg), lecture_breaks(cfg)
    tasks = []
    for lec in lecture_list:
        if lec["is_break"]:
            continue
        for field, verb, due in (("vorbereitet", "vorbereiten", planner.prep_due(module_cfg, lec["date"])),
                                 ("nachbereitet", "nachbereiten", planner.review_due(module_cfg, lec["date"]))):
            if due >= sem_start and not state.get(planner.lecture_key(module_id, lec["date"], field)):
                tasks.append({"due": due, "unit": lec, "label": f"Vorlesung {lec['nr']} {verb}",
                              "about": lec["topic"], "tab": 1 if field == "vorbereitet" else 2})
    for ex in exercise_list:
        due = planner.exercise_due(module_cfg, ex, schedule, breaks)
        if due >= sem_start and not state.get(ex["plan_key"]):
            tasks.append({"due": due, "unit": ex, "label": "Übungsblatt lösen", "about": ex["title"], "tab": None})
    tasks.sort(key=lambda t: t["due"])
    return tasks

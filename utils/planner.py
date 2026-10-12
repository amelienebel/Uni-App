"""Wochenübersicht, Lernfahrplan, To-do-Generierung und Fortschrittsberechnung."""

from __future__ import annotations

from datetime import date, datetime, timedelta

from utils import spaced_repetition as sr
from utils.storage import CHAPTER_STATUS_FIELDS, days_until_exam


def monday_of(d: date) -> date:
    return d - timedelta(days=d.weekday())


def semester_week(semester_start: date, d: date) -> int:
    """1-basierte Vorlesungswoche (<= 0: vor Semesterbeginn)."""
    delta = (monday_of(d) - monday_of(semester_start)).days
    return delta // 7 + 1


def chapter_for_week(chapters: list[dict], week: int) -> dict | None:
    """Kapitel, das in der gegebenen Vorlesungswoche behandelt wird (letztes mit week <= Woche)."""
    if week < 1:
        return None
    current = None
    for ch in sorted(chapters, key=lambda c: c.get("week") or 0):
        if (ch.get("week") or 0) <= week:
            current = ch
    return current


def week_events(schedule: list[dict], monday: date) -> list[dict]:
    events = []
    for event in schedule:
        weekday = int(event.get("weekday", 0))
        events.append({**event, "date": monday + timedelta(days=weekday)})
    events.sort(key=lambda e: (e["date"], e.get("start", "")))
    return events


def generate_todos(cfg: dict, modules_data: dict[str, dict], schedule: list[dict], monday: date,
                   semester_start: date, semester_end: date, learning: dict) -> list[dict]:
    """Erzeugt konkrete Aufgaben mit Fristen für die Woche ab `monday`.

    - Vorlesung vorbereiten: fällig `prep_days_before` Tage vor der Vorlesung
    - Vorlesung nachbereiten: fällig `review_days_after` Tage nach der Vorlesung
    - Übungsblatt lösen: fällig am Tag vor der Übung (Stoff der Vorwoche)
    - Spaced-Repetition-Wiederholungen und Klausurvorbereitung je nach Klausurnähe
    Aufgaben mit Kapitelbezug sind direkt mit dem Kapitelstatus verknüpft.
    """
    prep_before = int(learning.get("prep_days_before", 1))
    review_after = int(learning.get("review_days_after", 2))
    week = semester_week(semester_start, monday)
    in_lecture_period = monday_of(semester_start) <= monday <= semester_end
    todos: list[dict] = []
    seen: set[str] = set()

    def add(todo: dict) -> None:
        if todo["key"] not in seen:
            seen.add(todo["key"])
            todos.append(todo)

    for event in week_events(schedule, monday):
        module_id = event.get("module_id")
        if module_id not in modules_data or not in_lecture_period:
            continue
        data = modules_data[module_id]
        if event.get("type") == "Vorlesung":
            chapter = chapter_for_week(data["chapters"], week)
            if not chapter:
                continue
            idx = data["chapters"].index(chapter) + 1
            add({
                "key": f"{module_id}:{chapter['id']}:vorbereitet",
                "module_id": module_id, "chapter_id": chapter["id"], "status_field": "vorbereitet",
                "kind": "Vorbereitung",
                "title": f"Vorlesung vorbereiten – Kap. {idx}: {chapter['title']}",
                "due": event["date"] - timedelta(days=prep_before),
            })
            add({
                "key": f"{module_id}:{chapter['id']}:nachbereitet",
                "module_id": module_id, "chapter_id": chapter["id"], "status_field": "nachbereitet",
                "kind": "Nachbereitung",
                "title": f"Vorlesung nachbereiten – Kap. {idx}: {chapter['title']}",
                "due": event["date"] + timedelta(days=review_after),
            })
        elif event.get("type") in ("Übung", "Tutorium"):
            chapter = chapter_for_week(data["chapters"], week - 1) or chapter_for_week(data["chapters"], week)
            if not chapter:
                continue
            idx = data["chapters"].index(chapter) + 1
            add({
                "key": f"{module_id}:{chapter['id']}:uebung",
                "module_id": module_id, "chapter_id": chapter["id"], "status_field": "uebung",
                "kind": "Übungsblatt",
                "title": f"Übungsblatt lösen – Kap. {idx}: {chapter['title']}",
                "due": event["date"] - timedelta(days=1),
            })

    iso_week = f"{monday.isocalendar()[0]}-W{monday.isocalendar()[1]:02d}"
    for module in cfg["modules"]:
        module_id = module["id"]
        data = modules_data[module_id]
        days = days_until_exam(module_id, monday)
        due_cards = len(sr.due_queue(data["cards"], days, today=monday + timedelta(days=6)))
        if due_cards:
            add({
                "key": f"{module_id}:sr:{iso_week}",
                "module_id": module_id, "chapter_id": None, "status_field": None,
                "kind": "Wiederholung",
                "title": f"Lernkarten wiederholen (ca. {due_cards} fällig bis Sonntag)",
                "due": monday + timedelta(days=6),
            })
        if days is not None and 0 <= days <= 35:
            add({
                "key": f"{module_id}:klausur:{iso_week}",
                "module_id": module_id, "chapter_id": None, "status_field": None,
                "kind": "Klausurvorbereitung",
                "title": f"Altklausur unter Zeitdruck rechnen ({days} Tage bis zur Klausur)",
                "due": monday + timedelta(days=5),
            })

    todos.sort(key=lambda t: (t["due"], t["module_id"]))
    return todos


def todo_done(todo: dict, modules_data: dict[str, dict], todo_state: dict) -> bool:
    if todo.get("status_field"):
        data = modules_data[todo["module_id"]]
        for ch in data["chapters"]:
            if ch["id"] == todo["chapter_id"]:
                return bool(ch["status"].get(todo["status_field"]))
    return bool(todo_state.get(todo["key"]))


def module_progress(module_data: dict) -> dict:
    chapters = module_data["chapters"]
    total = len(chapters) * len(CHAPTER_STATUS_FIELDS)
    done = sum(1 for ch in chapters for key in CHAPTER_STATUS_FIELDS if ch["status"].get(key))
    chapter_share = done / total if total else 0.0
    stats = sr.card_stats(module_data["cards"])
    # Gesamtfortschritt: 70 % Kapitelbearbeitung, 30 % Kartenbeherrschung (falls Karten existieren)
    overall = chapter_share if not stats["total"] else 0.7 * chapter_share + 0.3 * stats["mastery"]
    return {"chapters": chapter_share, "cards": stats["mastery"], "overall": overall,
            "chapters_done": sum(1 for ch in chapters if all(ch["status"].values())), "n_chapters": len(chapters),
            "card_stats": stats}


def study_recommendations(cfg: dict, modules_data: dict[str, dict], today: date) -> list[dict]:
    """Priorisiert die Module für heute: Klausurnähe × offener Stoff + fällige Karten."""
    recs = []
    for module in cfg["modules"]:
        data = modules_data[module["id"]]
        days = days_until_exam(module["id"], today)
        pressure = sr.exam_pressure(days)
        progress = module_progress(data)
        due = len(sr.due_queue(data["cards"], days, today=today))
        score = pressure["weight"] * (1.2 - progress["overall"]) * 10 + due * 0.3
        open_chapters = [ch for ch in data["chapters"] if not all(ch["status"].values())]
        reason = []
        if days is not None and days >= 0:
            reason.append(f"Klausur in {days} Tagen")
        if due:
            reason.append(f"{due} Karten fällig")
        if open_chapters:
            reason.append(f"{len(open_chapters)} Kapitel offen")
        recs.append({"module_id": module["id"], "score": round(score, 1), "pressure": pressure,
                     "reason": ", ".join(reason) or "alles im Plan", "due": due})
    recs.sort(key=lambda r: r["score"], reverse=True)
    return recs


def format_due(d: date, today: date) -> str:
    delta = (d - today).days
    weekday = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"][d.weekday()]
    if delta == 0:
        rel = "heute"
    elif delta == 1:
        rel = "morgen"
    elif delta < 0:
        rel = f"überfällig seit {-delta} T."
    else:
        rel = f"in {delta} T."
    return f"{weekday}, {d:%d.%m.} ({rel})"


def parse_time(value: str) -> datetime | None:
    try:
        return datetime.strptime(value, "%H:%M")
    except (TypeError, ValueError):
        return None

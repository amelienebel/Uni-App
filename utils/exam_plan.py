"""Klausur-Lernplan: verteilt die Wiederholung aller Kapitel, Schwachstellen und Altklausuren auf die Tage
bis zu den Klausuren. Der Plan wird immer ab heute neu berechnet – erledigte Blöcke fallen heraus,
verpasste rutschen automatisch nach hinten.
"""

from __future__ import annotations

import re
from datetime import date, timedelta

from utils.storage import chapter_number, get_exam_date
from utils.weakness import chapter_stats

DEFAULT_START = date(2027, 1, 11)  # erster Montag nach den Weihnachtsferien


def plan_key(module_id: str, task_id: str) -> str:
    return f"plan:{module_id}:{task_id}"


def module_tasks(module: dict, data: dict) -> list[dict]:
    """Alle Lernblöcke eines Moduls in sinnvoller Reihenfolge (ohne den Generalprobe-Block)."""
    tasks = []
    weak = {s["chapter_id"] for s in chapter_stats(data) if s["mastery"] is not None and s["mastery"] < 0.6}
    for ch in data["chapters"]:
        i = chapter_number(data, ch["id"])
        title = re.sub(r"^Kap\.\s*[\d\s,und–-]+:\s*", "", ch["title"])
        tasks.append({"id": f"rev:{ch['id']}", "title": f"Kap. {i} wiederholen: {title}", "chapter_id": ch["id"],
                      "kind": "Wiederholen"})
        if ch["id"] in weak:
            tasks.append({"id": f"weak:{ch['id']}", "title": f"Kap. {i} vertiefen (Schwachstelle)",
                          "chapter_id": ch["id"], "kind": "Schwachstelle"})
    tasks += [{"id": "alt1", "title": "Altklausur 1 unter Zeitdruck rechnen", "chapter_id": None, "kind": "Altklausur"},
              {"id": "alt2", "title": "Altklausur 2 rechnen & Fehler nacharbeiten", "chapter_id": None,
               "kind": "Altklausur"}]
    for task in tasks:
        task["module_id"] = module["id"]
    return tasks


def build_plan(cfg: dict, modules_data: dict[str, dict], state: dict, start: date, today: date,
               weekday_blocks: int = 2, weekend_blocks: int = 3) -> dict:
    """Ergebnis: {"days": [{date, items}], "unplanned": {modul: anzahl}, "progress": {modul: (erledigt, gesamt)}}."""
    exams = {m["id"]: get_exam_date(m["id"]) for m in cfg["modules"]}
    exams = {mid: d for mid, d in exams.items() if d and d >= today}
    begin = max(start, today)
    remaining: dict[str, list[dict]] = {}
    progress: dict[str, tuple[int, int]] = {}
    for module in cfg["modules"]:
        mid = module["id"]
        tasks = module_tasks(module, modules_data[mid])
        final = {"id": "final", "title": "Generalprobe: Formeln, Merksätze & offene Fragen", "chapter_id": None,
                 "kind": "Generalprobe", "module_id": mid}
        done = [t for t in tasks + [final] if state.get(plan_key(mid, t["id"]))]
        progress[mid] = (len(done), len(tasks) + 1)
        if mid in exams:
            remaining[mid] = [t for t in tasks if not state.get(plan_key(mid, t["id"]))]
            if not state.get(plan_key(mid, "final")):
                remaining[mid + ":final"] = [final]

    days = []
    if not exams:
        return {"days": days, "unplanned": {}, "progress": progress}
    day = begin
    last = max(exams.values())
    while day <= last:
        items = []
        exam_today = [mid for mid, d in exams.items() if d == day]
        # Tag vor der Klausur: Generalprobe zuerst
        for mid, d in exams.items():
            if d - timedelta(days=1) == day and remaining.get(mid + ":final"):
                items.append(remaining.pop(mid + ":final")[0])
        capacity = (weekend_blocks if day.weekday() >= 5 else weekday_blocks) - (1 if exam_today else 0)
        while len(items) < capacity:
            best, best_urgency = None, 0.0
            for mid, tasks in remaining.items():
                if mid.endswith(":final") or not tasks or exams[mid] <= day:
                    continue
                days_left = max(1, (exams[mid] - day).days - 1)  # letzter Tag ist für die Generalprobe reserviert
                urgency = len(tasks) / days_left
                if urgency > best_urgency:
                    best, best_urgency = mid, urgency
            if best is None:
                # Alles verteilt: freie Zeit mit Übungsblöcken für die nächsten Klausuren füllen
                upcoming = sorted((d, mid) for mid, d in exams.items() if d > day)
                used = {i["module_id"] for i in items if i["kind"] == "Übung"}
                filler = next((mid for _, mid in upcoming if mid not in used), None)
                if filler is None:
                    break
                items.append({"id": f"extra:{day.isoformat()}", "title": "Übungsblock: Altklausuraufgaben, "
                              "Übungsblätter & fällige Karteikarten", "chapter_id": None, "kind": "Übung",
                              "module_id": filler})
                continue
            items.append(remaining[best].pop(0))
        for mid in exam_today:
            items.insert(0, {"id": "exam", "title": "Klausur", "chapter_id": None, "kind": "Klausur",
                             "module_id": mid})
        days.append({"date": day, "items": items})
        day += timedelta(days=1)
    unplanned = {mid: len(t) for mid, t in remaining.items() if t and not mid.endswith(":final")}
    # Klausur schon heute: Generalprobe direkt heute einplanen
    for mid, tasks in remaining.items():
        if mid.endswith(":final") and tasks and days:
            days[0]["items"].append(tasks[0])
    return {"days": days, "unplanned": unplanned, "progress": progress}

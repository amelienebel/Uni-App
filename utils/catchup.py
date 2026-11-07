"""Aufholplan: Rückstand erkennen und sinnvoll auf die nächsten Tage verteilen.

Reihenfolge:
1. Übungsblätter, deren Besprechung in den nächsten 2 Tagen ist – samt Nacharbeiten/Check der zugehörigen
   Vorlesungen davor.
2. Überfälliges: Module nach Rangfolge (ExRW und I&F, dann Statistik und Mathe, dann VWL), je Modul die älteste
   Vorlesung zuerst, innerhalb einer Vorlesung Nacharbeiten → Check → Übungsblatt → Wochentraining.
3. Was in den nächsten 7 Tagen fällig wird, nach Frist.
Verteilt wird nach dem Zeitbudget je Wochentag (Einstellungen → Lernen).
"""

from __future__ import annotations

from datetime import date, timedelta

from utils import planner, units
from utils.config import get_module
from utils.storage import load_settings, semester_dates

DEFAULT_BUDGET = {0: 120, 1: 240, 2: 360, 3: 120, 4: 240, 5: 240, 6: 240}  # Minuten je Wochentag (Mo = 0)
DEFAULT_RANK = {"rewe": 0, "invfin": 0, "statistik": 1, "mathe": 1, "vwl": 2}
DEFAULT_MINUTES = {1: 60, 2: 30, 3: 180, 4: 20}  # Nacharbeiten, Check, Übungsblatt, Wochentraining
STEP_LABELS = {1: "Nacharbeiten", 2: "Vorlesungs-Check", 3: "Übungsblatt", 4: "Wochentraining"}
HORIZON_DAYS = 7


def budget() -> dict[int, int]:
    stored = load_settings().get("learning", {}).get("budget") or {}
    return {d: int(stored.get(str(d), DEFAULT_BUDGET[d])) for d in range(7)}


def minutes() -> dict[int, int]:
    stored = load_settings().get("learning", {}).get("task_minutes") or {}
    return {s: int(stored.get(str(s), DEFAULT_MINUTES[s])) for s in DEFAULT_MINUTES}


def ranks() -> dict[str, int]:
    return {**DEFAULT_RANK, **(load_settings().get("learning", {}).get("module_rank") or {})}


def open_tasks(cfg: dict, modules_data: dict[str, dict], state: dict, today: date) -> list[dict]:
    sem_start, _ = semester_dates(cfg)
    durations = minutes()
    out = []
    for module in cfg["modules"]:
        module_cfg = get_module(cfg, module["id"])
        data = modules_data[module["id"]]
        lecs, exs = units.all_units(cfg, module_cfg, data)
        for t in units.open_tasks(cfg, module_cfg, lecs, exs, state, sem_start, data):
            if t["due"] > today + timedelta(days=HORIZON_DAYS):
                continue
            unit = t["unit"]
            out.append({**t, "module_id": module["id"], "module": module_cfg["short"],
                        "minutes": durations.get(t["step"], 60),
                        "order_date": (unit["date"] if unit and unit["kind"] == "lecture"
                                       else unit["session"] if unit else t["due"])})
    return out


def prioritize(tasks: list[dict], today: date) -> list[dict]:
    rank = ranks()
    urgent_sheets = [t for t in tasks if t["step"] == 3 and t["unit"] and today <= t["unit"]["session"]
                     <= today + timedelta(days=2)]
    urgent_chapters = {(t["module_id"], t["unit"].get("chapter_id")) for t in urgent_sheets}

    def key(t: dict) -> tuple:
        unit = t["unit"]
        if t in urgent_sheets or (t["step"] in (1, 2) and unit and
                                  (t["module_id"], unit.get("chapter_id")) in urgent_chapters):
            return (0, t["order_date"], t["step"])
        if t["due"] < today:
            return (1, rank.get(t["module_id"], 3), t["order_date"], t["step"])
        return (2, t["due"], t["step"], rank.get(t["module_id"], 3))

    return sorted(tasks, key=key)


def schedule(tasks: list[dict], today: date, days: int = 21) -> list[dict]:
    caps = budget()
    plan = [{"date": today + timedelta(days=i), "items": [], "used": 0,
             "capacity": caps[(today + timedelta(days=i)).weekday()]} for i in range(days)]
    i = 0
    for t in tasks:
        while i < len(plan) - 1 and plan[i]["used"] and plan[i]["used"] + t["minutes"] > plan[i]["capacity"]:
            i += 1
        while i < len(plan) - 1 and plan[i]["capacity"] == 0:
            i += 1
        plan[i]["items"].append(t)
        plan[i]["used"] += t["minutes"]
    return plan


def build(cfg: dict, modules_data: dict[str, dict], state: dict, today: date) -> dict:
    tasks = prioritize(open_tasks(cfg, modules_data, state, today), today)
    overdue = [t for t in tasks if t["due"] < today]
    plan = schedule(tasks, today)
    done_by = None
    if overdue:
        last = overdue[-1]
        done_by = next((d["date"] for d in plan if any(x is last for x in d["items"])), None)
    return {"tasks": tasks, "overdue": overdue, "plan": plan, "caught_up": done_by,
            "overdue_minutes": sum(t["minutes"] for t in overdue)}


def is_enabled() -> bool:
    return planner.LEARNING_V2

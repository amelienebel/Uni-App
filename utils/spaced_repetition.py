"""Spaced Repetition mit FSRS (Free Spaced Repetition Scheduler, wie im aktuellen Anki) – plus Klausurtermin.

FSRS merkt sich pro Karte
    stability  = nach wie vielen Tagen ich die Karte nur noch zu 90 % weiß,
    difficulty = wie schwer mir die Karte fällt (1 … 10).
Daraus folgt, wie wahrscheinlich ich sie heute noch weiß (retrievability). Die nächste Wiederholung kommt,
wenn diese Wahrscheinlichkeit auf die Zielquote fällt.

Vier Bewertungen: 0 = Gar nicht (kommt in derselben Runde wieder), 1 = Etwas, 2 = Gut, 3 = Perfekt.

Klausurtermin:
- Zielquote steigt, je näher die Klausur ist (88 % → 92 % → 95 %); wichtige Karten etwas höher, Randthemen niedriger.
- Endspurt: Würde die nächste Wiederholung erst nach Beginn der letzten FINAL_DAYS Tage liegen, wird sie in diesen
  Endspurt gelegt (verteilt über die Tage) – so kommt jede gelernte Karte kurz vor der Klausur noch einmal dran.
- Neue Karten pro Tag: so viele, dass alle neuen Karten NEW_BUFFER_DAYS Tage vor der Klausur eingeführt sind,
  mindestens aber die Zahl aus den Einstellungen. Wichtige Karten zuerst, Randthemen zuletzt.
"""

from __future__ import annotations

import copy
import math
import zlib
from datetime import date, timedelta

from utils.storage import new_id, now_iso

GRADES = [
    {"value": 0, "label": "Gar nicht"},
    {"value": 1, "label": "Etwas"},
    {"value": 2, "label": "Gut"},
    {"value": 3, "label": "Perfekt"},
]
PRIORITIES = {"high": "wichtig", "normal": "normal", "low": "Randthema"}
_PRIORITY_RANK = {"high": 0, "normal": 1, "low": 2}

# Standard-Parameter von FSRS-5 (aus Millionen Anki-Wiederholungen ermittelt)
W = [0.40255, 1.18385, 3.173, 15.69105, 7.1949, 0.5345, 1.4604, 0.0046, 1.54575, 0.1192, 1.01925,
     1.9395, 0.11, 0.29605, 2.2698, 0.2315, 2.9898, 0.51655, 0.6621]
DECAY = -0.5
FACTOR = 19 / 81
FINAL_DAYS = 4
NEW_BUFFER_DAYS = 7
MASTERED_STABILITY = 21
DEFAULT_NEW_PER_DAY = 15


def new_card(front: str, back: str, source: str = "manuell", chapter_id: str | None = None,
             card_type: str = "basic", **extra) -> dict:
    card = {
        "id": new_id(),
        "front": front.strip(),
        "back": back.strip(),
        "type": card_type,
        "source": source,
        "chapter_id": chapter_id,
        "priority": "normal",
        "keywords": [],
        "explanation": "",
        "section": [],
        "sources": [],
        "needs_review": False,
        "state": "new",
        "stability": None,
        "difficulty": None,
        "interval": 0,
        "reps": 0,
        "lapses": 0,
        "due": date.today().isoformat(),
        "last_review": None,
        "history": [],
        "chat": [],
        "created_at": now_iso(),
    }
    card.update(extra)
    return card


def _upgrade(card: dict) -> dict:
    """Ältere SM-2-Karten (ease/interval) in FSRS-Werte übersetzen – der Lernstand bleibt erhalten."""
    if "state" in card:
        return card
    if card.get("reps", 0) > 0 or card.get("history"):
        card["state"] = "review"
        card["stability"] = float(max(1, card.get("interval", 1)))
        card["difficulty"] = _clamp_d(5 + (2.5 - card.get("ease", 2.5)) * 3)
    else:
        card.update({"state": "new", "stability": None, "difficulty": None})
    card.setdefault("priority", "normal")
    return card


def _clamp_d(d: float) -> float:
    return min(10.0, max(1.0, d))


def _d0(g: int) -> float:
    return _clamp_d(W[4] - math.exp(W[5] * (g - 1)) + 1)


def _next_d(d: float, g: int) -> float:
    delta = -W[6] * (g - 3)
    d = d + delta * (10 - d) / 9
    return _clamp_d(W[7] * _d0(4) + (1 - W[7]) * d)


def _recall_s(d: float, s: float, r: float, g: int) -> float:
    hard = W[15] if g == 2 else 1.0
    easy = W[16] if g == 4 else 1.0
    return s * (math.exp(W[8]) * (11 - d) * s ** -W[9] * (math.exp(W[10] * (1 - r)) - 1) * hard * easy + 1)


def _forget_s(d: float, s: float, r: float) -> float:
    return min(s, W[11] * d ** -W[12] * ((s + 1) ** W[13] - 1) * math.exp(W[14] * (1 - r)))


def _r(elapsed: float, s: float) -> float:
    return (1 + FACTOR * elapsed / s) ** DECAY


def retrievability(card: dict, today: date | None = None) -> float | None:
    """Wahrscheinlichkeit (0–1), dass ich die Karte heute noch weiß; None bei neuen Karten."""
    _upgrade(card)
    if card["state"] == "new" or not card.get("stability") or not card.get("last_review"):
        return None
    today = today or date.today()
    return _r(max(0, (today - date.fromisoformat(card["last_review"])).days), card["stability"])


def target_retention(days_to_exam: int | None, priority: str = "normal") -> float:
    base = 0.88
    if days_to_exam is not None and days_to_exam >= 0:
        base = 0.95 if days_to_exam <= 7 else 0.92 if days_to_exam <= 21 else 0.88
    base += {"high": 0.02, "low": -0.03}.get(priority, 0.0)
    return min(0.97, max(0.80, base))


def _interval(s: float, retention: float) -> int:
    return max(1, round(s / FACTOR * (retention ** (1 / DECAY) - 1)))


def _fit_exam(interval: int, days_to_exam: int | None, card_id: str) -> int:
    """Nächste Wiederholung, die hinter den Endspurt fallen würde, in den Endspurt legen."""
    if days_to_exam is None or days_to_exam <= FINAL_DAYS:
        return interval  # kein Termin, schon im Endspurt oder Klausur vorbei: normal planen
    window_start = days_to_exam - FINAL_DAYS
    if interval <= window_start:
        return interval
    return window_start + zlib.crc32(card_id.encode()) % FINAL_DAYS


def exam_pressure(days_to_exam: int | None) -> dict:
    """Gewicht für die Lernplanung (welches Modul heute wichtiger ist) und eine Beschreibung."""
    if days_to_exam is None or days_to_exam < 0:
        return {"factor": 1.0, "weight": 1.0, "level": "keine", "label": "Kein Klausurtermin"}
    if days_to_exam <= 7:
        return {"factor": 0.4, "weight": 3.0, "level": "kritisch", "label": f"Kritisch ({days_to_exam} T.)"}
    if days_to_exam <= 21:
        return {"factor": 0.6, "weight": 2.2, "level": "hoch", "label": f"Hoch ({days_to_exam} T.)"}
    if days_to_exam <= 45:
        return {"factor": 0.8, "weight": 1.5, "level": "mittel", "label": f"Mittel ({days_to_exam} T.)"}
    return {"factor": 1.0, "weight": 1.0, "level": "niedrig", "label": f"Niedrig ({days_to_exam} T.)"}


def review(card: dict, grade: int, days_to_exam: int | None = None, today: date | None = None) -> dict:
    """Aktualisiert eine Karte nach einer Bewertung (in-place) und gibt sie zurück."""
    today = today or date.today()
    _upgrade(card)
    g = grade + 1  # FSRS zählt 1–4
    was = card["state"]
    if was == "new" or not card.get("stability"):
        s, d = W[g - 1], _d0(g)
    else:
        s, d = card["stability"], card.get("difficulty") or 5.0
        elapsed = (today - date.fromisoformat(card["last_review"])).days if card.get("last_review") else 0
        if elapsed <= 0:  # mehrmals am selben Tag
            s = s * math.exp(W[17] * (g - 3 + W[18]))
        else:
            r = _r(elapsed, s)
            if g == 1:
                s = _forget_s(d, s, r)
                card["lapses"] = card.get("lapses", 0) + 1
            else:
                s = _recall_s(d, s, r, g)
        d = _next_d(d, g)
    s = min(36500.0, max(0.1, s))

    if g == 1 or (was == "new" and g == 2):
        state, interval = ("relearning" if was == "review" else "learning"), 0  # gleich nochmal
    else:
        state = "review"
        interval = _interval(s, target_retention(days_to_exam, card.get("priority", "normal")))
        interval = _fit_exam(interval, days_to_exam, card["id"])

    card.update({
        "state": state,
        "stability": round(s, 4),
        "difficulty": round(d, 4),
        "interval": interval,
        "reps": card.get("reps", 0) + 1,
        "due": (today + timedelta(days=interval)).isoformat(),
        "last_review": today.isoformat(),
    })
    card.setdefault("history", []).append({"date": today.isoformat(), "grade": grade, "interval": interval})
    return card


def preview(card: dict, days_to_exam: int | None = None, today: date | None = None) -> dict[int, int]:
    """Für jede Bewertung: in wie vielen Tagen die Karte wiederkäme (0 = gleich nochmal)."""
    return {g["value"]: review(copy.deepcopy(card), g["value"], days_to_exam, today)["interval"] for g in GRADES}


def interval_label(days: int) -> str:
    if days <= 0:
        return "gleich nochmal"
    if days == 1:
        return "morgen"
    if days < 31:
        return f"in {days} Tagen"
    return f"in {days / 30:.1f} Monaten".replace(".", ",")


def is_new(card: dict) -> bool:
    return _upgrade(card)["state"] == "new"


def is_due(card: dict, today: date | None = None) -> bool:
    """Fällige Wiederholung (neue Karten zählen nicht – die kommen über das Tageskontingent)."""
    today = today or date.today()
    return not is_new(card) and date.fromisoformat(card["due"]) <= today


def introduced_on(cards: list[dict], day: date) -> int:
    return sum(1 for c in cards if c.get("history") and c["history"][0]["date"] == day.isoformat())


def new_per_day(cards: list[dict], days_to_exam: int | None, minimum: int = DEFAULT_NEW_PER_DAY) -> int:
    """Tageskontingent neuer Karten: alle neuen bis NEW_BUFFER_DAYS vor der Klausur, mindestens `minimum`."""
    n_new = sum(1 for c in cards if is_new(c))
    if days_to_exam is None or days_to_exam < 0:
        return min(n_new, minimum)
    days_left = days_to_exam - NEW_BUFFER_DAYS
    if days_left <= 0:
        return n_new
    return min(n_new, max(minimum, math.ceil(n_new / days_left)))


def _new_order(card: dict) -> tuple:
    return _PRIORITY_RANK.get(card.get("priority"), 1), card.get("created_at", "")


def _review_order(card: dict, today: date) -> tuple:
    # zuerst, was ich am ehesten vergessen habe; wichtige Karten bei Gleichstand zuerst
    r = retrievability(card, today)
    return (r if r is not None else 0.0) + 0.05 * _PRIORITY_RANK.get(card.get("priority"), 1), card["due"]


def due_queue(cards: list[dict], days_to_exam: int | None, limit: int | None = None,
              chapter_ids: list[str] | None = None, today: date | None = None,
              new_limit: int | None = None) -> list[dict]:
    """Heutige Runde: fällige Wiederholungen (vergessensgefährdete zuerst), danach neue Karten im Kontingent."""
    today = today or date.today()
    pool = [c for c in cards if not chapter_ids or c.get("chapter_id") in chapter_ids]
    reviews = sorted((c for c in pool if is_due(c, today)), key=lambda c: _review_order(c, today))
    if limit:
        reviews = reviews[:limit]
    if new_limit is None:
        new_limit = max(0, new_per_day(cards, days_to_exam) - introduced_on(cards, today))
    new = sorted((c for c in pool if is_new(c)), key=_new_order)[:new_limit]
    return reviews + new


def daily_plan(cards: list[dict], days_to_exam: int | None, minimum: int = DEFAULT_NEW_PER_DAY,
               today: date | None = None) -> dict:
    """Wie viel heute ansteht: Wiederholungen und neue Karten (Rest des Tageskontingents)."""
    today = today or date.today()
    quota = max(0, new_per_day(cards, days_to_exam, minimum) - introduced_on(cards, today))
    return {"reviews": sum(1 for c in cards if is_due(c, today)),
            "new": min(quota, sum(1 for c in cards if is_new(c))), "quota": quota}


def card_stats(cards: list[dict], today: date | None = None) -> dict:
    today = today or date.today()
    total = len(cards)
    due = sum(1 for c in cards if is_due(c, today))
    new = sum(1 for c in cards if is_new(c))
    mastered = sum(1 for c in cards if not is_new(c) and (c.get("stability") or 0) >= MASTERED_STABILITY)
    learning = total - new - mastered
    return {"total": total, "due": due, "new": new, "learning": max(0, learning), "mastered": mastered,
            "mastery": (mastered / total) if total else 0.0}


def forecast(cards: list[dict], days: int = 14, today: date | None = None) -> list[dict]:
    """Anzahl fälliger Wiederholungen pro Tag für die nächsten Tage (Überfällige zählen heute)."""
    today = today or date.today()
    counts = {today + timedelta(days=i): 0 for i in range(days)}
    for c in cards:
        if is_new(c):
            continue
        due = max(date.fromisoformat(c["due"]), today)
        if due in counts:
            counts[due] += 1
    return [{"Datum": d.strftime("%d.%m."), "Karten": n} for d, n in counts.items()]

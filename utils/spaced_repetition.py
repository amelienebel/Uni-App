"""Spaced Repetition nach dem SuperMemo-2-/Anki-Prinzip – erweitert um Klausurdruck.

Vier Bewertungsstufen steuern das Intervall:
    0 = Gar nicht kann   -> Karte startet von vorn (morgen wieder)
    1 = Etwas kann       -> kleines Wachstum, Leichtigkeitsfaktor sinkt
    2 = Gut kann         -> normales SM-2-Wachstum
    3 = Perfekt kann     -> SM-2-Wachstum plus Bonus

Klausurdruck: Je näher die Prüfung, desto kürzer werden die Intervalle (Faktor)
und desto höher ist die Priorität fälliger Karten. Zusätzlich wird jedes Intervall
so gedeckelt, dass eine Karte vor der Klausur mindestens noch einmal drankommt.
"""

from __future__ import annotations

from datetime import date, timedelta

from utils.storage import new_id, now_iso

GRADES = [
    {"value": 0, "label": "Gar nicht kann", "icon": "🔴"},
    {"value": 1, "label": "Etwas kann", "icon": "🟠"},
    {"value": 2, "label": "Gut kann", "icon": "🟢"},
    {"value": 3, "label": "Perfekt kann", "icon": "💚"},
]
# Abbildung auf die SM-2-Qualitätsskala (0–5)
_QUALITY = {0: 1, 1: 3, 2: 4, 3: 5}
MIN_EASE = 1.3
MASTERED_INTERVAL = 21


def new_card(front: str, back: str, source: str = "manuell", chapter_id: str | None = None,
             card_type: str = "basic") -> dict:
    return {
        "id": new_id(),
        "front": front.strip(),
        "back": back.strip(),
        "type": card_type,  # basic | formula
        "source": source,
        "chapter_id": chapter_id,
        "ease": 2.5,
        "interval": 0,
        "reps": 0,
        "lapses": 0,
        "due": date.today().isoformat(),
        "last_review": None,
        "history": [],
        "chat": [],
        "created_at": now_iso(),
    }


def exam_pressure(days_to_exam: int | None) -> dict:
    """Liefert Intervallfaktor, Prioritätsgewicht und eine Beschreibung."""
    if days_to_exam is None or days_to_exam < 0:
        return {"factor": 1.0, "weight": 1.0, "level": "keine", "label": "⚪ Kein Klausurtermin"}
    if days_to_exam <= 7:
        return {"factor": 0.4, "weight": 3.0, "level": "kritisch", "label": f"🔥 Kritisch ({days_to_exam} T.)"}
    if days_to_exam <= 21:
        return {"factor": 0.6, "weight": 2.2, "level": "hoch", "label": f"🔴 Hoch ({days_to_exam} T.)"}
    if days_to_exam <= 45:
        return {"factor": 0.8, "weight": 1.5, "level": "mittel", "label": f"🟠 Mittel ({days_to_exam} T.)"}
    return {"factor": 1.0, "weight": 1.0, "level": "niedrig", "label": f"🟢 Niedrig ({days_to_exam} T.)"}


def _cap_for_exam(interval: int, days_to_exam: int | None) -> int:
    if days_to_exam is None or days_to_exam < 0:
        return interval
    if days_to_exam <= 2:
        return 1
    # Karte soll vor der Klausur noch mindestens einmal (in der zweiten Hälfte) auftauchen
    return max(1, min(interval, days_to_exam // 2))


def review(card: dict, grade: int, days_to_exam: int | None = None, today: date | None = None) -> dict:
    """Aktualisiert eine Karte nach einer Bewertung (in-place) und gibt sie zurück."""
    today = today or date.today()
    quality = _QUALITY[grade]
    ease = card.get("ease", 2.5)
    interval = card.get("interval", 0)
    reps = card.get("reps", 0)

    if grade == 0:
        reps = 0
        interval = 1
        card["lapses"] = card.get("lapses", 0) + 1
    else:
        reps += 1
        if reps == 1:
            interval = 1 if grade < 3 else 2
        elif reps == 2:
            interval = 3 if grade == 1 else 4 if grade == 2 else 6
        elif grade == 1:
            interval = max(interval + 1, round(interval * 1.2))
        else:
            interval = round(interval * ease * (1.3 if grade == 3 else 1.0))

    ease = ease + (0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02))
    ease = max(MIN_EASE, round(ease, 2))

    pressure = exam_pressure(days_to_exam)
    interval = max(1, round(interval * pressure["factor"]))
    interval = _cap_for_exam(interval, days_to_exam)

    card.update({
        "ease": ease,
        "interval": interval,
        "reps": reps,
        "due": (today + timedelta(days=interval)).isoformat(),
        "last_review": today.isoformat(),
    })
    card.setdefault("history", []).append({"date": today.isoformat(), "grade": grade, "interval": interval})
    return card


def is_due(card: dict, today: date | None = None) -> bool:
    today = today or date.today()
    return date.fromisoformat(card["due"]) <= today


def priority(card: dict, days_to_exam: int | None, today: date | None = None) -> float:
    """Höher = dringender. Kombiniert Überfälligkeit, Schwierigkeit und Klausurnähe."""
    today = today or date.today()
    overdue = (today - date.fromisoformat(card["due"])).days
    urgency = 1.0 + max(0, overdue) * 0.5
    difficulty = (3.0 - card.get("ease", 2.5)) + card.get("lapses", 0) * 0.5
    new_bonus = 0.5 if card.get("reps", 0) == 0 else 0.0
    return round((urgency + difficulty + new_bonus) * exam_pressure(days_to_exam)["weight"], 3)


def due_queue(cards: list[dict], days_to_exam: int | None, limit: int | None = None,
              chapter_ids: list[str] | None = None, today: date | None = None) -> list[dict]:
    today = today or date.today()
    queue = [c for c in cards if is_due(c, today) and (not chapter_ids or c.get("chapter_id") in chapter_ids)]
    queue.sort(key=lambda c: priority(c, days_to_exam, today), reverse=True)
    return queue[:limit] if limit else queue


def card_stats(cards: list[dict], today: date | None = None) -> dict:
    today = today or date.today()
    total = len(cards)
    due = sum(1 for c in cards if is_due(c, today))
    new = sum(1 for c in cards if c.get("reps", 0) == 0)
    mastered = sum(1 for c in cards if c.get("interval", 0) >= MASTERED_INTERVAL
                   or (c.get("reps", 0) >= 3 and c.get("ease", 0) >= 2.5))
    learning = total - new - mastered
    return {"total": total, "due": due, "new": new, "learning": max(0, learning), "mastered": mastered,
            "mastery": (mastered / total) if total else 0.0}


def forecast(cards: list[dict], days: int = 14, today: date | None = None) -> list[dict]:
    """Anzahl fälliger Karten pro Tag für die nächsten Tage (Überfällige zählen heute)."""
    today = today or date.today()
    counts = {today + timedelta(days=i): 0 for i in range(days)}
    for c in cards:
        due = max(date.fromisoformat(c["due"]), today)
        if due in counts:
            counts[due] += 1
    return [{"Datum": d.strftime("%d.%m."), "Karten": n} for d, n in counts.items()]

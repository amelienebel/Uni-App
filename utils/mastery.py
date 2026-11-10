"""Wissensstand je Minithema: Spaced Repetition (FSRS), Schwierigkeitsleiter, Abdeckung, Archiv-Hinweise.

- Jede Antwort im Vorlesungs-Check oder Wochentraining wird mit der Selbstbewertung (schwer/mittel/einfach)
  zu einer FSRS-Bewertung kombiniert: falsch → „Nochmal“, teilweise/schwer → „Schwer“, mittel → „Gut“,
  einfach → „Leicht“. Ein benutzter Tipp drückt eine richtige Antwort auf „Schwer“.
- Leiter je Minithema: Single Choice → Multiple Choice → Freitext. Rechen-Minithemen (Rechenweg, Kopfrechnen)
  enden bei Multiple Choice bzw. Zahl-Eingabe – es werden nie Formeln getippt.
- Alte Karteikarten (Archiv) liefern nur einen HINWEIS (schwach/mittel/sicher): Er beeinflusst Reihenfolge und
  Einstiegsstufe, aber ein Minithema gilt erst als abgefragt/gelernt, wenn es wirklich gefragt wurde.
"""

from __future__ import annotations

from datetime import date, timedelta

from utils import spaced_repetition as sr

LEVELS = ["sc", "mc", "freitext"]
LEVEL_LABELS = {"sc": "Single Choice", "mc": "Multiple Choice", "freitext": "Freitext"}
SELF_GRADES = {"schwer": "Schwer", "mittel": "Mittel", "einfach": "Einfach"}
# Umrechnung der alten 4 Stufen auf die neuen 3: Gar nicht/Etwas → schwer, Gut → mittel, Perfekt → einfach
ARCHIVE_GRADE = {0: "schwer", 1: "schwer", 2: "mittel", 3: "einfach"}
_SELF_VALUE = {"schwer": 0.0, "mittel": 0.5, "einfach": 1.0}
_PRIORITY = {"hoch": "high", "normal": "normal", "niedrig": "low"}
STATUS_ORDER = ["neu", "unsicher", "wird sicher", "sicher"]
STATUS_COLORS = {"neu": "#9AA3AF", "unsicher": "#D6455D", "wird sicher": "#E08A1E", "sicher": "#2E9D5B"}


def top_level(mt: dict) -> str:
    return "mc" if mt.get("kind") in ("rechenweg", "kopfrechnen") else "freitext"


def entry(data: dict, mt_id: str) -> dict:
    e = data.setdefault("mastery", {}).setdefault(mt_id, {})
    e.setdefault("asked", 0)
    e.setdefault("first_asked", None)
    e.setdefault("history", [])
    e.setdefault("exercise_flags", [])
    e.setdefault("fsrs", {"id": mt_id, "state": "new", "stability": None, "difficulty": None, "interval": 0,
                          "reps": 0, "lapses": 0, "due": None, "last_review": None, "history": []})
    return e


def peek(data: dict, mt_id: str) -> dict:
    """Wissensstand lesen, ohne etwas anzulegen."""
    return (data.get("mastery") or {}).get(mt_id) or {"asked": 0, "history": [], "exercise_flags": []}


# ---------------------------------------------------------------------------
# Archiv der Karteikarten
# ---------------------------------------------------------------------------

def card_value(card: dict) -> float | None:
    """0 (schwer) … 1 (einfach) aus den letzten drei Bewertungen einer alten Karte (umgerechnet auf 3 Stufen)."""
    history = card.get("history") or []
    if not history:
        return None
    vals = [_SELF_VALUE[ARCHIVE_GRADE.get(int(h.get("grade", 0)), "schwer")] for h in history[-3:]]
    value = sum(vals) / len(vals)
    if card.get("lapses", 0) >= 2:
        value = min(value, 0.4)
    return value


def archive_hint(data: dict, mt_id: str) -> dict | None:
    ids = [cid for cid, target in (data.get("archive_map") or {}).items() if target == mt_id]
    if not ids:
        return None
    cards = [c for c in data.get("cards", []) if c["id"] in ids]
    values = [v for v in (card_value(c) for c in cards) if v is not None]
    if not values:
        return {"cards": len(cards), "score": None, "label": "nie gelernt"}
    score = sum(values) / len(values)
    label = "schwach" if score < 0.4 else "mittel" if score < 0.75 else "sicher"
    return {"cards": len(cards), "score": round(score, 2), "label": label}


# ---------------------------------------------------------------------------
# Stufe, Status, Abdeckung
# ---------------------------------------------------------------------------

def start_level(data: dict, mt: dict) -> str:
    rating = nacharbeit_rating(data, mt)
    if rating:
        return "mc" if rating == "sicher" else "sc"
    hint = archive_hint(data, mt["id"])
    return "mc" if hint and hint["label"] == "sicher" else "sc"


def current_level(data: dict, mt: dict) -> str:
    e = peek(data, mt["id"])
    level = e.get("level") or start_level(data, mt)
    top = LEVELS.index(top_level(mt))
    return LEVELS[min(LEVELS.index(level), top)]


def retrievability(e: dict, today: date | None = None) -> float | None:
    fsrs = e.get("fsrs")
    if not fsrs or not e.get("asked"):
        return None
    return sr.retrievability(fsrs, today)


def status(data: dict, mt: dict, today: date | None = None) -> str:
    e = peek(data, mt["id"])
    if not e.get("asked"):
        return "neu"
    r = retrievability(e, today) or 0.0
    last = e["history"][-1] if e.get("history") else {}
    if last.get("correct") is False or r < 0.6 or any(f["kind"] == "schlecht" and f.get("open")
                                                      for f in e.get("exercise_flags", [])):
        return "unsicher"
    if current_level(data, mt) == top_level(mt) and r >= 0.85 and e["asked"] >= 2 and last.get("correct") is True:
        return "sicher"
    return "wird sicher"


def score(data: dict, mt: dict, today: date | None = None) -> float:
    """0–1 für Fortschrittsbalken (Stufe × Erinnerungswahrscheinlichkeit)."""
    e = peek(data, mt["id"])
    if not e.get("asked"):
        return 0.0
    top = LEVELS.index(top_level(mt))
    idx = LEVELS.index(current_level(data, mt))
    return round((idx + 1) / (top + 1) * (retrievability(e, today) or 0.5), 3)


def is_due(data: dict, mt: dict, today: date | None = None) -> bool:
    e = peek(data, mt["id"])
    if not e.get("asked"):
        return False
    due = (e.get("fsrs") or {}).get("due")
    return bool(due) and date.fromisoformat(due) <= (today or date.today())


def covered(data: dict, mt: dict) -> bool:
    return bool(peek(data, mt["id"]).get("asked"))


def coverage(data: dict, mts: list[dict]) -> tuple[int, int]:
    return sum(1 for m in mts if covered(data, m)), len(mts)


# ---------------------------------------------------------------------------
# Antwort verbuchen
# ---------------------------------------------------------------------------

def fsrs_grade(correct, self_grade: str, hints_used: int = 0) -> int:
    if correct is False:
        return 0
    if correct == "partial" or self_grade == "schwer":
        return 1
    grade = 3 if self_grade == "einfach" else 2
    return 1 if hints_used else grade


def record(data: dict, mt: dict, correct, self_grade: str, *, source: str, question_id: str | None,
           level_asked: str, hints_used: int = 0, days_to_exam: int | None = None,
           today: date | None = None) -> dict:
    """Antwort + Selbstbewertung zu einem Minithema verbuchen (FSRS, Leiter, Abdeckung)."""
    today = today or date.today()
    e = entry(data, mt["id"])
    fsrs = e["fsrs"]
    fsrs["priority"] = _PRIORITY.get(mt.get("importance"), "normal")
    stable_before = (fsrs.get("stability") or 0) >= 7
    sr.review(fsrs, fsrs_grade(correct, self_grade, hints_used), days_to_exam, today)
    top = LEVELS.index(top_level(mt))
    idx = LEVELS.index(level_asked) if level_asked in LEVELS else 0
    if correct is False:
        idx -= 1
    elif correct is True and self_grade in ("mittel", "einfach") and not hints_used:
        idx += 2 if self_grade == "einfach" and stable_before else 1
    e["level"] = LEVELS[max(0, min(top, idx))]
    e["asked"] += 1
    e["first_asked"] = e["first_asked"] or today.isoformat()
    e["history"].append({"date": today.isoformat(), "source": source, "question_id": question_id,
                         "level": level_asked, "correct": correct, "self": self_grade, "hints": hints_used})
    for flag in e["exercise_flags"]:
        if flag.get("open") and correct is True and self_grade != "schwer":
            flag["open"] = False  # Schwäche aus der Übung gilt nach einer sicheren Antwort als bearbeitet
    nach = e.get("nacharbeit")
    if nach and nach.get("open") and correct is True and self_grade != "schwer":
        nach["open"] = False  # ebenso eine Schwäche aus der Nacharbeit
    return e


def apply_exercise_flag(data: dict, mt: dict, exercise_id: str, kind: str, text: str,
                        today: date | None = None) -> None:
    """Rückmeldung aus der Übung: „schlecht“ → sofort fällig, höchstens Multiple Choice; „gut“ → nur vermerkt."""
    today = today or date.today()
    e = entry(data, mt["id"])
    if any(f["exercise_id"] == exercise_id and f["kind"] == kind and f["text"] == text for f in e["exercise_flags"]):
        return
    e["exercise_flags"].append({"exercise_id": exercise_id, "kind": kind, "text": text, "date": today.isoformat(),
                                "open": kind == "schlecht"})
    if kind == "schlecht":
        if e.get("level") == "freitext":
            e["level"] = "mc"
        if e.get("asked"):
            e["fsrs"]["due"] = today.isoformat()


def has_open_flag(data: dict, mt: dict) -> bool:
    return any(f["kind"] == "schlecht" and f.get("open") for f in peek(data, mt["id"]).get("exercise_flags", []))


def next_due(data: dict, mts: list[dict], today: date | None = None) -> list[dict]:
    today = today or date.today()
    return [m for m in mts if is_due(data, m, today)]


def week_window(today: date) -> tuple[date, date]:
    monday = today - timedelta(days=today.weekday())
    return monday, monday + timedelta(days=6)


# ---------------------------------------------------------------------------
# Nacharbeit (externer Tutor-Chat): Einstufung je Minithema
# ---------------------------------------------------------------------------

NACH_RATINGS = {"sicher": "Sicher", "wackelig": "Wackelig", "unklar": "Nicht verstanden", "offen": "Nicht geschafft"}
NACH_COLORS = {"sicher": "#2E9D5B", "wackelig": "#E08A1E", "unklar": "#D6455D", "offen": "#9AA3AF"}
_NACH_ORDER = ["unklar", "offen", "wackelig", "sicher"]


def apply_nacharbeit(data: dict, mt: dict, rating: str, text: str, practice: str = "",
                     today: date | None = None) -> None:
    """Einstufung aus der Zusammenfassung des Tutor-Chats: sicher → Einstieg Multiple Choice; wackelig / nicht
    verstanden / nicht geschafft → Einstieg Single Choice, bleibt offen bis zu einer sicheren richtigen Antwort.
    Mehrere Zeilen zum selben Minithema: die schwächere Einstufung zählt."""
    today = today or date.today()
    e = entry(data, mt["id"])
    old = e.get("nacharbeit")
    if old and old.get("date") == today.isoformat() and _NACH_ORDER.index(old["rating"]) < _NACH_ORDER.index(rating):
        rating, text = old["rating"], old["text"] + (f" | {text}" if text else "")
    e["nacharbeit"] = {"rating": rating, "text": text, "practice": practice or (old or {}).get("practice", ""),
                       "date": today.isoformat(), "open": rating != "sicher"}
    if rating != "sicher" and e.get("level") == "freitext":
        e["level"] = "mc"


def nacharbeit_rating(data: dict, mt: dict) -> str | None:
    return (peek(data, mt["id"]).get("nacharbeit") or {}).get("rating")


def has_open_nacharbeit(data: dict, mt: dict) -> bool:
    return bool((peek(data, mt["id"]).get("nacharbeit") or {}).get("open"))


def weak_notes(data: dict, mt: dict) -> list[str]:
    """Was beim Nacharbeiten und in der Übung gehakt hat (fließt in neue Fragen und die Korrektur ein)."""
    e = peek(data, mt["id"])
    out = [f["text"] for f in e.get("exercise_flags", []) if f["kind"] == "schlecht" and f.get("open")]
    nach = e.get("nacharbeit") or {}
    if nach.get("open"):
        out.append(f"Nacharbeit ({NACH_RATINGS.get(nach['rating'], '')}): {nach.get('text', '')}".strip())
        if nach.get("practice"):
            out.append(f"Als Nächstes üben: {nach['practice']}")
    return out


def is_problem(data: dict, mt: dict, source: str | None = None) -> bool:
    """Letzte Antwort zum Minithema war falsch, nur teilweise richtig oder „schwer“ (optional nur aus Checks)."""
    hist = [h for h in peek(data, mt["id"]).get("history", []) if source is None or h.get("source") == source]
    if not hist:
        return False
    last_any = peek(data, mt["id"])["history"][-1]
    if last_any is not hist[-1] and last_any.get("correct") is True and last_any.get("self") != "schwer":
        return False  # inzwischen sicher beantwortet
    return hist[-1].get("correct") is not True or hist[-1].get("self") == "schwer"

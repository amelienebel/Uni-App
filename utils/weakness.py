"""Schwachstellen: Wie gut sitzen die Kapitel? Grundlage sind Karteikarten-Bewertungen und korrigierte Quizfragen."""

from __future__ import annotations

from utils.storage import chapter_label


def card_score(card: dict) -> float | None:
    """0 = gar nicht gekonnt … 1 = perfekt (Mittel der letzten drei Bewertungen); None = noch nie abgefragt."""
    history = card.get("history") or []
    if not history:
        return None
    last = [h["grade"] for h in history[-3:]]
    return sum(last) / (3 * len(last))


def is_weak(card: dict) -> bool:
    history = card.get("history") or []
    if not history:
        return False
    return history[-1]["grade"] <= 1 or card.get("lapses", 0) >= 2 or card.get("ease", 2.5) < 2.0


def chapter_stats(data: dict) -> list[dict]:
    """Pro Kapitel: Karten, abgefragte Karten, Beherrschung (0–1), schwache Karten, Quiz-Quote."""
    quiz_points: dict[str, list[int]] = {}
    for quiz in data.get("quizzes", []):
        chapters = quiz.get("chapters") or []
        for result in quiz.get("results", {}).values():
            for cid in chapters:
                entry = quiz_points.setdefault(cid, [0, 0])
                entry[0] += result.get("score", 0)
                entry[1] += result.get("max_score", 0)
    stats = []
    for ch in data["chapters"]:
        cards = [c for c in data["cards"] if c.get("chapter_id") == ch["id"]]
        scores = [s for s in (card_score(c) for c in cards) if s is not None]
        weak = [c for c in cards if is_weak(c)]
        quiz = quiz_points.get(ch["id"])
        quiz_pct = quiz[0] / quiz[1] if quiz and quiz[1] else None
        mastery = sum(scores) / len(scores) if scores else None
        if mastery is not None and quiz_pct is not None:
            mastery = 0.7 * mastery + 0.3 * quiz_pct
        stats.append({"chapter_id": ch["id"], "label": chapter_label(data, ch["id"]), "cards": len(cards),
                      "reviewed": len(scores), "mastery": mastery, "weak_cards": weak, "quiz_pct": quiz_pct})
    return stats


def weakest(data: dict, limit: int = 3) -> list[dict]:
    """Die schwächsten Kapitel mit genügend Daten (mind. 3 abgefragte Karten)."""
    ranked = [s for s in chapter_stats(data) if s["mastery"] is not None and s["reviewed"] >= 3 and s["mastery"] < 0.75]
    ranked.sort(key=lambda s: (s["mastery"], -len(s["weak_cards"])))
    return ranked[:limit]

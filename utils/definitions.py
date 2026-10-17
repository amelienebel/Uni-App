"""Definitionen je Modul: Nachschlagen im Reiter „Definitionen“ – jede Definition ist auch eine Karteikarte."""

from __future__ import annotations

import re

from utils import spaced_repetition as sr
from utils.storage import new_id, now_iso


def _norm(term: str) -> str:
    return re.sub(r"\s+", " ", (term or "").strip().lower())


term_key = _norm  # Schlüssel, über den eine Karte zu ihrer Definition gehört


def card_front(term: str) -> str:
    return f"Was versteht man unter „{term.strip()}“?"


def definitions(data: dict) -> list[dict]:
    return data.setdefault("definitions", [])


def _has_card(data: dict, term: str) -> bool:
    key = _norm(term)
    return any(c.get("definition_term") == key or _norm(c["front"]) == _norm(card_front(term)) for c in data["cards"])


def add_definition(data: dict, term: str, text: str, unit_id: str | None, chapter_id: str | None,
                   source: str = "KI") -> bool:
    """Neue Definition (Duplikate nach Begriff werden übersprungen) – samt passender Karteikarte."""
    term, text = (term or "").strip(), (text or "").strip()
    if not term or not text:
        return False
    if any(_norm(d["term"]) == _norm(term) for d in definitions(data)):
        return False
    definitions(data).append({"id": new_id(), "term": term, "definition": text, "unit": unit_id,
                              "chapter_id": chapter_id, "source": source, "created_at": now_iso()})
    ensure_card(data, term, text, unit_id, chapter_id)
    return True


def ensure_card(data: dict, term: str, text: str, unit_id: str | None, chapter_id: str | None) -> None:
    if _has_card(data, term):
        return
    card = sr.new_card(card_front(term), text, source="Definition", chapter_id=chapter_id)
    card["unit"] = unit_id
    card["definition_term"] = _norm(term)
    data["cards"].append(card)


def update_definition(data: dict, def_id: str, term: str, text: str) -> None:
    for d in definitions(data):
        if d["id"] == def_id:
            old = _norm(d["term"])
            d.update({"term": term.strip(), "definition": text.strip()})
            for c in data["cards"]:  # zugehörige Karte mitziehen
                if c.get("definition_term") == old:
                    c.update({"front": card_front(term), "back": text.strip(), "definition_term": _norm(term)})


def delete_definition(data: dict, def_id: str) -> None:
    data["definitions"] = [d for d in definitions(data) if d["id"] != def_id]

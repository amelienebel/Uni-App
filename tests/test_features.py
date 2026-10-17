"""Lernzentrum (Focus Mode, Zurück zur vorigen Karte), Zurück-Button der Navigation, Vorbereitung und Quiz."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"


@pytest.fixture(autouse=True)
def clean_data():
    def content():
        return [p for p in DATA.iterdir() if not p.name.startswith(".")] if DATA.exists() else []

    was_empty = not content()
    yield
    if was_empty:
        for path in content():
            shutil.rmtree(path) if path.is_dir() else path.unlink()
        from utils import storage

        storage.reload_all()


def _run(at: AppTest) -> AppTest:
    at.run(timeout=120)
    assert not at.exception, [e.message for e in at.exception]
    return at


def _button(at: AppTest, label: str):
    return next(b for b in at.button if b.label.startswith(label))


def _add_cards(n: int = 3) -> list[dict]:
    from utils import spaced_repetition as sr
    from utils import storage, units
    from utils.config import get_module, load_config

    cfg = load_config()
    data = storage.load_module("mathe")
    lecs, _ = units.all_units(cfg, get_module(cfg, "mathe"), data)
    cards = []
    for i in range(n):
        card = sr.new_card(f"Frage {i}?", f"- Antwort {i}", keywords=[f"Antwort {i}"], explanation="Weil …")
        card["unit"] = lecs[0]["id"]
        data["cards"].append(card)
        cards.append(card)
    storage.save_module("mathe")
    return cards


def test_cards_center_focus_session_and_back():
    from views.common import PAGES

    _add_cards()
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=120)
    at.session_state["nav"] = PAGES["cards"]
    _run(at)
    assert any("Lernzentrum" in t.value for t in at.title)
    _button(at, "Jetzt lernen").click()
    _run(at)
    assert at.session_state["cc_session"]["queue"]
    assert not at.sidebar.button  # Focus Mode: keine Seitenleiste
    first = at.session_state["cc_session"]["queue"][0][1]
    _button(at, "Auflösen").click()
    _run(at)
    _button(at, "Perfekt").click()
    _run(at)
    sess = at.session_state["cc_session"]
    assert len(sess["done"]) == 1 and sess["done"][0]["cid"] == first
    # Zurück zur vorigen Karte und Bewertung ändern
    at.button(key="cc_back").click()
    _run(at)
    assert at.session_state["cc_session"]["view"] == 0
    _button(at, "Gar nicht").click()
    _run(at)
    sess = at.session_state["cc_session"]
    assert sess["done"][0]["grade"] == 0 and [m for m, c in sess["queue"]].count("mathe") == len(sess["queue"])
    assert any(c == first for _, c in sess["queue"])  # „Gar nicht“ kommt in dieser Runde wieder
    card = next(c for c in at.session_state["_module_mathe"]["cards"] if c["id"] == first)
    assert card["interval"] == 0 and card["reps"] == 1
    at.button(key="cc_forward").click()
    _run(at)
    at.button(key="cc_end").click()
    _run(at)
    assert "cc_session" not in at.session_state and at.sidebar.button


def test_back_button_restores_previous_view():
    from views.common import PAGES

    at = _run(AppTest.from_file(str(ROOT / "app.py"), default_timeout=120))
    assert at.button(key="nav_back_btn").disabled
    at.sidebar.button(key="navpage_week").click()
    _run(at)
    at.sidebar.button(key="navmod_statistik").click()
    _run(at)
    at.button(key="nav_back_btn").click()
    _run(at)
    assert at.session_state["nav"] == PAGES["week"]
    at.button(key="nav_back_btn").click()
    _run(at)
    assert at.session_state["nav"] == PAGES["today"]


def test_settings_contains_export_and_backup():
    from views.common import PAGES

    assert "export" not in PAGES and PAGES["week"].endswith("Wochenübersicht")
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=120)
    at.session_state["nav"] = PAGES["settings"]
    _run(at)
    labels = [s.value for s in at.subheader]
    assert "Vollständiges Backup" in labels and any("exportieren" in v for v in labels)


def test_prep_and_quiz_formats(monkeypatch):
    from utils import ai, learning, storage, units
    from utils.config import exam_format, get_module, load_config
    from views.module_tabs import exams

    cfg = load_config()
    assert exam_format(get_module(cfg, "mathe"))["type"] == "mc_multi"
    assert exam_format(get_module(cfg, "rewe"))["type"] == "sc4"
    assert exam_format(get_module(cfg, "statistik"))["type"] == "open"
    assert exam_format(get_module(cfg, "vwl"))["type"] == "mixed"

    data = storage.load_module("mathe")
    lecs, _ = units.all_units(cfg, get_module(cfg, "mathe"), data)
    doc = {"id": "d1", "filename": "VL1.pdf", "doc_type": "folien", "unit": lecs[0]["id"], "kind": "pdf",
           "figure_pages": []}
    data["documents"].append(doc)
    monkeypatch.setattr(ai, "is_available", lambda: True)
    monkeypatch.setattr(learning, "get_document_text", lambda _doc, label="Seite": "--- Folie 1 ---\nMatrix")
    seen = {}

    def fake_json(prompt, schema, **kw):
        seen.update(prompt=prompt, task=kw.get("task"))
        return {"must_watch": [{"slides": "12–15", "topic": "Determinante", "why": "Herleitung"}],
                "concept_table": [{"slides": "3", "term": "Matrix", "short": "Zahlenschema", "watch_out": "m×n"}],
                "summary": "- **Folie 1–3** · Matrizen", "formulas": [],
                "check_questions": [{"question": "Was ist eine Matrix?", "answer": "Schema"}]}

    monkeypatch.setattr(ai, "complete_json", fake_json)
    learning.run_analysis(cfg, "mathe", doc, visual=False)
    assert seen["task"] == "summary" and "Foliennummer" in seen["prompt"]
    assert doc["analysis"]["important_slides"][0]["page"] == 12
    assert doc["analysis"]["key_concepts"] == [{"term": "Matrix", "explanation": "Zahlenschema"}]
    assert exams.correct_indices({"correct_index": 2}) == [2]
    assert exams.correct_indices({"correct_indices": [3, 0]}) == [0, 3]
    data["quizzes"].append({"id": "q1", "created_at": "2026-10-17T10:00", "chapters": [], "results": {},
                            "scope": "main", "questions": [
                                {"type": "mc_multi", "operator": "", "question": "Welche stimmen?",
                                 "options": ["A", "B", "C", "D", "E"], "correct_indices": [0, 2],
                                 "explanation": "", "sample_answer": "", "points": 2}]})
    storage.save_module("mathe")

    from views.common import PAGES

    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=120)
    at.session_state["nav"] = PAGES["module"]
    at.session_state["nav_module"] = "mathe"
    at.session_state["unit_mathe"] = lecs[0]["id"]
    _run(at)
    assert any("Must-Watch" in m.value for m in at.markdown)
    assert any("| Folie | Kernbegriff / Formel" in m.value for m in at.markdown)

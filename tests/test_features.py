"""Karteikarten (Focus Mode, Zurück zur vorigen Karte), Zurück-Button der Navigation, Vorbereitung und Quiz."""

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
    assert any("Karteikarten" in t.value for t in at.title)
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
    assert exam_format(get_module(cfg, "vwl"))["type"] == "open"

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
                "quiz": [{"type": "mc_multi", "question": "Was ist eine Matrix?", "options": list("ABCDE"),
                          "correct_indices": [1], "explanation": "Folie 3", "slides": "3"}]}

    monkeypatch.setattr(ai, "complete_json", fake_json)
    learning.run_analysis(cfg, "mathe", doc, visual=False)
    assert seen["task"] == "summary" and "Foliennummer" in seen["prompt"]
    assert "genau 5 Quizfragen" in seen["prompt"] and '"mc_multi", genau 5 Optionen' in seen["prompt"]
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
    assert any("Was ist eine Matrix?" in m.value for m in at.markdown)  # Quiz in der Vorbereitung


def test_figures_first_then_prep(monkeypatch):
    """Mit Abbildungen entsteht die Vorbereitung erst, wenn entschieden ist, welche Seiten genau gelesen werden."""
    from utils import learning, storage, units
    from utils.config import get_module, load_config
    from views.common import PAGES

    cfg = load_config()
    data = storage.load_module("mathe")
    lecs, _ = units.all_units(cfg, get_module(cfg, "mathe"), data)
    doc = {"id": "d2", "filename": "VL1.pdf", "doc_type": "folien", "unit": lecs[0]["id"], "kind": "pdf",
           "figure_pages": [2, 5], "path": "x.pdf", "n_pages": 6}
    data["documents"].append(doc)
    storage.save_module("mathe")
    assert learning.pending_figures(doc) == [2, 5]
    calls = []
    monkeypatch.setattr(learning, "run_analysis", lambda *a, **k: calls.append(1) or "ok")
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=120)
    at.session_state["nav"] = PAGES["module"]
    at.session_state["nav_module"] = "mathe"
    at.session_state["unit_mathe"] = lecs[0]["id"]
    _run(at)
    assert any("kann ich die Abbildungen nicht sehen" in m.value for m in at.markdown)
    assert not any(b.label == "Vorbereitung erstellen" for b in at.button)
    assert at.multiselect(key="exsel_d2").value == [2, 5]  # auch im Reiter Lernen wählbar
    at.button(key="figno_d2").click()
    _run(at)
    assert at.session_state["_module_mathe"]["documents"][-1]["skipped_figures"] == [2, 5]


def test_exact_read_after_lecture_without_prep(monkeypatch):
    """Nach der Vorlesung im Reiter Lernen Seiten genau lesen – ohne dass eine Vorbereitung entsteht."""
    from utils import ai, learning, storage, units
    from utils.config import get_module, load_config
    from views.common import PAGES
    from views.module_tabs import lecture_page

    cfg = load_config()
    data = storage.load_module("mathe")
    lecs, _ = units.all_units(cfg, get_module(cfg, "mathe"), data)
    doc = {"id": "d3", "filename": "VL2.pdf", "doc_type": "folien", "unit": lecs[1]["id"], "kind": "pdf",
           "figure_pages": [3], "path": "x.pdf", "n_pages": 4}
    data["documents"].append(doc)
    storage.save_module("mathe")
    calls = []
    monkeypatch.setattr(lecture_page, "read_pages_visual", lambda *a, **k: calls.append((a[3], k)) or "ok")
    monkeypatch.setattr(learning, "run_analysis", lambda *a, **k: calls.append("prep") or "ok")
    monkeypatch.setattr(ai, "is_available", lambda: True)
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=120)
    at.session_state["nav"] = PAGES["module"]
    at.session_state["nav_module"] = "mathe"
    at.session_state["unit_mathe"] = lecs[1]["id"]
    _run(at)
    at.multiselect(key="exsel_d3").select(1)
    at.button(key="exgo_d3").click()
    _run(at)
    assert [(sorted(p), k) for p, k in calls] == [([1, 3], {"update_prep": False})]


def test_exercise_deadlines_and_next_session():
    from datetime import date

    from utils import planner
    from utils.config import get_module, load_config
    from utils.storage import get_schedule, lecture_breaks

    cfg = load_config()
    schedule, breaks = get_schedule(cfg), lecture_breaks(cfg)
    for mid, weekday in (("mathe", 5), ("statistik", 5), ("invfin", 2)):
        module = get_module(cfg, mid)
        for ex in planner.exercises_of(module)[1:4]:
            assert planner.exercise_due(module, ex, schedule, breaks).weekday() == weekday, (mid, ex["title"])
    nxt = planner.next_session(cfg, get_module(cfg, "mathe"), schedule, date(2026, 10, 17))
    assert nxt["date"].weekday() == 0


def test_sidebar_without_module_page_and_custom_todos():
    from views.common import PAGES

    at = _run(AppTest.from_file(str(ROOT / "app.py"), default_timeout=120))
    keys = [b.key for b in at.sidebar.button]
    assert "navpage_module" not in keys and "navmod_mathe" in keys and "navpage_quiz" in keys
    at.text_input(key="today_new_title").input("Bücher zurückgeben")
    at.button(key="today_new_add").click()
    _run(at)
    assert any("Bücher zurückgeben" in b.label for b in at.button)
    todo = at.session_state["_todos"]["_custom"][0]
    at.session_state["nav"] = PAGES["week"]
    _run(at)
    assert any("Bücher zurückgeben" in b.label for b in at.button)
    at.session_state["nav"] = PAGES["today"]
    _run(at)
    at.button(key=f"del_today_custom:{todo['id']}").click()
    _run(at)
    assert not at.session_state["_todos"]["_custom"]


def test_cards_browse_filter_delete_and_feedback(monkeypatch):
    from utils import ai, learning
    from views.cards_center import is_weak
    from views.common import PAGES

    cards = _add_cards(3)
    from utils import spaced_repetition as sr

    sr.review(cards[0], 0)
    from utils import storage

    storage.save_module("mathe")
    assert is_weak(cards[0]) and not is_weak(cards[1])
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=120)
    at.session_state["nav"] = PAGES["cards"]
    _run(at)
    at.selectbox(key="cb_filter").select("weak")
    _run(at)
    assert _button(at, "Diese Karten lernen").label.endswith("(1)")
    at.button(key=f"cbdel_{cards[0]['id']}").click()
    _run(at)
    assert len(at.session_state["_module_mathe"]["cards"]) == 2

    def fake_json(prompt, schema, **kw):
        assert "kürzer" in prompt
        return {"front": "Neue Frage?", "answer": ["Neu"], "explanation": "E", "keywords": ["Neu"]}

    monkeypatch.setattr(ai, "is_available", lambda: True)
    monkeypatch.setattr(ai, "complete_json", fake_json)
    card = at.session_state["_module_mathe"]["cards"][0]
    learning.rewrite_card("mathe", card, "Antwort kürzer")
    assert card["front"] == "Neue Frage?" and card["back"] == "- Neu" and card["previous"]["front"].startswith("Frage")
    learning.undo_rewrite("mathe", card)
    assert card["front"].startswith("Frage") and "previous" not in card


def test_quiz_center_focus_session():
    from utils import storage
    from views.common import PAGES
    from views.module_tabs import exams

    data = storage.load_module("rewe")
    quiz = exams.save_quiz("rewe", data, [
        {"type": "mc", "operator": "", "question": "Was ist richtig?", "options": ["A", "B", "C", "D"],
         "correct_indices": [2], "explanation": "Weil C.", "sample_answer": "", "points": 1},
        {"type": "mc_multi", "operator": "", "question": "Welche stimmen?", "options": list("ABCDE"),
         "correct_indices": [0, 1], "explanation": "", "sample_answer": "", "points": 1}], [], "center", "VL 1")
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=120)
    at.session_state["nav"] = PAGES["quiz"]
    _run(at)
    at.button(key=f"qz_again_{quiz['id']}").click()
    _run(at)
    assert not at.sidebar.button  # Focus Mode
    at.radio(key=f"qz_{quiz['id']}_0").set_value(2)
    at.button(key=f"qz_{quiz['id']}_0_check").click()
    _run(at)
    assert at.success and any("Mehr Infos" in e.label for e in at.expander)
    at.button(key="qz_next").click()
    _run(at)
    at.checkbox(key=f"qz_{quiz['id']}_1_0").check()
    at.button(key=f"qz_{quiz['id']}_1_check").click()
    _run(at)
    assert at.error  # B fehlt
    at.button(key="qz_next").click()
    _run(at)
    assert at.session_state["_module_rewe"]["quizzes"][-1]["last_score"] == [1, 2]
    at.button(key="qz_finish").click()
    _run(at)
    assert at.sidebar.button


def test_formula_sheet_selection():
    from utils import storage
    from views.common import PAGES

    storage.add_formulas("invfin", [{"name": "Barwert", "latex": "PV = \\frac{C}{(1+r)^t}", "explanation": ""},
                                    {"name": "Kapitalwert", "latex": "NPV = -I_0 + PV", "explanation": ""}], "manuell")
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=120)
    at.session_state["nav"] = PAGES["formulas"]
    _run(at)
    assert at.title[0].value.endswith(": Formelsammlung")
    at.toggle(key="fs_choose").set_value(True)
    _run(at)
    barwert = next(f for f in at.session_state["_module_invfin"]["formulas"] if f["name"] == "Barwert")
    at.checkbox(key=f"fs_sel_{barwert['id']}").uncheck()
    _run(at)
    assert barwert["in_sheet"] is False or not next(
        f for f in at.session_state["_module_invfin"]["formulas"] if f["name"] == "Barwert")["in_sheet"]
    at.toggle(key="fs_choose").set_value(False)
    _run(at)
    shown = [m.value for m in at.markdown]
    assert any("Kapitalwert" in v for v in shown) and not any("Barwert" in v for v in shown)


def _script_pdf() -> bytes:
    import io

    from reportlab.pdfgen import canvas

    pages = [["Inhalt", "1.1 Einleitung ..... 2", "1.2 Bilanz ..... 3", "1.3 GuV ..... 3", "1.4 Anhang ..... 4",
              "1.5 Lagebericht ..... 5", "2 Jahresabschluss ..... 6"],
             ["1 Rechnungswesen als Sprache", "1.1 Einleitung", "Text"], ["1.2 Bilanz", "Aktiva", "1.3 GuV", "Ertrag"],
             ["1.4 Anhang", "Erläuterungen"], ["1.5 Lagebericht", "Lage"], ["2 Jahresabschluss", "2.1 Grundlagen"]]
    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    for lines in pages:
        for i, line in enumerate(lines):
            c.drawString(72, 750 - 20 * i, line)
        c.showPage()
    c.save()
    return buf.getvalue()


def test_script_split_and_prep(monkeypatch):
    """Ganzes Skript → Abschnitte je Vorlesung (aus „Skript 1.1–1.4“) → fließt in die Vorbereitung der Folien ein."""
    from utils import ai, learning, script, storage, units
    from utils.config import get_module, load_config
    from utils.pdf_parser import extract_pdf

    assert script.sections_from_topic("Rechnungswesen I – Skript 1.1–1.4") == ("1.1", "1.4")
    assert script.sections_from_topic("Unternehmensanalyse – Skript Abschnitt 3") == ("3", "3")
    assert script.sections_from_topic("Grundlagen Buchungstechnik (Baaken)") is None
    content = _script_pdf()
    sections, total = script.detect_sections(content, extract_pdf(content)["pages"])
    assert [s["nr"] for s in sections][:3] == ["1", "1.1", "1.2"] and total == 6
    assert script.page_range(sections, "1.1", "1.4", total) == (2, 5)
    assert script.page_range(sections, "2", "2", total) == (6, 6)

    cfg = load_config()
    module = get_module(cfg, "rewe")
    lecs = units.lectures(cfg, module)
    rows = script.proposal(lecs, sections, total)
    assert rows[0]["unit"] == lecs[0]["id"] and rows[0]["sections"] == "1.1–1.4" and rows[0]["start"] == 2
    assert script.split_script("rewe", "Skript.pdf", content, rows[:1], {lecs[0]["id"]: "k1"}) == 1
    data = storage.load_module("rewe")
    part = next(d for d in data["documents"] if d.get("script_split"))
    assert part["unit"] == lecs[0]["id"] and part["n_pages"] == 4 and part["script_pages"] == "2–5"
    assert script.split_script("rewe", "Skript.pdf", content, rows[:1], {}) == 1  # ersetzt, nicht doppelt
    assert sum(1 for d in storage.load_module("rewe")["documents"] if d.get("script_split")) == 1

    data = storage.load_module("rewe")
    doc = {"id": "f1", "filename": "VL1.pdf", "doc_type": "folien", "unit": lecs[0]["id"], "kind": "pdf",
           "figure_pages": []}
    data["documents"].append(doc)
    monkeypatch.setattr(ai, "is_available", lambda: True)
    seen = {}

    def fake_json(prompt, schema, **kw):
        seen["prompt"] = prompt
        return {"must_watch": [], "concept_table": [], "summary": "", "formulas": [], "quiz": []}

    monkeypatch.setattr(ai, "complete_json", fake_json)
    learning.run_analysis(cfg, "rewe", doc, visual=False)
    assert "--- Skript S. 2 ---" in seen["prompt"] and "Bilanz" in seen["prompt"] and doc["analysis"]["with_script"]
    learning.run_analysis(cfg, "rewe", next(d for d in data["documents"] if d.get("script_split")))
    assert "keine Folien" in seen["prompt"]

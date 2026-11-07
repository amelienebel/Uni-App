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


@pytest.mark.usefixtures("old_system")
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
    from utils import ai, learning, planner, storage, units

    monkeypatch.setattr(planner, "PREP_ENABLED", True)  # Vorbereiten ist abgeschaltet, der Code bleibt getestet
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


@pytest.mark.usefixtures("old_system")
def test_figures_first_then_prep(monkeypatch):
    """Mit Abbildungen entsteht die Vorbereitung erst, wenn entschieden ist, welche Seiten genau gelesen werden."""
    from utils import learning, planner, storage, units

    monkeypatch.setattr(planner, "PREP_ENABLED", True)
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


@pytest.mark.usefixtures("old_system")
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


@pytest.mark.usefixtures("old_system")
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
        return {"cards": [{"front": "Neue Frage?", "answer": ["Neu"], "explanation": "E", "keywords": ["Neu"]}]}

    monkeypatch.setattr(ai, "is_available", lambda: True)
    monkeypatch.setattr(ai, "complete_json", fake_json)
    card = at.session_state["_module_mathe"]["cards"][0]
    learning.rewrite_card("mathe", card, "Antwort kürzer")
    assert card["front"] == "Neue Frage?" and card["back"] == "- Neu" and card["previous"]["front"].startswith("Frage")
    learning.undo_rewrite("mathe", card)
    assert card["front"].startswith("Frage") and "previous" not in card

    # Feedback „fragt zu viel“ → auf zwei Karten aufteilen, Rückgängig entfernt die zweite wieder
    monkeypatch.setattr(ai, "complete_json", lambda *a, **k: {"cards": [
        {"front": "Teil 1?", "answer": ["A"], "explanation": "", "keywords": ["A"]},
        {"front": "Teil 2?", "answer": ["B"], "explanation": "", "keywords": ["B"]}]})
    assert learning.rewrite_card("mathe", card, "Antwort kürzer, auf zwei Karten") == 2
    assert card["front"] == "Teil 1?" and "Teil 2?" in [c["front"] for c in storage.load_module("mathe")["cards"]]
    learning.undo_rewrite("mathe", card)
    assert "Teil 2?" not in [c["front"] for c in storage.load_module("mathe")["cards"]]


@pytest.mark.usefixtures("old_system")
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


def test_no_formula_sheet():
    """Formelsammlung ist entfernt: keine Seite in der Navigation, kein Formel-Schritt in der Nachbereitung."""
    from views.common import MODULE_TABS, PAGES

    assert "formulas" not in PAGES and not any("Formel" in t for t in MODULE_TABS)

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


@pytest.mark.usefixtures("old_system")
def test_review_steps_without_prep(monkeypatch):
    """Ohne Vorbereitung: kein Reiter/To-do „vorbereiten“; Nachbereitung mit Karten durchsehen, ohne Formelschritt."""
    from datetime import date

    from utils import planner, storage, units
    from utils.config import get_module, load_config
    from views.common import PAGES, lecture_tabs

    assert not planner.PREP_ENABLED and not any("Vorbereiten" in t for t in lecture_tabs())
    cfg = load_config()
    mathe = get_module(cfg, "mathe")
    data = storage.load_module("mathe")
    lecs, exs = units.all_units(cfg, mathe, data)
    self_study = next(lec for lec in lecs if lec.get("self_study"))
    assert self_study["chapter_id"] == "e3" and self_study["nr"] == 3
    tasks = units.open_tasks(cfg, mathe, lecs, exs, {}, date(2026, 10, 1))
    assert tasks and not any("vorbereiten" in t["label"] for t in tasks)

    lec = lecs[0]
    _add_cards(2)
    units.lecture_notes(data, lec["id"])["text"] = "Formel $a^2+b^2=c^2$"
    storage.save_module("mathe")

    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=120)
    at.session_state["nav"] = PAGES["module"]
    at.session_state["nav_module"] = "mathe"
    at.session_state["unit_mathe"] = lec["id"]
    _run(at)
    assert any("Karte 1 von 2" in m.value for m in at.markdown)
    assert not any("Formelsammlung" in m.value for m in at.markdown)
    assert not any("Mitschrift auf Papier" in e.label for e in at.expander)
    at.button(key=f"cvnext_{lec['id']}").click()
    _run(at)
    assert any("Karte 2 von 2" in m.value for m in at.markdown)


def test_rooms_exam_format_and_exercise_page():
    """Mathe-Tutorium in M 110, I&F mit freien Aufgaben; Übungsseite ohne eigene Lösung/Karten, Abhak-Knopf."""
    from utils import storage, units
    from utils.config import exam_format, get_module, load_config
    from views.common import PAGES

    cfg = load_config()
    tut = next(e for e in get_module(cfg, "mathe")["schedule"] if e["type"] == "Tutorium")
    assert "M 110" in tut["room"]
    assert exam_format(get_module(cfg, "invfin"))["type"] == "open"
    settings = storage.load_settings()
    settings["schedule"] = [{"module_id": "mathe", "type": "Tutorium", "weekday": 0, "start": "14:00", "end": "16:00",
                             "room": "Amalienstraße 73a – Raum 220"}]
    assert "M 110" in storage.get_schedule(cfg)[0]["room"]
    settings["schedule"] = []

    data = storage.load_module("mathe")
    _, exs = units.all_units(cfg, get_module(cfg, "mathe"), data)
    ex = exs[1]
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=120)
    at.session_state["nav"] = PAGES["module"]
    at.session_state["nav_module"] = "mathe"
    at.session_state["unit_mathe"] = ex["id"]
    _run(at)
    assert not any("Meine Lösung" in m.value or "Karteikarten zu" in m.value for m in at.markdown)
    wkey = f"exdone_mathe_{ex['id']}"
    at.button(key=f"btn_{wkey}").click()
    _run(at)
    assert at.session_state["_todos"].get(ex["plan_key"]) is True
    at.button(key=f"btn_{wkey}").click()
    _run(at)
    assert at.session_state["_todos"].get(ex["plan_key"]) is False


@pytest.mark.usefixtures("old_system")
def test_priority_picker_in_focus_mode():
    from views.common import PAGES

    cards = _add_cards(1)
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=120)
    at.session_state["nav"] = PAGES["cards"]
    _run(at)
    _button(at, "Jetzt lernen").click()
    _run(at)
    picker = next(b for b in at.button_group if b.key and "_prio_" in b.key)
    picker.set_value("low")
    _run(at)
    card = next(c for c in at.session_state["_module_mathe"]["cards"] if c["id"] == cards[0]["id"])
    assert card["priority"] == "low"


@pytest.mark.usefixtures("old_system")
def test_exam_tasks_only_for_held_lectures(monkeypatch):
    from utils import ai, exam_tasks, storage, units
    from utils.config import get_module, load_config
    from views.common import PAGES

    cfg = load_config()
    data = storage.load_module("invfin")
    lecs, _ = units.all_units(cfg, get_module(cfg, "invfin"), data)
    data["documents"].append({"id": "ak1", "filename": "Klausur WS24.pdf", "doc_type": "altklausur", "unit": None,
                              "n_pages": 1, "n_chars": 10})
    seen = {}

    def fake_json(prompt, schema, **kw):
        seen["prompt"] = prompt
        return {"tasks": [
            {"nr": "1", "question": "Berechnen Sie den Kapitalwert.", "points": 10, "operator": "Berechnen Sie",
             "type": "freitext", "options": [], "correct_indices": [], "lectures": [lecs[0]["nr"]],
             "sample_answer": "NPV = …", "explanation": "Abzinsen"},
            {"nr": "2", "question": "Erläutern Sie das CAPM.", "points": 8, "operator": "Erläutern Sie",
             "type": "freitext", "options": [], "correct_indices": [], "lectures": [lecs[-1]["nr"]],
             "sample_answer": "…", "explanation": ""}]}

    monkeypatch.setattr(ai, "complete_json", fake_json)
    monkeypatch.setattr(exam_tasks, "get_document_text", lambda *a, **k: "Aufgabe 1 …")
    assert exam_tasks.extract_tasks(cfg, "invfin", data["documents"][-1]) == 2
    assert f"{lecs[0]['nr']}: {lecs[0]['topic']}" in seen["prompt"]
    found = exam_tasks.tasks_for(storage.load_module("invfin"), {lecs[0]["nr"]})
    assert [t["nr"] for _, _, t in found] == ["1"]

    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=120)
    at.session_state["nav"] = PAGES["module"]
    at.session_state["nav_module"] = "invfin"
    at.session_state["learn_sel_invfin"] = [lecs[0]["id"]]
    _run(at)
    texts = [m.value for m in at.markdown]
    assert "Berechnen Sie den Kapitalwert." in texts and "Erläutern Sie das CAPM." not in texts


def test_card_hint_always_in_prompt(monkeypatch):
    from datetime import date

    from utils import ai, learning

    data = {"cards": [], "chapters": [], "definitions": [], "lecture_notes": {},
            "documents": [{"id": "d1", "filename": "VL.pdf", "doc_type": "folien", "unit": "u1"}]}
    unit = {"id": "u1", "kind": "lecture", "nr": 1, "date": date(2026, 10, 20), "topic": "T", "chapter_id": None}
    data["lecture_notes"]["u1"] = {"card_hint": "Nur Formeln abfragen", "text": "", "images": []}
    monkeypatch.setattr(learning, "load_module", lambda _mid: data)
    monkeypatch.setattr(learning, "save_module", lambda _mid: None)
    monkeypatch.setattr(learning, "get_module", lambda _cfg, _mid: {"name": "F"})
    monkeypatch.setattr(learning, "get_document_pages", lambda _doc: ["a", "b"])
    monkeypatch.setattr(learning, "exam_style_material", lambda *a, **k: "")
    monkeypatch.setattr(ai, "is_available", lambda: True)
    seen = {}
    monkeypatch.setattr(ai, "complete_json", lambda prompt, *a, **k: seen.update(prompt=prompt) or {"cards": []})
    learning.generate_unit_cards({}, "m", unit, only={"d1": {2}})
    assert seen["prompt"].startswith("<hinweis_zur_kartenerstellung>\nNur Formeln abfragen")
    assert seen["prompt"].rstrip().endswith("Nur Formeln abfragen")


def test_exercise_feedback_flows_into_cards_quiz_and_grading(monkeypatch):
    """Rückmeldung aus dem Chat: Feld auf der Übungsseite, fließt in Karten-, Quiz- und Korrektur-Prompt ein."""
    from utils import ai, learning, storage, units
    from utils.config import get_module, load_config
    from views.common import PAGES
    from views.module_tabs import exams

    cfg = load_config()
    data = storage.load_module("invfin")
    lecs, exs = units.all_units(cfg, get_module(cfg, "invfin"), data)
    ex = exs[0]
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=120)
    at.session_state["nav"] = PAGES["module"]
    at.session_state["nav_module"] = "invfin"
    at.session_state["unit_invfin"] = ex["id"]
    _run(at)
    at.text_area[0].input("Barwert sicher")
    at.text_area[1].input("Annuität: Rentenbarwertfaktor falsch abgezinst")
    _button(at, "Speichern").click()
    _run(at)
    fb = at.session_state["_module_invfin"]["exercise_feedback"][ex["id"]]
    assert fb["bad"].startswith("Annuität") and fb["good"] == "Barwert sicher"
    assert units.has_feedback(at.session_state["_module_invfin"], ex["id"])

    data = storage.load_module("invfin")
    data["exercise_feedback"] = {ex["id"]: dict(fb)}
    block = learning.feedback_block(cfg, "invfin", data, [ex.get("chapter_id")])
    assert "<rueckmeldung_uebungen>" in block and "Rentenbarwertfaktor" in block and "Lief gut: Barwert" in block

    monkeypatch.setattr(ai, "is_available", lambda: True)
    seen = {}
    monkeypatch.setattr(ai, "complete_json", lambda prompt, *a, **k: seen.update(prompt=prompt) or {"questions": []})
    exams.build_quiz(cfg, "invfin", data, 3, exams.QUIZ_TYPES[0], "mittel", False, "Kontext", "Test", [])
    assert "Rentenbarwertfaktor" in seen["prompt"] and "option_notes" in seen["prompt"] and "hint" in seen["prompt"]
    exams.grade_answer({"question": "Berechne", "sample_answer": "42"}, "41", exams.weak_points(cfg, "invfin", data))
    assert "Rentenbarwertfaktor" in seen["prompt"] and "errors" in seen["prompt"]


def test_vwl_sessions_hidden_from_timetable_but_kept():
    from utils import storage, units
    from utils.config import get_module, load_config

    cfg = load_config()
    assert not storage.in_timetable({"module_id": "vwl", "type": "Übung"})
    assert not storage.in_timetable({"module_id": "vwl", "type": "Tutorium"})
    assert storage.in_timetable({"module_id": "vwl", "type": "Vorlesung"})
    assert storage.in_timetable({"module_id": "mathe", "type": "Tutorium"})
    _, exs = units.all_units(cfg, get_module(cfg, "vwl"), storage.load_module("vwl"))
    assert exs  # Übungen (und ihre To-dos) bleiben bestehen


def test_no_opus_models():
    from utils import ai, storage

    settings = storage.load_settings()
    settings["ai"] = {"models": {"tutor": "claude-opus-5-5", "cards": "claude-opus-5-5"}, "models_version": 2}
    assert ai._settings("tutor")[0] == "claude-sonnet-5-5"
    assert all("opus" not in m for m in storage.load_settings()["ai"]["models"].values())
    assert not any("opus" in m for m in ai.MODELS)


@pytest.mark.usefixtures("old_system")
def test_quiz_option_breakdown_and_hint(monkeypatch):
    """Quiz: Tipp zum Aufklappen, nach dem Auswerten jede Option mit richtig/falsch und Begründung."""
    from utils import storage
    from views.common import PAGES
    from views.module_tabs import exams

    data = storage.load_module("invfin")
    q = {"type": "mc", "operator": "", "question": "Was ist $r_f$?", "options": ["Zins", "Risiko", "Beta", "Rendite"],
         "correct_indices": [0], "option_notes": ["Richtig: risikoloser Zins", "Falsch: verwechselt mit sigma",
                                                  "Falsch: Beta misst Risiko", "Falsch: zu allgemein"],
         "hint": "$r_f$ steht für den risikolosen Zinssatz.", "explanation": "Weil.", "sample_answer": "",
         "points": 1}
    quiz = exams.save_quiz("invfin", data, [q], [], "center", "Test")
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=120)
    at.session_state["nav"] = PAGES["quiz"]
    at.session_state["qz_session"] = {"mid": "invfin", "qid": quiz["id"], "i": 0, "answers": {}}
    _run(at)
    assert any(e.label == "Tipp" for e in at.expander)
    at.radio[0].set_value(1)
    _button(at, "Auswerten").click()
    _run(at)
    text = " ".join(m.value for m in at.markdown)
    assert "Deine Wahl – falsch" in text and "verwechselt mit sigma" in text and "Richtig – nicht gewählt" in text

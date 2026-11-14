"""Neues Lernsystem: Migration ohne Datenverlust, Minithemen, Wissensstand, Check und Wochentraining."""

from __future__ import annotations

import json
import shutil
from datetime import date, timedelta
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


def _setup(module_id: str = "invfin", n_cards: int = 3):
    """Modul mit alten Karteikarten (inkl. Verlauf), einer Folien-PDF-Textfassung und gehaltener Vorlesung."""
    from utils import spaced_repetition as sr
    from utils import storage, units
    from utils.config import get_module, load_config

    cfg = load_config()
    data = storage.load_module(module_id)
    lecs, exs = units.all_units(cfg, get_module(cfg, module_id), data)
    lec = next(x for x in lecs if not x["is_break"])
    for i in range(n_cards):
        card = sr.new_card(f"Alte Frage {i}?", f"Antwort {i}")
        card["unit"] = lec["id"]
        sr.review(card, [0, 2, 3][i % 3], today=date(2026, 10, 20))
        data["cards"].append(card)
    doc = {"id": "doc1", "filename": "VL1.pdf", "doc_type": "folien", "unit": lec["id"], "path": "x/VL1.pdf",
           "n_pages": 4}
    data["documents"].append(doc)
    storage.set_document_pages(doc, ["Investition und Finanzierung", "Kapitalwert: Summe der Barwerte aller "
                                     "Zahlungen eines Projekts abzüglich Anfangsauszahlung zum heutigen Zeitpunkt",
                                     "Barwert: zukünftige Zahlung abgezinst mit dem Zinssatz r auf heute",
                                     "Literatur und Termine"], "text")
    storage.save_module(module_id)
    return cfg, data, lec, lecs, exs


def _fake_topics(prompt, schema, system=None, **kw):
    return {"topics": [{"title": "Kapitalwert", "minitopics": [
        {"nr": 1, "title": "Definition Kapitalwert", "kind": "definition", "importance": "hoch",
         "summary": "Summe der Barwerte minus Anfangsauszahlung.", "definition_term": "Kapitalwert",
         "definition": "Summe der Barwerte aller Zahlungen", "doc": 1, "pages": [2]},
        {"nr": 2, "title": "Barwert berechnen", "kind": "kopfrechnen", "importance": "normal",
         "summary": "Abzinsen mit (1+r)^t.", "definition_term": "", "definition": "", "doc": 1, "pages": [3]},
        {"nr": 3, "title": "Interpretation", "kind": "wissen", "importance": "normal",
         "summary": "Positiv ⇒ vorteilhaft.", "definition_term": "", "definition": "", "doc": 1, "pages": [2]}]}],
        "no_minitopic": [{"doc": 1, "pages": [1, 4], "reason": "Titel/Orga"}],
        "card_links": [{"card": 1, "minitopic": 1}, {"card": 2, "minitopic": 2}]}


def _fake_questions(prompt, schema, system=None, **kw):
    import re

    reqs = re.findall(r"\[(\d+)\] type=(\w+)", prompt)
    out = []
    for nr, qtype in reqs:
        q = {"req": int(nr), "type": qtype, "question": f"Frage {nr}?", "options": [], "correct_indices": [],
             "option_notes": [], "hints": ["Denk an …", "Konzept …", "Schritt …"], "explanation": "Weil …",
             "sample_answer": "", "key_points": [], "number_answer": "", "calc": "keins"}
        if qtype == "sc":
            q.update(options=["A", "B", "C", "D"], correct_indices=[1], option_notes=["f", "r", "f", "f"])
        elif qtype == "mc":
            q.update(options=["A", "B", "C", "D", "E"], correct_indices=[0, 2], option_notes=["r", "f", "r", "f", "f"])
        elif qtype == "zahl":
            q.update(number_answer="100", calc="kopf")
        else:
            q.update(sample_answer="Musterlösung", key_points=["Punkt 1", "Punkt 2"])
        out.append(q)
    return {"questions": out}


# ---------------------------------------------------------------------------
# Migration
# ---------------------------------------------------------------------------

def test_migration_keeps_every_card_and_makes_backup():
    from utils import migration, storage
    from utils.config import load_config

    cfg, data, lec, _, _ = _setup()
    before = json.dumps(data["cards"], sort_keys=True, default=str)
    state = storage.load_todos()
    state[f"invfin:vl:{lec['date'].isoformat()}:nachbereitet"] = True
    storage.save_todos()
    assert migration.ensure_all(load_config()) == []
    data = storage.load_module("invfin")
    assert json.dumps(data["cards"], sort_keys=True, default=str) == before  # Byte für Byte gleich
    info = data["cards_archived"]
    assert info["count"] == 3 and info["history"] == 3 and data["learning_version"] == 2
    assert lec["id"] in data["legacy_lectures"]  # schon nachbereitet → kein Check-To-do
    backup = DATA / info["backup"]
    assert (backup / "modules" / "invfin.json").exists() and (backup / "INFO.json").exists()
    saved = json.loads((backup / "modules" / "invfin.json").read_text())
    assert len(saved["cards"]) == 3
    assert migration.ensure_all(cfg) == []  # zweiter Lauf: nichts mehr zu tun, kein neues Backup
    assert len(list((DATA / "backups").iterdir())) == 1


def test_migration_aborts_without_saving_on_mismatch(monkeypatch):
    from utils import migration, storage
    from utils.config import load_config

    _setup()
    calls = iter([{"count": 3, "history": 3, "sha256": "a"}, {"count": 2, "history": 3, "sha256": "b"}] * 10)
    monkeypatch.setattr(migration, "fingerprint", lambda cards: next(calls))
    errors = migration.ensure_all(load_config())
    assert errors and "unverändert" in errors[0]
    assert storage.load_module("invfin").get("learning_version", 1) == 1
    assert "cards_archived" not in storage.load_module("invfin")


# ---------------------------------------------------------------------------
# Minithemen
# ---------------------------------------------------------------------------

def test_slide_suggestions_duplicates_and_orga():
    from utils import storage, topics

    cfg, data, lec, lecs, _ = _setup()
    nxt = next(x for x in lecs if x["date"] > lec["date"] and not x["is_break"])
    doc2 = {"id": "doc2", "filename": "VL2.pdf", "doc_type": "folien", "unit": nxt["id"], "path": "x/VL2.pdf"}
    data["documents"].append(doc2)
    storage.set_document_pages(doc2, ["Agenda", "Kapitalwert: Summe der Barwerte aller Zahlungen eines Projekts "
                                      "abzüglich Anfangsauszahlung zum heutigen Zeitpunkt",
                                      "Annuitätenmethode: konstante Zahlung über die Laufzeit mit gleichem Barwert "
                                      "wie das Projekt insgesamt bei Zinssatz r"], "text")
    sug = topics.suggest_exclusions(data, nxt, lecs, doc2)
    assert sug[1] == topics.REASON_ORGA and sug[2].startswith(f"schon in VL {lec['nr']}") and 3 not in sug
    topics.ensure_suggestions("invfin", data, nxt, lecs)
    assert set(topics.excluded(doc2)) == {1, 2}
    topics.toggle_slide("invfin", "doc2", 2)  # Klick aufs Bild nimmt den Vorschlag zurück
    assert set(topics.excluded(doc2)) == {1}
    from utils.units import lecture_notes

    notes = lecture_notes(data, nxt["id"])
    notes["scope"] = {"mode": "range", "from": 1, "to": 2}
    assert topics.active_pages(data, nxt, doc2) == [2]
    assert topics.carry_over(data, nxt)[0]["pages"] == [3]


def test_create_topics_keeps_ids_maps_cards_and_definitions(monkeypatch):
    from utils import ai, mastery, topics
    from utils import definitions as defs

    cfg, data, lec, lecs, _ = _setup()
    monkeypatch.setattr(ai, "is_available", lambda: True)
    seen = {}

    def fake(prompt, schema, system=None, **kw):
        seen["prompt"] = prompt
        return _fake_topics(prompt, schema, system, **kw)

    monkeypatch.setattr(ai, "complete_json", fake)
    n_cards = len(data["cards"])
    assert topics.create_topics(cfg, "invfin", lec, lecs) == 3
    assert "[1] Alte Frage 0?" in seen["prompt"] and "--- Seite 2 ---" in seen["prompt"]
    mts = topics.minitopics(data, lec["id"])
    assert [m["title"] for m in mts] == ["Definition Kapitalwert", "Barwert berechnen", "Interpretation"]
    assert data["archive_map"][data["cards"][0]["id"]] == mts[0]["id"]
    assert [d["term"] for d in defs.definitions(data)] == ["Kapitalwert"] and len(data["cards"]) == n_cards
    # Archiv-Hinweis: Karte 1 wurde mit „Gar nicht“ bewertet → schwach; ändert aber nichts am Wissensstand
    assert mastery.archive_hint(data, mts[0]["id"])["label"] == "schwach"
    assert mastery.status(data, mts[0]) == "neu" and not mastery.covered(data, mts[0])
    first_ids = [m["id"] for m in mts]
    topics.create_topics(cfg, "invfin", lec, lecs)  # neu erstellen: gleiche IDs, Wissensstand bleibt
    assert [m["id"] for m in topics.minitopics(data, lec["id"])] == first_ids


# ---------------------------------------------------------------------------
# Wissensstand
# ---------------------------------------------------------------------------

def test_grade_conversion_and_ladder():
    from utils import mastery

    assert mastery.ARCHIVE_GRADE == {0: "schwer", 1: "schwer", 2: "mittel", 3: "einfach"}
    data = {"mastery": {}}
    mt = {"id": "m1", "kind": "wissen", "importance": "normal"}
    calc = {"id": "m2", "kind": "kopfrechnen"}
    assert mastery.current_level(data, mt) == "sc"
    mastery.record(data, mt, True, "mittel", source="check", question_id="q", level_asked="sc")
    assert mastery.current_level(data, mt) == "mc" and mastery.covered(data, mt)
    mastery.record(data, mt, True, "schwer", source="training", question_id="q", level_asked="mc")
    assert mastery.current_level(data, mt) == "mc"  # schwer → bleibt
    mastery.record(data, mt, True, "einfach", source="training", question_id="q", level_asked="mc")
    assert mastery.current_level(data, mt) == "freitext"
    mastery.record(data, mt, False, "schwer", source="training", question_id="q", level_asked="freitext")
    assert mastery.current_level(data, mt) == "mc" and mastery.status(data, mt) == "unsicher"
    mastery.record(data, calc, True, "einfach", source="check", question_id="q", level_asked="mc")
    assert mastery.current_level(data, calc) == "mc"  # Rechnen nie als Freitext
    assert mastery.fsrs_grade(True, "einfach", hints_used=1) == 1  # Tipp benutzt → zählt wie schwer
    mastery.apply_exercise_flag(data, mt, "ex1", "schlecht", "Vorzeichen vertauscht")
    assert mastery.has_open_flag(data, mt)


def test_question_reuse_rules_and_number_parsing():
    from utils import question_bank as qb

    data = {"questions": [{"id": "q1", "minitopic_id": "m", "type": "sc", "used_in": [3], "calc": "keins"}]}
    assert qb.reusable(data, "m", "sc", 4, {}) is None  # direkt danach: nein
    assert qb.reusable(data, "m", "sc", 5, {})["id"] == "q1"  # eine Session dazwischen: ja
    q = data["questions"][0]
    qb.mark_used(q, 5)
    qb.mark_used(q, 7)
    assert q["retired"] and qb.reusable(data, "m", "sc", 20, {}) is None  # höchstens 3-mal
    assert qb.parse_number("1.000") == qb.parse_number("1000") and qb.parse_number("0,25") == qb.parse_number(".25")
    assert qb.check_number({"number_answer": "120"}, "120,0") and not qb.check_number({"number_answer": "120"}, "121")
    assert qb.question_type({"kind": "kopfrechnen"}, "mc", {}) == "zahl"
    assert qb.question_type({"kind": "kopfrechnen"}, "mc", {"calculator": True}) == "mc"
    assert qb.question_type({"kind": "wissen"}, "freitext", {}) == "freitext"


def test_plan_check_and_training_priorities(monkeypatch):
    from utils import mastery, sessions, topics

    cfg, data, lec, lecs, _ = _setup()
    monkeypatch.setattr(sessions.ai, "complete_json", _fake_topics)
    topics.create_topics(cfg, "invfin", lec, lecs)
    mts = topics.minitopics(data, lec["id"])
    first, second = sessions.halves(data, lec["id"])
    assert [m["id"] for m in first + second] == [m["id"] for m in mts] and first and second
    slots = sessions.plan_check(data, lec["id"], {}, 1)
    assert {s["mt"]["id"] for s in slots} == {m["id"] for m in first}  # nur die erste Hälfte, jedes Minithema
    assert len(slots) == min(sessions.CHECK_SIZE, 3 * len(first))
    assert {s["mt"]["id"] for s in sessions.plan_check(data, lec["id"], {}, 2)} == {m["id"] for m in second}
    # Nacharbeit „nicht verstanden“ → Einstieg Single Choice und eine zweite Frage im Check
    mastery.apply_nacharbeit(data, first[0], "unklar", "Formel verwechselt")
    assert mastery.current_level(data, first[0]) == "sc"
    many = [{**first[0], "id": f"x{i}", "title": f"X{i}"} for i in range(20)]
    monkeypatch.setattr(sessions, "part_minitopics", lambda d, lid, part: [first[0]] + many)
    big = sessions.plan_check(data, lec["id"], {}, 1)
    assert len(big) == 22  # 21 Minithemen + zweite Frage zum schwachen – mehr als 15 ist erlaubt
    assert sum(1 for s in big if s["mt"]["id"] == first[0]["id"]) == 2
    monkeypatch.undo()
    # Nach Check 1: Probleme aus dem Check haben im Training Vorrang, dann offene Minithemen
    data["sessions"] = [{"id": "s", "kind": "check", "lecture_id": lec["id"], "finished_at": "2026-11-01T10:00",
                         "part": 1, "part_ids": [m["id"] for m in first], "items": []}]
    assert sessions.check_done(data, lec["id"], 1) and not sessions.check_done(data, lec["id"], 2)
    mastery.record(data, first[0], True, "einfach", source="check", question_id="q", level_asked="sc")
    mastery.record(data, first[1], False, "schwer", source="check", question_id="q", level_asked="sc")
    held = [x for x in lecs if x["date"] <= lec["date"]]
    plan = sessions.plan_training(data, held, 1, {})
    assert [s["mt"]["id"] for s in plan] == [first[1]["id"]]
    assert not mastery.has_open_nacharbeit(data, first[0])  # sicher richtig beantwortet → erledigt


def test_nacharbeit_summary_maps_to_minitopics(monkeypatch):
    from utils import mastery, nacharbeit, sessions, topics

    cfg, data, lec, lecs, _ = _setup()
    monkeypatch.setattr(sessions.ai, "complete_json", _fake_topics)
    topics.create_topics(cfg, "invfin", lec, lecs)
    mts = topics.minitopics(data, lec["id"])
    nacharbeit.save("invfin", lec["id"], "SICHER:\n- [Folie 2] Kapitalwert\n\nWACKELIG:\n- [Folie 3] Barwert")
    assert nacharbeit.needs_mapping(data, lec["id"])
    monkeypatch.setattr(nacharbeit.ai, "complete_json", lambda *a, **k: {"links": [
        {"category": "sicher", "text": "Kapitalwert", "minitopics": [1]},
        {"category": "wackelig", "text": "Barwert – Vorzeichen", "minitopics": [2]},
        {"category": "ueben", "text": "Barwert mit anderen Zinsen", "minitopics": [2]}]})
    assert nacharbeit.map_summary(cfg, "invfin", lec["id"]) == 3
    assert mastery.nacharbeit_rating(data, mts[0]) == "sicher" and mastery.current_level(data, mts[0]) == "mc"
    assert mastery.has_open_nacharbeit(data, mts[1])
    assert any("anderen Zinsen" in n for n in mastery.weak_notes(data, mts[1]))
    assert not nacharbeit.needs_mapping(data, lec["id"])


def test_long_documents_are_split(monkeypatch):
    from utils import ai, topics

    cfg, data, lec, lecs, _ = _setup()
    doc = data["documents"][-1]
    from utils import storage

    storage.set_document_pages(doc, [f"Seite {i} Inhalt Kapitalwert Barwert Zins" for i in range(1, 151)], "text")
    doc["n_pages"] = 150
    doc["figure_pages"] = [5, 6, 7]
    storage.save_module("invfin")
    assert topics.parse_pages("1-3, 7; 10–11, 99", 20) == [1, 2, 3, 7, 10, 11]
    assert topics.format_pages([1, 2, 3, 7, 10, 11]) == "1-3, 7, 10-11"
    topics.set_read("invfin", lec["id"], doc["id"], "figures", [6])
    assert topics.unread_pages(storage.load_module("invfin"), lec)[doc["id"]] == [5, 7]
    topics.set_read("invfin", lec["id"], doc["id"], "all", list(range(1, 141)))
    calls = []

    def fake(prompt, schema, system=None, **kw):
        calls.append(prompt.count("--- Seite"))
        if calls[-1] > 30:
            raise ai.TruncatedError("zu lang")
        nr = len(calls)
        return {"topics": [{"title": f"Thema {nr}", "minitopics": [
            {"nr": 1, "title": f"Mini {nr}", "kind": "wissen", "importance": "normal", "summary": "…",
             "definition_term": "", "definition": "", "doc": 1, "pages": [1]}]}], "no_minitopic": [], "card_links": []}

    monkeypatch.setattr(ai, "complete_json", fake)
    n = topics.create_topics(cfg, "invfin", lec, lecs)
    assert max(calls) <= topics.TOPIC_CHUNK_PAGES and n == sum(1 for c in calls if c <= 30)


# ---------------------------------------------------------------------------
# Kompletter Durchlauf in der App
# ---------------------------------------------------------------------------

def test_check_session_end_to_end(monkeypatch):
    from utils import ai, mastery, planner, sessions, storage, topics
    from views.common import PAGES

    cfg, data, lec, lecs, _ = _setup()
    monkeypatch.setattr(ai, "is_available", lambda: True)
    monkeypatch.setattr(ai, "complete_json", _fake_topics)
    monkeypatch.setattr(ai, "complete", lambda *a, **k: "Stilprofil")
    topics.create_topics(cfg, "invfin", lec, lecs)
    monkeypatch.setattr(ai, "complete_json", _fake_questions)
    session = sessions.start_check(cfg, "invfin", lec, {})
    n = len(session["items"])
    assert session["label"].endswith("I&F Check 1") and session["part"] == 1 and n >= 4
    assert len({it["question_id"] for it in session["items"]}) == n

    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=120)
    at.session_state["nav"] = PAGES["cards"]
    at.session_state["v2_session"] = {"mid": "invfin", "sid": session["id"]}
    _run(at)
    assert not at.sidebar.button  # Fokus-Modus ohne Seitenleiste
    for _ in range(n):
        data = at.session_state["_module_invfin"]
        sess = sessions.find_session(data, session["id"])
        idx = sessions.current_index(sess)
        q = sessions.question(data, sess["items"][idx]["question_id"])
        if q["type"] == "sc":
            at.radio[0].set_value(1)
        elif q["type"] == "mc":
            at.checkbox(key=f"v2_{session['id']}_{idx}_mc_0").check()
            at.checkbox(key=f"v2_{session['id']}_{idx}_mc_2").check()
        elif q["type"] == "zahl":
            at.text_input(key=f"v2_{session['id']}_{idx}_num").input("100")
        else:
            monkeypatch.setattr(ai, "complete_json", lambda *a, **k: {"score": 4, "max_score": 4, "feedback": "gut",
                                                                       "errors": [], "missing_points": []})
            at.text_area(key=f"v2_{session['id']}_{idx}_txt").input("Meine Erklärung")
        if idx == 0:
            at.button(key=f"v2_{session['id']}_0_hint").click()
            _run(at)
            assert any("Tipp 1" in i.value for i in at.info)
        at.button(key=f"v2_{session['id']}_{idx}_check").click()
        _run(at)
        assert at.success, "Antwort sollte richtig sein"
        at.button(key=f"sg_mittel_v2_{session['id']}_{idx}").click()
        _run(at)
        if idx == 1:  # Zurück: vorherige Frage ansehen (nur lesen), dann wieder zur aktuellen
            at.button(key="v2_back").click()
            _run(at)
            assert any("Einschätzung: Mittel" in c.value for c in at.caption)
            at.button(key="v2_back").click()
            _run(at)
            at.button(key=f"v2_{session['id']}_0_fwd").click()
            _run(at)
            at.button(key=f"v2_{session['id']}_1_fwd").click()
            _run(at)
            assert at.button(key=f"v2_{session['id']}_2_check")
    assert any("geschafft" in m.value for m in at.markdown)
    data = at.session_state["_module_invfin"]
    assert sessions.check_done(data, lec["id"])
    assert not sessions.check_done(data, lec["id"], 2)
    mts = topics.minitopics(data, lec["id"])
    assert all(mastery.covered(data, m) for m in sessions.part_minitopics(data, lec["id"], 1))
    assert at.session_state["_todos"].get(planner.lecture_key("invfin", lec["date"], "check")) is True
    # die erste Frage wurde mit Tipp beantwortet → zählt wie schwer, Stufe bleibt
    first = next(m for m in mts if m["id"] == sess["items"][0]["minitopic_id"])
    assert mastery.peek(data, first["id"])["history"][0]["hints"] == 1
    saved = json.loads((DATA / "modules" / "invfin.json").read_text())
    assert saved["sessions"][-1]["finished_at"] and len(saved["cards"]) == 3  # Karten unverändert da
    del storage


def test_todos_in_fixed_order_and_training_window():
    from utils import planner, storage
    from utils.config import get_module, load_config

    cfg = load_config()
    module = get_module(cfg, "invfin")
    modules_data = {m["id"]: storage.load_module(m["id"]) for m in cfg["modules"]}
    lec = planner.lectures_of(module)[2]
    monday = planner.monday_of(planner.step_due(module, lec["date"], "upload"))
    sem_start, sem_end = storage.semester_dates(cfg)
    todos = [t for t in planner.generate_todos(cfg, modules_data, storage.get_schedule(cfg), monday, sem_start,
                                               sem_end, {}, storage.lecture_breaks(cfg)) if t["module_id"] == "invfin"]
    kinds = [t["kind"] for t in todos]
    assert {"Upload", "Nacharbeit", "Check 1"} <= set(kinds) and "Wiederholung" not in kinds
    assert kinds.index("Upload") < kinds.index("Nacharbeit") < kinds.index("Check 1")
    lec_todos = planner.lecture_steps_todos(cfg, module, modules_data["invfin"], lec, 3, storage.get_schedule(cfg),
                                            storage.lecture_breaks(cfg))
    assert [t["kind"] for t in lec_todos] == ["Upload", "Nacharbeit", "Check 1", "Check 2"]
    assert lec_todos[-1]["due"] > lec_todos[0]["due"]  # Check 2 nach dem Übungsblatt
    windows = planner.training_windows(cfg, module, storage.get_schedule(cfg), storage.lecture_breaks(cfg))
    for w in windows[:4]:  # Wochentraining 4 Tage nach der Blatt-Frist, zählt ab dem Tag davor
        assert w["due"] == w["ex_due"] + timedelta(days=4) and w["start"] == w["ex_due"] - timedelta(days=1)


def test_v2_pages_open():
    from views.common import PAGES

    _setup()
    for page in ("cards", "quiz", "today", "week", "settings"):
        at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=120)
        at.session_state["nav"] = PAGES[page]
        _run(at)
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=120)
    at.session_state["nav"] = PAGES["settings"]
    _run(at)
    assert any("Karten mit allen Bewertungen unverändert" in c.value for c in at.caption)


def test_mathe_sheets_follow_lectures():
    from utils import storage, units
    from utils.config import get_module, load_config

    cfg = load_config()
    data = storage.load_module("mathe")
    data["exercise_chapters"] = {}
    lecs, exs = units.all_units(cfg, get_module(cfg, "mathe"), data)
    by_title = {ex["title"].split(" –")[0]: ex for ex in exs}
    assert by_title["Übungsblatt 3"]["chapter_id"] == "e3"  # Einheit 3 (Selbststudium)
    assert by_title["Übungsblatt 4"]["chapter_id"] == "e4"
    lec3 = next(x for x in lecs if x["chapter_id"] == "e3")
    assert [ex["title"].split(" –")[0] for ex in units.related_exercises(lec3, exs)] == ["Übungsblatt 3"]


def test_shared_slide_deck_continues_in_next_lecture():
    from utils import storage, topics
    from utils.units import lecture_notes, unit_docs

    cfg, data, lec, lecs, _ = _setup("rewe", 0)
    nxt = next(x for x in lecs if x["date"] > lec["date"] and not x["is_break"])
    doc = next(d for d in data["documents"] if d["id"] == "doc1")
    topics.set_range("rewe", lec["id"], "doc1", 1, 2)  # „wir kamen bis Folie 2“
    assert topics.active_pages(data, lec, doc) == [1, 2]
    offer = topics.offered_carry(data, nxt, lecs)
    assert offer and offer[0]["pages"][0] == 3
    topics.accept_carry("rewe", nxt["id"], offer, True)
    assert doc in unit_docs(data, nxt) and topics.is_shared(doc, nxt["id"])
    assert topics.doc_range(lecture_notes(data, nxt["id"]), doc, 4) == (3, 4)
    assert not topics.offered_carry(data, nxt, lecs)  # schon übernommen
    # Vorschläge vergleichen eine gemeinsame Datei nicht mit sich selbst
    assert all(not r.startswith("schon in VL") for r in topics.suggest_exclusions(data, nxt, lecs, doc).values())
    del storage


def test_unfinished_tasks_carry_into_current_week():
    from utils import planner, storage
    from utils.config import load_config

    cfg = load_config()
    modules_data = {m["id"]: storage.load_module(m["id"]) for m in cfg["modules"]}
    sem_start, sem_end = storage.semester_dates(cfg)
    monday = planner.monday_of(storage.today())
    carried = planner.overdue_before(cfg, modules_data, storage.get_schedule(cfg), monday, sem_start, sem_end, {},
                                     {}, storage.lecture_breaks(cfg))
    assert carried and all(t["due"] < monday and t["carried"] for t in carried)
    assert len({t["key"] for t in carried}) == len(carried)
    state = {carried[0]["key"]: True}
    again = planner.overdue_before(cfg, modules_data, storage.get_schedule(cfg), monday, sem_start, sem_end, {},
                                   state, storage.lecture_breaks(cfg))
    assert carried[0]["key"] not in {t["key"] for t in again}


def test_step_deadlines_per_module():
    from utils import planner, storage
    from utils.config import get_module, load_config

    cfg = load_config()
    schedule, breaks = storage.get_schedule(cfg), storage.lecture_breaks(cfg)
    # Upload · Nacharbeit · Check 1 · Übungsblatt · Check 2 · Wochentraining (0 = Mo … 6 = So)
    expected = {"mathe": [0, 2, 4, 6, 1, 3], "rewe": [0, 2, 4, 6, 1, 3], "vwl": [1, 3, 5, 0, 2, 4],
                "invfin": [1, 3, 5, 0, 2, 4], "statistik": [3, 5, 0, 2, 4, 6]}
    for mid, days in expected.items():
        module = get_module(cfg, mid)
        lec = next(x for x in planner.lectures_of(module) if x["date"] >= date(2026, 11, 2))
        dues = [planner.step_due(module, lec["date"], s) for s in planner.STEP_DAYS]
        assert [d.weekday() for d in dues] == days, mid
        assert dues[0] == lec["date"] and (dues[-1] - dues[0]).days == 10
        todos = planner.lecture_steps_todos(cfg, module, {}, {**lec}, 1, schedule, breaks)
        assert [t["due"] for t in todos] == [dues[0], dues[1], dues[2], dues[4]]
        sheet = planner.lecture_sheet(module, lec, schedule, breaks)
        assert sheet and planner.exercise_due(module, sheet, schedule, breaks) == dues[3]
        window = next(w for w in planner.training_windows(cfg, module, schedule, breaks)
                      if w["lecture_date"] == lec["date"])
        assert window["due"] == dues[5]
    module = get_module(cfg, "mathe")
    due = {ex["title"].split(" –")[0]: planner.exercise_due(module, ex, schedule, breaks)
           for ex in planner.exercises_of(module)}
    assert due["Übungsblatt 4"] == date(2026, 11, 1) and due["Übungsblatt 5"] == date(2026, 11, 8)
    # VWL/Statistik: Blatt der Folgewoche gehört zur Vorlesung davor
    vwl = get_module(cfg, "vwl")
    pairs = planner.sheet_lectures(vwl, schedule, breaks)
    ex = next(e for e in planner.exercises_of(vwl) if e["week_of"] == date(2026, 11, 16))
    assert pairs[ex["index"]]["date"] == date(2026, 11, 10)


def test_exercise_feedback_maps_to_earlier_lectures(monkeypatch):
    from utils import ai, mastery, planner, sessions, storage, topics, units
    from utils.config import get_module

    cfg, data, lec, lecs, exs = _setup()
    monkeypatch.setattr(ai, "complete_json", _fake_topics)
    monkeypatch.setattr(ai, "complete", lambda *a, **k: "Profil")
    topics.create_topics(cfg, "invfin", lec, lecs)
    # Blatt 3 gehört zu einer späteren Vorlesung, fragt aber Stoff der ersten ab
    ex = next(e for e in exs if e["title"] == "Übungsblatt 3")
    pair = planner.sheet_lectures(get_module(cfg, "invfin"), storage.get_schedule(cfg),
                                  storage.lecture_breaks(cfg))[ex["index"]]
    assert pair["date"] > lec["date"]
    data = storage.load_module("invfin")
    units.exercise_feedback(data, ex["id"])["bad"] = "Kapitalwert-Definition vergessen"
    seen = {}

    def fake(prompt, schema, **kw):
        seen["prompt"] = prompt
        return {"links": [{"kind": "schlecht", "text": "Kapitalwert-Definition vergessen", "minitopics": [1]}]}

    monkeypatch.setattr(ai, "complete_json", fake)
    assert sessions.map_feedback(cfg, "invfin", ex) == 1
    assert "Definition Kapitalwert" in seen["prompt"] and "früheren Vorlesung" in seen["prompt"]
    data = storage.load_module("invfin")
    mt = next(m for m in topics.minitopics(data, lec["id"]) if m["title"] == "Definition Kapitalwert")
    assert mastery.has_open_flag(data, mt)
    assert data["exercise_feedback"][ex["id"]]["map_version"] == sessions.FEEDBACK_MAP_VERSION


def test_question_feedback_corrects_and_regrades(monkeypatch):
    from utils import ai, sessions, topics

    cfg, data, lec, lecs, _ = _setup()
    monkeypatch.setattr(ai, "is_available", lambda: True)
    monkeypatch.setattr(ai, "complete_json", _fake_topics)
    monkeypatch.setattr(ai, "complete", lambda *a, **k: "Profil")
    topics.create_topics(cfg, "invfin", lec, lecs)
    monkeypatch.setattr(ai, "complete_json", _fake_questions)
    session = sessions.start_check(cfg, "invfin", lec, {})
    idx = next(i for i, it in enumerate(session["items"]) if it["type"] == "sc")
    sessions.submit(cfg, "invfin", session, idx, [2])
    assert session["items"][idx]["correct"] is False
    monkeypatch.setattr(ai, "complete_json", lambda *a, **k: {
        "error_confirmed": True, "reply": "Stimmt, C ist richtig.", "correct_indices": [2], "number_answer": "",
        "sample_answer": "", "explanation": "Neu.", "option_notes": []})
    entry = sessions.question_feedback(cfg, "invfin", session, idx, sessions.FEEDBACK_KINDS[0], "C ist richtig")
    q = sessions.question(data, session["items"][idx]["question_id"])
    assert entry["confirmed"] and q["correct_indices"] == [2] and q["retired"] and q["corrected"]
    assert session["items"][idx]["correct"] is True  # neu gewertet
    mt_id = session["items"][idx]["minitopic_id"]
    assert any("C ist richtig" in n for n in sessions.feedback_notes(data, mt_id))


def test_priority_and_grouping():
    from utils import storage
    from views import common

    todos = [{"key": "a", "kind": "Wochentraining", "due": date(2026, 11, 2), "module_id": "m"},
             {"key": "b", "kind": "Übungsblatt", "due": date(2026, 11, 3), "module_id": "m"},
             {"key": "c", "kind": "Upload", "due": date(2026, 11, 5), "module_id": "m"},
             {"key": "d", "kind": "Upload", "due": date(2026, 11, 1), "module_id": "m"},
             {"key": "e", "kind": "Eigenes", "due": date(2026, 11, 1), "module_id": None}]
    common._cycle_prio("c")  # → 1
    assert common.prio_of("c") == 1
    groups = common.grouped(todos)
    # Vorgenommenes (mit Priorität) steht oben, der Rest darunter nach Kategorie
    assert [g for g, _ in groups] == ["Als Nächstes", "Upload", "Übungsblatt", "Wochentraining", "Sonstiges"]
    assert [t["key"] for t in groups[0][1]] == ["c"] and [t["key"] for t in groups[1][1]] == ["d"]
    common._cycle_prio("a")
    common._cycle_prio("a")  # → 2
    assert [t["key"] for t in common.grouped(todos)[0][1]] == ["c", "a"]
    for _ in range(2):
        common._cycle_prio("a")
    for _ in range(3):
        common._cycle_prio("c")
    assert common.prio_of("c") is None
    del storage


def test_move_lecture_to_other_module(monkeypatch):
    """Falsch hochgeladene VL (I&F 4 statt VWL 4): Dateien, Minithemen, Definitionen und Erledigt wandern mit."""
    from utils import ai, move, planner, storage, topics, units
    from utils import definitions as defs
    from utils.config import get_module

    cfg, data, lec, lecs, _ = _setup()
    monkeypatch.setattr(ai, "complete_json", _fake_topics)
    topics.create_topics(cfg, "invfin", lec, lecs)
    units.lecture_notes(data, lec["id"])["emphasized"] = "Kapitalwert"
    storage.load_todos()[planner.lecture_key("invfin", lec["date"], "nachbereitet")] = True
    vwl_lec = next(x for x in units.lectures(cfg, get_module(cfg, "vwl")) if not x["is_break"])
    res = move.move_lecture("invfin", lec, "vwl", vwl_lec)
    assert res["docs"] == 1 and res["minitopics"] == 3
    vwl = storage.load_module("vwl")
    assert not topics.lecture_topics(data, lec["id"]) and not [d for d in data["documents"] if d["id"] == "doc1"]
    assert len(topics.minitopics(vwl, vwl_lec["id"])) == 3
    assert next(d for d in vwl["documents"] if d["id"] == "doc1")["unit"] == vwl_lec["id"]
    assert storage.get_document_pages(next(d for d in vwl["documents"] if d["id"] == "doc1"))
    assert [d["term"] for d in defs.definitions(vwl)] == ["Kapitalwert"] and not defs.definitions(data)
    assert units.lecture_notes(vwl, vwl_lec["id"])["emphasized"] == "Kapitalwert"
    assert not data.get("archive_map")
    state = storage.load_todos()
    assert state.get(planner.lecture_key("vwl", vwl_lec["date"], "nachbereitet"))
    assert not state.get(planner.lecture_key("invfin", lec["date"], "nachbereitet"))


def test_legacy_lecture_checks_and_nacharbeit_optional(monkeypatch):
    from utils import ai, storage, topics
    from utils.config import get_module
    from views import progress
    from views.common import PAGES

    cfg, data, lec, lecs, exs = _setup()
    monkeypatch.setattr(ai, "complete_json", _fake_topics)
    monkeypatch.setattr(ai, "complete", lambda *a, **k: "Profil")
    topics.create_topics(cfg, "invfin", lec, lecs)
    data = storage.load_module("invfin")
    data["legacy_lectures"] = [lec["id"]]
    storage.save_module("invfin")
    steps = {name: state for name, state, _ in progress.lecture_steps(cfg, get_module(cfg, "invfin"), data, lec,
                                                                       exs, {})}
    assert steps["Nacharbeit"] == "optional" and steps["Check 1"] == "optional"
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=120)
    at.session_state["nav"] = PAGES["cards"]
    _run(at)
    assert any(s.value.startswith("Frühere Vorlesungen") for s in at.subheader)

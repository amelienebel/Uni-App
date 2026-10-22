"""Karteikarten: FSRS-Planung mit Klausurtermin, Tageskontingent und Kartenerstellung (KI simuliert)."""

from __future__ import annotations

from datetime import date, timedelta

from utils import spaced_repetition as sr

TODAY = date(2026, 11, 2)


def _card(**extra) -> dict:
    card = sr.new_card("Frage?", "- Antwort", **extra)
    card["due"] = TODAY.isoformat()
    return card


def test_grades_order_intervals():
    card = _card()
    nxt = sr.preview(card, None, TODAY)
    assert nxt[0] == 0 and nxt[1] == 0  # neue Karte: Gar nicht/Etwas ⇒ gleich nochmal
    assert 1 <= nxt[2] < nxt[3]


def test_intervals_grow_and_lapse_resets():
    card = _card()
    day = TODAY
    intervals = []
    for _ in range(4):
        sr.review(card, 2, None, day)
        intervals.append(card["interval"])
        day += timedelta(days=card["interval"])
    assert intervals == sorted(intervals) and intervals[-1] > intervals[0]
    s_before = card["stability"]
    sr.review(card, 0, None, day)
    assert card["interval"] == 0 and card["lapses"] == 1 and card["stability"] < s_before
    assert card["state"] == "relearning" and sr.is_due(card, day)


def test_exam_endspurt_every_card_before_exam():
    card = _card()
    for d in range(3):
        sr.review(card, 3, None, TODAY + timedelta(days=d * 30))
    day = TODAY + timedelta(days=90)
    sr.review(card, 3, 20, day)  # Klausur in 20 Tagen, Karte sehr sicher
    assert 20 - sr.FINAL_DAYS <= card["interval"] <= 19


def test_retention_rises_near_exam_and_priority():
    assert sr.target_retention(60) < sr.target_retention(14) < sr.target_retention(3)
    assert sr.target_retention(60, "low") < sr.target_retention(60) < sr.target_retention(60, "high")


def test_new_cards_quota_and_priority_order():
    cards = [_card(priority="low"), _card(priority="high"), _card()]
    cards += [_card() for _ in range(97)]
    assert sr.new_per_day(cards, None, 15) == 15
    assert sr.new_per_day(cards, 17, 15) == 15  # 100 Karten / 10 Tage = 10 < Minimum
    assert sr.new_per_day(cards, 12, 15) == 20  # 100 / 5 Tage
    assert sr.new_per_day(cards, 5, 15) == 100  # Puffer erreicht ⇒ alle
    queue = sr.due_queue(cards, None, today=TODAY, new_limit=5)
    assert queue[0]["priority"] == "high" and all(c["priority"] != "low" for c in queue)


def test_old_sm2_cards_keep_progress():
    old = {"id": "x", "front": "F", "back": "B", "ease": 2.5, "interval": 10, "reps": 3,
           "due": TODAY.isoformat(), "last_review": (TODAY - timedelta(days=10)).isoformat(), "history": [{}]}
    assert sr.is_due(old, TODAY) and old["state"] == "review" and old["stability"] == 10
    sr.review(old, 2, None, TODAY)
    assert old["interval"] > 10


def test_keyword_hits_and_suggestion():
    from views.module_tabs.study import keyword_hits, suggested_grade

    hits = keyword_hits("Das systematische Risiko ist nicht diversifizierbar", ["systematisches Risiko",
                                                                                 "Diversifikation", "Beta"])
    assert [h for _, h in hits] == [True, True, False]
    assert suggested_grade(hits) == 1
    assert suggested_grade([]) is None


def test_generate_cards_with_coverage(monkeypatch):
    from utils import ai, learning
    from utils import definitions as defs

    data = {"cards": [], "chapters": [{"id": "c1", "title": "Kapitel 1"}], "documents": [], "definitions": []}
    doc = {"id": "d1", "filename": "VL1.pdf", "doc_type": "folien", "unit": "u1"}
    data["documents"].append(doc)
    pages = ["Titelfolie", "Definition Risiko: Streuung der Rendite", "Formel $\\mu$ Erwartungswert der Rendite",
             "Literatur und weitere Quellen"]
    unit = {"id": "u1", "kind": "lecture", "nr": 1, "date": TODAY, "topic": "Risiko", "chapter_id": "c1"}
    monkeypatch.setattr(learning, "load_module", lambda _mid: data)
    monkeypatch.setattr(learning, "save_module", lambda _mid: None)
    monkeypatch.setattr(learning, "get_module", lambda _cfg, _mid: {"name": "Finanzen", "exam_note": "90 min"})
    monkeypatch.setattr(learning, "get_document_pages", lambda _doc: pages)
    monkeypatch.setattr(learning, "lecture_notes", lambda _d, _u: {"text": "", "emphasized": "Risiko!", "briefly": "",
                                                                   "examples": "", "images": []})
    monkeypatch.setattr(ai, "is_available", lambda: True)
    seen = {}

    def fake_json(prompt, schema, system, **kw):
        seen.update(prompt=prompt, system=system, task=kw.get("task"))
        return {"cards": [{
            "section": ["1 Risiko"], "type": "definition", "term": "Risiko", "front": "Risiko: Definition?",
            "answer": ["Streuung der Rendite", "  um den Erwartungswert"], "keywords": ["Streuung"],
            "explanation": "Weil …", "priority": "high", "sources": [{"doc": 1, "pages": [2]}],
            "from_notes": True, "needs_review": False, "chapter_hint": "Kapitel 1"}],
            "skipped": [{"doc": 1, "pages": [1, 4], "reason": "Titel/Literatur"}], "warnings": []}

    monkeypatch.setattr(ai, "complete_json", fake_json)
    assert learning.generate_unit_cards({}, "m", unit) == 1
    assert "[SEHR WICHTIG]\nRisiko!" in seen["prompt"] and "--- Folie 2 ---" in seen["prompt"]
    assert seen["system"] == learning.CARDS_SYSTEM and seen["task"] == "cards"
    card = data["cards"][0]
    assert card["back"] == "- Streuung der Rendite\n  - um den Erwartungswert"
    assert card["priority"] == "high" and card["sources"] == [{"doc_id": "d1", "pages": [2]}]
    assert [d["term"] for d in defs.definitions(data)] == ["Risiko"] and len(data["cards"]) == 1  # keine Doppelkarte
    cov = learning.card_coverage(data, unit)[0]
    assert cov["covered"] == [2] and list(cov["skipped"]) == [1, 4] and cov["missing"] == [3]
    # Nachholen: nur die fehlende Seite wird geschickt
    learning.generate_unit_cards({}, "m", unit, only={"d1": {3}})
    assert "--- Folie 3 ---" in seen["prompt"] and "--- Folie 2 ---" not in seen["prompt"]


def test_exam_style_and_slim(monkeypatch):
    from utils import ai, learning

    exam = {"id": "k1", "filename": "Klausur.pdf", "doc_type": "altklausur", "unit": None}
    sheet = {"id": "b1", "filename": "Blatt1.pdf", "doc_type": "uebung", "unit": None, "chapter_id": "c1"}
    cards = [{"id": f"x{i}", "front": f"Frage {i}", "back": "- Antwort", "unit": "u1"} for i in range(1, 4)]
    data = {"cards": cards, "chapters": [], "documents": [exam, sheet], "definitions": []}
    unit = {"id": "u1", "kind": "lecture", "nr": 2, "topic": "Funktionen"}
    monkeypatch.setattr(learning, "load_module", lambda _mid: data)
    monkeypatch.setattr(learning, "save_module", lambda _mid: None)
    monkeypatch.setattr(learning, "get_module", lambda _cfg, _mid: {"name": "Mathe"})
    monkeypatch.setattr(learning, "get_document_text",
                        lambda doc, **kw: {"k1": "Aufgabe 1: Bestimmen Sie f'(x)", "b1": "Blatt: Ableiten"}[doc["id"]])
    monkeypatch.setattr(learning, "get_document_pages", lambda _doc: [])
    monkeypatch.setattr(learning, "lecture_notes", lambda _d, _u: {"text": "", "emphasized": "Kettenregel", "skip": "Beweis",
                                                                   "card_hint": "kurz", "briefly": "", "examples": "",
                                                                   "images": []})
    style = learning.exam_style_material({}, "m", data)
    assert "Bestimmen Sie" in style and "Blatt: Ableiten" in style

    def fake_json(prompt, schema, **kw):
        assert "[SEHR WICHTIG]\nKettenregel" in prompt and "[STREICHEN]\nBeweis" in prompt
        assert "[HINWEIS]\nkurz" in prompt and "Bestimmen Sie" in prompt and "[3] Frage: Frage 3" in prompt
        return {"delete": [{"card": 2, "reason": "doppelt zu [1]"}],
                "rewrite": [{"card": 1, "front": "Kettenregel?", "answer": ["$f(g(x))' = f'(g(x))g'(x)$"],
                             "explanation": "…", "keywords": ["f'(g(x))"], "reason": "kürzer"},
                            {"card": 2, "front": "doppelt", "answer": ["x"], "explanation": "", "keywords": [],
                             "reason": ""}]}

    monkeypatch.setattr(ai, "complete_json", fake_json)
    proposal = learning.propose_slim({}, "m", unit)
    assert [d["id"] for d in proposal["delete"]] == ["x2"] and [r["id"] for r in proposal["rewrite"]] == ["x1"]
    assert learning.apply_slim("m", unit) == (1, 1)
    assert [c["id"] for c in data["cards"]] == ["x1", "x3"] and data["cards"][0]["front"] == "Kettenregel?"
    assert data["cards"][0]["previous"]["front"] == "Frage 1" and not data["card_slim"]


def test_read_pages_without_prep(monkeypatch):
    import io

    from pypdf import PdfWriter

    from utils import ai, learning

    writer = PdfWriter()
    for _ in range(3):
        writer.add_blank_page(100, 100)
    buf = io.BytesIO()
    writer.write(buf)
    doc = {"id": "d1", "filename": "VL2.pdf", "doc_type": "folien", "path": "x.pdf", "analysis": None}
    stored = {}
    monkeypatch.setattr(learning, "get_module", lambda _cfg, _mid: {"name": "Mathe"})
    monkeypatch.setattr(learning, "read_data_file", lambda _p: buf.getvalue())
    monkeypatch.setattr(learning, "get_document_pages", lambda _doc: ["a", "b", "c"])
    monkeypatch.setattr(learning, "set_document_pages", lambda _doc, pages, _m: stored.update(pages=pages))
    monkeypatch.setattr(learning, "save_module", lambda _mid: None)
    monkeypatch.setattr(learning, "run_analysis", lambda *a, **kw: (_ for _ in ()).throw(AssertionError("Vorbereitung")))
    monkeypatch.setattr(ai, "complete_json", lambda *a, **kw: {"slides": [{"page": 1, "text": "Grafik: f(x)"}]})
    assert learning.read_pages_visual({}, "m", doc, [2], update_prep=False) == "1 Seite(n) genau gelesen."
    assert stored["pages"] == ["a", "Grafik: f(x)", "c"] and doc["visual_pages"] == [2]

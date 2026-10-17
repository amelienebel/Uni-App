"""Seite einer einzelnen Vorlesung: Dateien, Vorbereiten, Nachbereiten, Lernen."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import streamlit as st

from utils import ai, planner, textbook
from utils.config import WEEKDAYS, get_module, load_config
from utils.learning import page_cost_estimate, pending_figures, read_pages_visual, run_analysis, unit_material
from utils.pdf_parser import figure_pages
from utils.storage import (IMAGE_TYPES, abs_data_path, chapter_label, delete_data_file, get_notes, load_module,
                           load_todos, now_iso, read_data_file, save_module, save_todos, save_upload)
from utils.units import has_notes, lecture_notes, related_exercises, short_label, unit_cards, unit_docs
from views.common import LECTURE_TABS, ai_hint, open_unit, render_formula, toggle_todo
from views import quiz_center
from views.module_tabs import exams, study, tutor
from views.module_tabs.files import file_list, show_messages, uploader


def _status_toggle(module_id: str, lec: dict, field: str, widget_key: str) -> None:
    todo = {"key": planner.lecture_key(module_id, lec["date"], field), "module_id": module_id,
            "chapter_id": lec.get("chapter_id"), "sync": field}
    toggle_todo(todo, widget_key)


def _set_done(module_id: str, lec: dict, field: str) -> None:
    state = load_todos()
    state[planner.lecture_key(module_id, lec["date"], field)] = True
    save_todos()
    data = load_module(module_id)
    planner.sync_chapter_status(get_module(load_config(), module_id), data, lec.get("chapter_id"), field, state)
    save_module(module_id)


def _header(cfg: dict, module_id: str, lec: dict, lecs: list[dict], exs: list[dict]) -> None:
    module = get_module(cfg, module_id)
    data = load_module(module_id)
    nav = st.columns([2, 1, 1])
    nav[0].button("Zum Ablauf", key=f"back_{lec['id']}", on_click=open_unit, args=(module_id, None))
    idx = lecs.index(lec)
    if idx > 0:
        nav[1].button("◀ vorige VL", key=f"prev_{lec['id']}", on_click=open_unit, args=(module_id, lecs[idx - 1]["id"]),
                      width="stretch")
    if idx < len(lecs) - 1:
        nav[2].button("nächste VL ▶", key=f"next_{lec['id']}", on_click=open_unit,
                      args=(module_id, lecs[idx + 1]["id"]), width="stretch")

    slot = next((s for s in module["schedule"] if s.get("type") == "Vorlesung"
                 and int(s.get("weekday", -1)) == lec["date"].weekday()), {})
    when = f"{WEEKDAYS[lec['date'].weekday()]}, {lec['date']:%d.%m.%Y}"
    if slot:
        when += f" · {slot.get('start', '')}–{slot.get('end', '')} · {slot.get('room', '')}"
    st.markdown(f"## :material/co_present: Vorlesung {lec['nr']}: {lec['topic']}")
    st.caption(when + (f" · {chapter_label(data, lec['chapter_id'])}" if lec.get("chapter_id") else "")
               + (" · vorlesungsfrei" if lec["is_break"] else ""))

    state = load_todos()
    c1, c2 = st.columns(2)
    prep, review = planner.prep_due(module, lec["date"]), planner.review_due(module, lec["date"])
    for col, field, label in ((c1, "vorbereitet", f"Vorbereitet (bis {WEEKDAYS[prep.weekday()][:2]} {prep:%d.%m.})"),
                              (c2, "nachbereitet",
                               f"Nachbereitet (bis {WEEKDAYS[review.weekday()][:2]} {review:%d.%m.})")):
        wkey = f"lst_{field}_{module_id}_{lec['id']}"
        st.session_state[wkey] = bool(state.get(planner.lecture_key(module_id, lec["date"], field)))
        col.checkbox(label, key=wkey, on_change=_status_toggle, args=(module_id, lec, field, wkey))

    related = related_exercises(lec, exs)
    if related:
        st.markdown("**Zugehörige Übungen:**")
        for ex in related:
            done = "✓" if state.get(ex["plan_key"]) else "○"
            st.button(f"{done} {short_label(ex)} – {ex['title']}", key=f"toex_{lec['id']}_{ex['id']}",
                      type="tertiary", on_click=open_unit, args=(module_id, ex["id"]))


def _files_tab(cfg: dict, module_id: str, lec: dict, exs: list[dict], all_units: list[dict]) -> None:
    data = load_module(module_id)
    uploader(cfg, module_id, lec, "folien", "Folien hochladen (PDF)",
             key=f"fol_{lec['id']}", analyse=True)
    docs = unit_docs(data, lec)
    file_list(module_id, docs, key=lec["id"], all_units=all_units,
              empty="Noch keine Folien für diese Vorlesung.")
    with st.expander("Weitere Unterlagen (Skript, Literatur …)"):
        uploader(cfg, module_id, lec, "skript", "Skript / Literatur (PDF)", key=f"skr_{lec['id']}")
    for ex in related_exercises(lec, exs):
        ex_docs = unit_docs(data, ex)
        st.markdown(f"**{short_label(ex)} – {ex['title']}**")
        file_list(module_id, ex_docs, key=f"{lec['id']}_{ex['id']}", empty="Noch keine Dateien zur Übung.")
    _book_chapters(module_id, data, lec)


def _save_book(module_id: str, lec_id: str, widget_key: str) -> None:
    data = load_module(module_id)
    data.setdefault("lecture_book", {})[lec_id] = sorted(st.session_state[widget_key])
    save_module(module_id)


def _book_chapters(module_id: str, data: dict, lec: dict) -> None:
    """Welche Lehrbuch-Kapitel ergänzen diese Vorlesung (Karteikarten & Tutor)?"""
    docs = textbook.book_docs(data)
    if not docs:
        return
    available = sorted({d["book_chapter"] for d in docs if d.get("book_chapter")})
    chosen = [c for c in textbook.lecture_chapters(data, lec) if c in available]
    wkey = f"book_sel_{lec['id']}"
    st.session_state[wkey] = chosen
    st.markdown("**:material/menu_book: Lehrbuch** – ergänzt Karteikarten und Tutor")
    st.multiselect("Buchkapitel zu dieser Vorlesung", available, key=wkey, on_change=_save_book,
                   args=(module_id, lec["id"], wkey), format_func=lambda n: f"Kapitel {n}",
                   placeholder="Kein Buchkapitel zugeordnet")


def _ensure_figure_pages(module_id: str, doc: dict) -> None:
    if "figure_pages" not in doc:  # ältere Uploads: einmalig nachträglich prüfen
        try:
            doc["figure_pages"] = figure_pages(read_data_file(doc["path"]))
        except (OSError, ValueError):
            doc["figure_pages"] = []
        save_module(module_id)


def _run(cfg: dict, module_id: str, job, spinner: str) -> None:
    with st.spinner(spinner):
        try:
            st.session_state[f"upmsg_{module_id}"] = [("success", job())]
        except ai.AIError as exc:
            st.session_state[f"upmsg_{module_id}"] = [("error", str(exc))]
    st.rerun()


def _figure_pages(cfg: dict, module_id: str, doc: dict) -> None:
    """Seiten mit Abbildungen nennen – die Studentin entscheidet, welche (teurer) genau gelesen werden.
    Die Vorbereitung entsteht erst nach dieser Entscheidung."""
    if doc.get("kind") == "image":
        return
    _ensure_figure_pages(module_id, doc)
    pending = pending_figures(doc)
    if doc.get("visual_pages"):
        st.caption(f"Genau gelesen: Seite(n) {', '.join(map(str, doc['visual_pages']))}")
    if not pending:
        return
    has_prep = bool(doc.get("analysis"))
    with st.container(border=True, key=f"figbox_{doc['id']}"):
        st.markdown(f":material/image: **Auf {len(pending)} Seite(n) kann ich die Abbildungen nicht sehen:** "
                    f"{', '.join(map(str, pending))}")
        wkey = f"figsel_{doc['id']}"
        chosen = st.multiselect("Welche Seiten soll ich genau lesen?", pending, default=pending, key=wkey,
                                format_func=lambda p: f"Seite {p}")
        cost = page_cost_estimate(len(chosen)) * 100
        verb = "aktualisieren" if has_prep else "erstellen"
        c1, c2 = st.columns([3, 2])

        def skip(pages: list[int]) -> None:
            doc["skipped_figures"] = sorted(set(doc.get("skipped_figures", [])) | set(pages))
            save_module(module_id)

        if c1.button(f"Genau lesen & Vorbereitung {verb} (ca. {cost:.1f} Cent)", key=f"figgo_{doc['id']}",
                     type="primary", disabled=not chosen or not ai.is_available()):
            skip([p for p in pending if p not in chosen])
            _run(cfg, module_id, lambda: read_pages_visual(cfg, module_id, doc, chosen),
                 f"Lese {len(chosen)} Seite(n) genau und erstelle die Vorbereitung …")
        if c2.button("Keine genau lesen" + ("" if has_prep else " – Vorbereitung erstellen"), key=f"figno_{doc['id']}"):
            skip(pending)
            if has_prep:
                st.rerun()
            _run(cfg, module_id, lambda: run_analysis(cfg, module_id, doc), "Erstelle Vorbereitung …")


def _cell(text: str) -> str:
    return (text or "").replace("|", "\\|").replace("\n", " ").strip() or "–"


def _check_questions(doc: dict, questions: list[dict]) -> None:
    """Pre-Check im alten Format (Frage + Musterantwort)."""
    st.markdown("#### :material/quiz: Pre-Check: Verständnisfragen")
    for i, q in enumerate(questions[:3], start=1):
        st.markdown(f"**{i}. {q['question']}**")
        st.text_area("Deine Antwort", key=f"cq_{doc['id']}_{i}", height=70, label_visibility="collapsed",
                     placeholder="Erst selbst antworten, dann auflösen …")
        with st.expander("Lösung anzeigen"):
            st.markdown(q["answer"])


def _prep_quiz(doc: dict, questions: list[dict]) -> None:
    st.markdown(f"#### :material/quiz: Quiz: {len(questions)} Fragen zum Selbsttest")
    store = st.session_state.setdefault(f"prepquiz_{doc['id']}", {})
    for i, q in enumerate(questions, start=1):
        if quiz_center.question_card(q, f"pq_{doc['id']}_{i}", store, title=f"Frage {i}"):
            st.rerun()
    graded = [r for r in store.values() if r["correct"] is not None]
    if graded:
        st.caption(f"{sum(r['correct'] for r in graded)} von {len(graded)} richtig")


def _prep_view(doc: dict, analysis: dict) -> None:
    """Scannbare Vorbereitung: Must-Watch, Kernkonzepte als Tabelle mit Folien, Pre-Check-Fragen."""
    if analysis.get("must_watch"):
        with st.container(border=True, key=f"nextbox_mw_{doc['id']}"):
            st.markdown("#### :material/star: Must-Watch: vor der Vorlesung ansehen")
            st.markdown("\n".join(f"- **Folie {m['slides']}** · {m['topic']} – {m['why']}"
                                   for m in analysis["must_watch"]))
    rows = analysis.get("concept_table", [])
    if rows:
        st.markdown("#### :material/table: Kernkonzepte")
        st.markdown("| Folie | Kernbegriff / Formel | Kurzerklärung | Worauf achten? |\n|---|---|---|---|\n" + "\n".join(
            f"| {_cell(r['slides'])} | **{_cell(r['term'])}** | {_cell(r['short'])} | {_cell(r['watch_out'])} |"
            for r in rows))
    if analysis.get("summary"):
        with st.expander("Ablauf entlang der Folien"):
            st.markdown(analysis["summary"])
    if analysis.get("formulas"):
        with st.expander(f"Formeln auf den Folien ({len(analysis['formulas'])})"):
            st.caption("In die Formelsammlung kommen sie erst, wenn du sie unter „Formeln & Notizen“ bestätigst.")
            for f in analysis["formulas"]:
                render_formula(f)
    if analysis.get("quiz"):
        _prep_quiz(doc, analysis["quiz"])
    elif analysis.get("check_questions"):
        _check_questions(doc, analysis["check_questions"])


def _old_prep_view(doc: dict, analysis: dict) -> None:
    """Zusammenfassungen im alten Format (vor der Tabellen-Vorbereitung)."""
    st.caption("Älteres Format – unten unter „Zusammenfassung neu erstellen“ gibt es die Tabellen-Fassung.")
    st.markdown(analysis.get("summary", ""))
    if analysis.get("key_concepts"):
        with st.expander(f"Fachbegriffe ({len(analysis['key_concepts'])})"):
            for concept in analysis["key_concepts"]:
                st.markdown(f"- **{concept['term']}** – {concept['explanation']}")
    if analysis.get("important_slides"):
        with st.expander("Diese Folien genau ansehen"):
            for s in analysis["important_slides"]:
                st.markdown(f"- **Folie {s['page']}**: {s['reason']}")
    if analysis.get("formulas"):
        with st.expander(f"Formeln auf den Folien ({len(analysis['formulas'])})"):
            st.caption("In die Formelsammlung kommen sie erst, wenn du sie unter „Formeln & Notizen“ bestätigst.")
            for f in analysis["formulas"]:
                render_formula(f)
    if analysis.get("check_questions"):
        _check_questions(doc, analysis["check_questions"])


def _prep_tab(cfg: dict, module_id: str, lec: dict) -> None:
    data = load_module(module_id)
    slides = [d for d in unit_docs(data, lec) if d.get("kind") != "image"]
    if not slides:
        st.info("Lade unter „Dateien“ die Folien hoch.")
        return
    for doc in slides:
        analysis = doc.get("analysis")
        if len(slides) > 1:
            st.markdown(f"### {doc['filename']}")
        if not analysis:
            _ensure_figure_pages(module_id, doc)
            if pending_figures(doc):
                _figure_pages(cfg, module_id, doc)
            elif st.button("Vorbereitung erstellen", key=f"an_{doc['id']}", type="primary"):
                _run(cfg, module_id, lambda doc=doc: run_analysis(cfg, module_id, doc), "Erstelle Vorbereitung …")
            continue
        if "concept_table" in analysis:
            _prep_view(doc, analysis)
        else:
            _old_prep_view(doc, analysis)
        if doc.get("text_source") == "ki-genau":
            st.caption("Genau gelesen: Formeln, Tabellen und Grafiken wurden mit erfasst.")
        else:
            _figure_pages(cfg, module_id, doc)
        with st.expander("Zusammenfassung neu erstellen"):
            st.caption("„Genau lesen“ lässt die KI das ganze PDF ansehen – inklusive Formeln, Tabellen und Grafiken. "
                       "Meist reicht es, oben nur die Seiten mit Abbildungen genau lesen zu lassen.")
            b1, b2 = st.columns(2)
            for col, visual, label in ((b1, False, "Neu erstellen"), (b2, True, "Genau lesen (mit Formeln & Grafiken)")):
                if col.button(label, key=f"rean_{visual}_{doc['id']}", disabled=visual and not ai.is_available()):
                    with st.spinner("Erstelle Vorbereitung …"):
                        try:
                            msg = run_analysis(cfg, module_id, doc, visual=visual)
                            st.session_state[f"upmsg_{module_id}"] = [("success", msg)]
                        except ai.AIError as exc:
                            st.session_state[f"upmsg_{module_id}"] = [("error", str(exc))]
                    st.rerun()


HANDWRITING_PROMPT = """Das sind Fotos meiner handschriftlichen Mitschrift aus der Vorlesung „{topic}“ im Modul
„{module}“. Tippe sie vollständig und originalgetreu ab, in der Reihenfolge der Fotos. Behalte Überschriften,
Aufzählungen und Pfeile/Zusammenhänge bei (als Markdown), Formeln in LaTeX mit $...$, Skizzen kurz in [eckigen
Klammern] beschreiben. Unleserliches mit [?] markieren. Nichts hinzuerfinden, nichts zusammenfassen."""


def _handwriting(module: dict, module_id: str, lec: dict, notes: dict) -> None:
    """Fotos der Papier-Mitschrift → KI tippt ab → Text landet in den Notizen."""
    with st.expander("Mitschrift auf Papier? Fotos abtippen lassen", icon=":material/photo_camera:"):
        if not ai.is_available():
            st.caption("Dafür wird ein API-Key benötigt.")
            return
        round_key = f"hw_round_{lec['id']}"
        photos = st.file_uploader("Fotos der Mitschrift (am Handy direkt mit der Kamera)", type=list(IMAGE_TYPES),
                                  accept_multiple_files=True, key=f"hw_{lec['id']}_{st.session_state.get(round_key, 0)}")
        if photos and st.button("Abtippen & in meine Notizen übernehmen", key=f"hw_go_{lec['id']}", type="primary",
                                icon=":material/edit_note:"):
            content = []
            for photo in photos:
                ext = Path(photo.name).suffix.lower().lstrip(".")
                content.append(ai.image_block(photo.getvalue(), IMAGE_TYPES.get(ext, "image/jpeg")))
            content.append({"type": "text", "text": HANDWRITING_PROMPT.format(topic=lec["topic"], module=module["name"])})
            with st.spinner(f"Tippe {len(photos)} Foto(s) ab …"):
                try:
                    text = ai.complete(content, max_tokens=16000)
                except ai.AIError as exc:
                    st.error(str(exc))
                    return
            notes["text"] = (notes["text"].rstrip() + "\n\n" if notes["text"].strip() else "") + \
                f"### Mitschrift (abgetippt)\n\n{text.strip()}"
            for photo in photos:
                notes["images"].append({"path": save_upload(module_id, photo.name, photo.getvalue(), "images"),
                                        "name": photo.name, "transcript": "", "in_notes": True})
            notes["updated_at"] = now_iso()
            save_module(module_id)
            st.session_state[round_key] = st.session_state.get(round_key, 0) + 1
            st.session_state[f"upmsg_{module_id}"] = [("success", "Mitschrift abgetippt und in deine Notizen "
                                                                  "übernommen – bitte kurz drüberlesen.")]
            st.rerun()


def _review_tab(cfg: dict, module_id: str, lec: dict) -> None:
    module = get_module(cfg, module_id)
    data = load_module(module_id)
    notes = lecture_notes(data, lec["id"])
    _handwriting(module, module_id, lec, notes)
    with st.form(f"lnotes_{module_id}_{lec['id']}"):
        text = st.text_area("Meine Notizen aus der Vorlesung", notes["text"], height=220,
                            placeholder="Was habe ich mitgeschrieben? Formeln gern in LaTeX: $C_0 = ...$")
        c1, c2, c3 = st.columns(3)
        emphasized = c1.text_area("Vom Dozenten betont", notes["emphasized"], height=130,
                                  placeholder="„Das kommt dran!“, Wiederholungen, Tafelanschrieb …")
        briefly = c2.text_area("Nur kurz angerissen", notes["briefly"], height=130,
                               placeholder="Folien übersprungen, „nur zur Info“ …")
        examples = c3.text_area("Genannte Beispiele", notes["examples"], height=130,
                                placeholder="Rechenbeispiele, Unternehmen, Fallstudien …")
        b1, b2 = st.columns(2)
        save = b1.form_submit_button("Speichern", width="stretch")
        finish = b2.form_submit_button("✓ Speichern & Nachbereitung abschließen", type="primary", width="stretch")
    if save or finish:
        notes.update({"text": text, "emphasized": emphasized, "briefly": briefly, "examples": examples,
                      "updated_at": now_iso()})
        save_module(module_id)
        if finish:
            _set_done(module_id, lec, "nachbereitet")
            st.session_state[f"ltab_next_{lec['id']}"] = LECTURE_TABS[3]
        st.rerun()
    if notes["text"].strip():
        with st.expander("Vorschau der Notizen (mit Formeln)"):
            st.markdown(notes["text"])

    st.markdown("#### Tafelbilder & Screenshots")
    images = st.file_uploader("Bilder hochladen", type=list(IMAGE_TYPES), accept_multiple_files=True,
                              key=f"img_up_{lec['id']}_{len(notes['images'])}")
    if images and st.button("Bilder speichern", key=f"img_save_{lec['id']}"):
        for img in images:
            notes["images"].append({"path": save_upload(module_id, img.name, img.getvalue(), "images"),
                                    "name": img.name, "transcript": ""})
        notes["updated_at"] = now_iso()
        save_module(module_id)
        st.rerun()
    cols = st.columns(3)
    for i, img in enumerate(list(notes["images"])):
        with cols[i % 3]:
            try:
                path = abs_data_path(img["path"])
            except ValueError:
                continue
            if path.exists():
                try:
                    st.image(str(path), caption=img["name"], width="stretch")
                except Exception:  # noqa: BLE001
                    st.caption(f"{img['name']} (Vorschau nicht möglich)")
            b1, b2 = st.columns(2)
            if ai.is_available() and not img.get("transcript") and not img.get("in_notes") and b1.button("Abtippen", key=f"tr_{lec['id']}_{i}"):
                ext = Path(img["name"]).suffix.lower().lstrip(".")
                with st.spinner("Lese Tafelbild …"):
                    try:
                        img["transcript"] = ai.complete([
                            ai.image_block(path.read_bytes(), IMAGE_TYPES.get(ext, "image/png")),
                            {"type": "text", "text": "Transkribiere dieses Tafelbild/diesen Screenshot aus einer "
                             f"Vorlesung „{module['name']}“ vollständig. Formeln in LaTeX ($...$), "
                             "Skizzen kurz in Worten beschreiben."},
                        ], max_tokens=8000)
                        notes["updated_at"] = now_iso()
                        save_module(module_id)
                    except ai.AIError as exc:
                        st.error(str(exc))
            if b2.button("Löschen", key=f"del_img_{lec['id']}_{i}"):
                delete_data_file(img["path"])
                notes["images"].remove(img)
                save_module(module_id)
                st.rerun()
            if img.get("transcript"):
                with st.expander("Abgetippt"):
                    st.markdown(img["transcript"])

    old = data["notes"].get(lec.get("chapter_id") or "")
    if old and any((old.get(k) or "").strip() for k in ("text", "emphasized", "briefly", "examples")):
        with st.expander("Ältere Notizen zu diesem Kapitel"):
            old = get_notes(data, lec["chapter_id"])
            for field, label in (("text", "Notizen"), ("emphasized", "Betont"), ("briefly", "Kurz angerissen"),
                                 ("examples", "Beispiele")):
                if old[field].strip():
                    st.markdown(f"**{label}:**\n\n{old[field]}")


def _learn_tab(cfg: dict, module_id: str, lec: dict) -> None:
    data = load_module(module_id)
    cards = unit_cards(data, lec)
    study.show_generation_message(lec["id"])
    has_ai = ai_hint("Die Kartenerstellung")
    generated = data.get("cards_generated", {}).get(lec["id"])
    notes_changed = lecture_notes(data, lec["id"]).get("updated_at")
    if generated and notes_changed and notes_changed > generated:
        st.info("Deine Nachbereitung hat sich seit der letzten Kartenerstellung geändert – ergänze die Karten, "
                "damit alles abgedeckt ist.")
    elif not has_notes(data, lec["id"]) and cards:
        st.caption("Tipp: Nach der Nachbereitung „Karten ergänzen“ – dann fließen deine Notizen mit ein.")
    elif not cards and not has_notes(data, lec["id"]):
        st.caption("Karten entstehen erst, wenn du auf „Karteikarten erstellen“ klickst – am besten nach der "
                   "Vorlesung, wenn du in der Nachbereitung eingetragen hast, was betont oder nur kurz angerissen "
                   "wurde.")
    if has_ai or cards or unit_docs(data, lec):
        study.generate_button(cfg, module_id, lec, cards, key=lec["id"])
    if generated:
        st.caption(f"Karten zuletzt erstellt am {datetime.fromisoformat(generated):%d.%m. um %H:%M}.")
    study.coverage_panel(cfg, module_id, lec, key=lec["id"])
    study.review_session(cfg, module_id, cards, key=f"lec_{lec['id']}")
    study.manual_card(module_id, data, lec, key=lec["id"])
    study.manage_cards(module_id, data, cards, key=lec["id"])

    st.divider()
    context = unit_material(data, lec)
    label = f"Vorlesung {lec['nr']} ({lec['date']:%d.%m.}): {lec['topic']}"
    with st.expander("Quiz zu dieser Vorlesung"):
        exams.quiz_section(cfg, module_id, data, scope_key=lec["id"], scope_label=label,
                           context=context or "(noch keine Unterlagen)", chapter_ids=[lec.get("chapter_id")] if lec.get("chapter_id") else [])
    with st.expander("Fragen an den Tutor zu dieser Vorlesung"):
        book = textbook.material_for_lecture(data, lec)
        tutor.render(cfg, module_id, scope_key=lec["id"],
                     context="\n\n".join(x for x in (context, book) if x) or "(noch keine Unterlagen)",
                     scope_label=label + (" · mit Lehrbuch" if book else ""))


LEC_TABS = LECTURE_TABS


def render(cfg: dict, module_id: str, lec: dict, lecs: list[dict], exs: list[dict]) -> None:
    _header(cfg, module_id, lec, lecs, exs)
    show_messages(module_id)
    if nxt := st.session_state.pop(f"ltab_next_{lec['id']}", None):
        st.session_state[f"ltab_{lec['id']}"] = nxt
    if st.session_state.get(f"ltab_{lec['id']}") not in LEC_TABS:
        st.session_state.pop(f"ltab_{lec['id']}", None)
    tabs = st.tabs(LEC_TABS, key=f"ltab_{lec['id']}", on_change="rerun")
    with tabs[0]:
        _files_tab(cfg, module_id, lec, exs, lecs + exs)
    with tabs[1]:
        _prep_tab(cfg, module_id, lec)
    with tabs[2]:
        _review_tab(cfg, module_id, lec)
    with tabs[3]:
        _learn_tab(cfg, module_id, lec)

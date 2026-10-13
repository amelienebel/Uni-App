"""Reiter: Vorlesungsvorbereitung – PDF-Upload, Extraktion, Zusammenfassung, Check-Fragen."""

from __future__ import annotations

import streamlit as st

from utils import ai, planner
from utils.config import get_module
from utils.pdf_parser import heuristic_analysis
from utils.storage import (add_document, add_formulas, chapter_label, documents_of, get_document_pages,
                           get_document_text, load_module, now_iso, save_module, today)
from views.common import ai_hint, chapter_select, render_formula

ANALYSIS_PROMPT = """Bereite mich auf die kommende Vorlesung vor. Unten stehen die Folien aus Moodle für das Modul
„{module}“, Kapitel „{chapter}“. Jede Folie ist mit „--- Folie N ---“ markiert.

Erstelle:
1. summary: eine kompakte Zusammenfassung der Kernkonzepte in Markdown (Überschriften und Stichpunkte,
   Formeln in $...$), so dass ich in 10 Minuten weiß, worum es geht und wie die Themen zusammenhängen.
2. key_concepts: die 5–12 wichtigsten Fachbegriffe mit prägnanter Erklärung.
3. important_slides: Folien, die ich mir unbedingt genau ansehen muss (wichtige Abbildungen, Diagramme,
   Herleitungen, Beispiele) – mit Foliennummer (page) und Begründung.
4. check_questions: genau 3 schnelle Verständnisfragen zum ersten Check, jeweils mit kurzer Musterantwort.
5. formulas: alle mathematischen und betriebswirtschaftlichen Formeln als sauberes LaTeX (ohne $-Zeichen)
   mit Name, kurzer Erklärung der Variablen und Foliennummer.

<folien>
{text}
</folien>"""


def _run_analysis(cfg: dict, module_id: str, doc: dict) -> None:
    cfg_module = get_module(cfg, module_id)
    data = load_module(module_id)
    pages = get_document_pages(doc)
    if ai.is_available():
        prompt = ANALYSIS_PROMPT.format(module=cfg_module["name"],
                                        chapter=chapter_label(data, doc.get("chapter_id")),
                                        text=get_document_text(doc, label="Folie"))
        result = ai.complete_json(prompt, ai.ANALYSIS_SCHEMA)
        result["mode"] = "ki"
    else:
        result = heuristic_analysis(pages)
    result["created_at"] = now_iso()
    doc["analysis"] = result
    save_module(module_id)
    added = add_formulas(module_id, result.get("formulas", []),
                         source=f"{doc['filename']} ({'KI' if result['mode'] == 'ki' else 'heuristisch'})",
                         chapter_id=doc.get("chapter_id"))
    st.session_state[f"prep_msg_{module_id}"] = f"Analyse fertig. {added} neue Formel(n) in die Formelsammlung übernommen."


def render(cfg: dict, module_id: str) -> None:
    data = load_module(module_id)
    upcoming = planner.current_chapter(cfg, get_module(cfg, module_id), data, today(), upcoming=True)

    st.subheader("🎬 Vorlesung vorbereiten")
    has_ai = ai_hint("Die Folienanalyse")

    with st.expander("⬆️ Moodle-Folien hochladen", expanded=not documents_of(data)):
        with st.form(f"prep_upload_{module_id}", clear_on_submit=True):
            files = st.file_uploader("PDF-Folien", type=["pdf"], accept_multiple_files=True)
            c1, c2 = st.columns(2)
            with c1:
                chapter_id = chapter_select(data, f"prep_up_ch_{module_id}", default=upcoming["id"] if upcoming else None)
            with c2:
                doc_types = cfg["document_types"]
                doc_type = st.selectbox("Dokumenttyp", list(doc_types), format_func=doc_types.get)
            if st.form_submit_button("Hochladen & Text extrahieren", type="primary") and files:
                for f in files:
                    with st.spinner(f"Extrahiere {f.name} …"):
                        doc = add_document(module_id, f.name, f.getvalue(), doc_type, chapter_id)
                    if doc["n_chars"] < 50:
                        st.warning(f"{f.name}: kaum Text gefunden (gescanntes PDF?). Analyse nur eingeschränkt möglich.")
                st.success(f"{len(files)} Datei(en) gespeichert.")

    docs = documents_of(data, ("folien", "skript", "sonstiges"))
    if not docs:
        st.caption("Noch keine Folien vorhanden.")
        return

    focus = st.session_state.pop(f"prep_focus_{module_id}", None)
    if focus:
        docs = sorted(docs, key=lambda d: d.get("chapter_id") != focus)
        st.session_state.pop(f"prep_doc_{module_id}", None)
    doc = st.selectbox("Foliensatz", docs, key=f"prep_doc_{module_id}",
                       format_func=lambda d: f"{d['filename']} – {chapter_label(data, d.get('chapter_id'))}")
    pages = get_document_pages(doc)

    c1, c2 = st.columns([1, 3])
    label = "🔄 Erneut analysieren" if doc.get("analysis") else "✨ Folien analysieren"
    if c1.button(label, key=f"analyze_{doc['id']}", type="primary"):
        with st.spinner("Analysiere Folien …" + (" (KI, kann etwas dauern)" if has_ai else "")):
            try:
                _run_analysis(cfg, module_id, doc)
            except ai.AIError as exc:
                st.error(str(exc))
    if msg := st.session_state.pop(f"prep_msg_{module_id}", None):
        st.success(msg)
    c2.caption(f"{doc['n_pages']} Seiten · {doc['n_chars']:,} Zeichen extrahiert".replace(",", "."))

    with st.expander("📄 Extrahierter Text (seitenweise)"):
        page_no = st.number_input("Seite", 1, max(1, len(pages)), 1, key=f"page_{doc['id']}")
        st.text(pages[page_no - 1] if pages else "(kein Text)")

    analysis = doc.get("analysis")
    if not analysis:
        return

    mode = "🤖 KI-Analyse" if analysis.get("mode") == "ki" else "🔧 Offline-Heuristik"
    st.caption(f"{mode} vom {analysis.get('created_at', '')[:10]}")
    left, right = st.columns([3, 2], gap="large")
    with left:
        st.markdown("#### 🧠 Kernkonzepte")
        st.markdown(analysis.get("summary", ""))
        for concept in analysis.get("key_concepts", []):
            st.markdown(f"- **{concept['term']}** – {concept['explanation']}")
    with right:
        st.markdown("#### 🖼️ Wichtige Folien & Abbildungen")
        slides = analysis.get("important_slides", [])
        if not slides:
            st.caption("Keine besonderen Hinweise.")
        for s in slides:
            st.markdown(f"- **Folie {s['page']}**: {s['reason']}")
        formulas = analysis.get("formulas", [])
        if formulas:
            st.markdown(f"#### 📐 Formeln ({len(formulas)})")
            for f in formulas[:6]:
                render_formula(f)
            if len(formulas) > 6:
                st.caption(f"… und {len(formulas) - 6} weitere im Reiter „Formelsammlung“.")

    st.markdown("#### ❓ 3 schnelle Verständnisfragen")
    for i, q in enumerate(analysis.get("check_questions", [])[:3], start=1):
        st.markdown(f"**{i}. {q['question']}**")
        st.text_area("Deine Antwort", key=f"cq_{doc['id']}_{i}", height=80, label_visibility="collapsed",
                     placeholder="Erst selbst antworten, dann auflösen …")
        with st.expander("Lösung anzeigen"):
            st.markdown(q["answer"])
    if analysis.get("check_questions"):
        chapter = next((ch for ch in data["chapters"] if ch["id"] == doc.get("chapter_id")), None)
        if chapter and not chapter["status"]["vorbereitet"]:
            if st.button("✅ Kapitel als vorbereitet markieren", key=f"mark_prep_{doc['id']}"):
                chapter["status"]["vorbereitet"] = True
                save_module(module_id)
                st.rerun()

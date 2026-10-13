"""Seite einer einzelnen Übung (inkl. Tutorium): Blatt, Musterlösung, meine Lösung, Fragen, Karten."""

from __future__ import annotations

import streamlit as st

from utils import ai, planner
from utils.config import WEEKDAYS_SHORT, get_module
from utils.storage import (abs_data_path, chapter_label, get_document_text, get_schedule, lecture_breaks, load_module,
                           load_todos, now_iso, save_module)
from utils.units import related_lectures, session_text, short_label, unit_cards, unit_docs
from views.common import open_unit, toggle_todo
from views.module_tabs import study
from views.module_tabs.files import file_list, show_messages, uploader
from views.module_tabs.notes import question_list

COMPARE_PROMPT = """Ich habe ein Übungsblatt im Modul „{module}“ gelöst. Vergleiche meine Lösung Aufgabe für
Aufgabe mit der Musterlösung (falls keine Musterlösung vorliegt: löse die Aufgaben selbst sauber und vergleiche).
- Was ist richtig? Wo genau liegen Fehler (Ansatz, Rechenweg, Ergebnis, Interpretation) – und warum?
- Was fehlt? Welche Punkte würde ich in einer Klausur verlieren?
- Konkrete Tipps, was ich wiederholen sollte.
Antworte in Markdown, gegliedert nach Aufgaben, Formeln in $...$."""


def _set_chapter(module_id: str, unit_id: str, widget_key: str) -> None:
    data = load_module(module_id)
    data.setdefault("exercise_chapters", {})[unit_id] = st.session_state[widget_key]
    save_module(module_id)


def _compare(cfg: dict, module_id: str, ex: dict, docs: list[dict]) -> None:
    module = get_module(cfg, module_id)
    content: list[dict] = [{"type": "text", "text": COMPARE_PROMPT.format(module=module["name"])}]
    for label, doc_type in (("Übungsblatt", "uebung"), ("Musterlösung", "loesung"), ("Meine Lösung", "eigene_loesung")):
        for doc in (d for d in docs if d["doc_type"] == doc_type):
            if doc.get("kind") == "image":
                try:
                    content.append({"type": "text", "text": f"{label} (Foto „{doc['filename']}“):"})
                    content.append(ai.image_block(abs_data_path(doc["path"]).read_bytes(), doc.get("mime", "image/png")))
                except (ValueError, OSError):
                    continue
            else:
                content.append({"type": "text", "text": f"<{label}>\n{get_document_text(doc)}\n</{label}>"})
    data = load_module(module_id)
    with st.spinner("Vergleiche deine Lösung …"):
        try:
            data.setdefault("exercise_feedback", {})[ex["id"]] = {"text": ai.complete(content, max_tokens=16000),
                                                                  "created_at": now_iso()}
            save_module(module_id)
        except ai.AIError as exc:
            st.error(str(exc))


def render(cfg: dict, module_id: str, ex: dict, lecs: list[dict], exs: list[dict]) -> None:
    data = load_module(module_id)
    state = load_todos()
    nav = st.columns([2, 1, 1])
    nav[0].button("← Zurück zum Ablauf", key=f"back_{ex['id']}", on_click=open_unit, args=(module_id, None))
    idx = exs.index(ex)
    if idx > 0:
        nav[1].button("◀ vorige Übung", key=f"prev_{ex['id']}", on_click=open_unit,
                      args=(module_id, exs[idx - 1]["id"]), width="stretch")
    if idx < len(exs) - 1:
        nav[2].button("nächste Übung ▶", key=f"next_{ex['id']}", on_click=open_unit,
                      args=(module_id, exs[idx + 1]["id"]), width="stretch")

    st.markdown(f"## ✏️ {ex['title']}")
    st.caption(f"Besprechung: {session_text(ex)}")

    wkey = f"exdone_{module_id}_{ex['id']}"
    st.session_state[wkey] = bool(state.get(ex["plan_key"]))
    due = planner.exercise_due(get_module(cfg, module_id), ex, get_schedule(cfg), lecture_breaks(cfg))
    st.checkbox(f"Blatt gelöst (bis {WEEKDAYS_SHORT[due.weekday()]} {due:%d.%m.})", key=wkey, on_change=toggle_todo,
                args=({"key": ex["plan_key"], "module_id": module_id, "chapter_id": ex.get("chapter_id"),
                       "sync": "uebung"}, wkey))

    c1, c2 = st.columns([4, 1], vertical_alignment="center")
    lectures = related_lectures(ex, lecs)
    if ex.get("chapter_id"):
        c1.markdown(f"**Bezieht sich auf:** {chapter_label(data, ex['chapter_id'])}"
                    + (" _(automatisch: Stoff der letzten Vorlesung davor)_" if ex.get("chapter_auto") else ""))
    else:
        c1.markdown("**Bezieht sich auf:** noch nicht zugeordnet")
    with c2.popover("Ändern"):
        options = [ch["id"] for ch in data["chapters"]]
        ckey = f"exch_{module_id}_{ex['id']}"
        st.selectbox("Kapitel", options, index=options.index(ex["chapter_id"]) if ex.get("chapter_id") in options else 0,
                     key=ckey, format_func=lambda cid: chapter_label(data, cid))
        st.button("Übernehmen", key=f"exchb_{ex['id']}", on_click=_set_chapter, args=(module_id, ex["id"], ckey))
    for lec in lectures:
        st.button(f"🎬 {short_label(lec)} – {lec['topic']}", key=f"tolec_{ex['id']}_{lec['id']}", type="tertiary",
                  on_click=open_unit, args=(module_id, lec["id"]))

    show_messages(module_id)
    all_units = lecs + exs
    docs = unit_docs(data, ex)
    cols = st.columns(3)
    for col, doc_type, title in ((cols[0], "uebung", "📄 Übungsblatt"), (cols[1], "loesung", "📗 Musterlösung"),
                                 (cols[2], "eigene_loesung", "✍️ Meine Lösung")):
        with col.container(border=True):
            st.markdown(f"**{title}**")
            file_list(module_id, [d for d in docs if d["doc_type"] == doc_type], key=f"{ex['id']}_{doc_type}",
                      all_units=all_units, empty="Noch nichts hochgeladen.")
            uploader(cfg, module_id, ex, doc_type, "Hochladen (PDF oder Foto)", key=f"{ex['id']}_{doc_type}",
                     allow_images=True)

    mine = [d for d in docs if d["doc_type"] == "eigene_loesung"]
    feedback = data.get("exercise_feedback", {}).get(ex["id"])
    if ai.is_available() and mine:
        label = "🔄 Erneut vergleichen" if feedback else "🤖 Meine Lösung mit der Musterlösung vergleichen"
        if st.button(label, key=f"cmp_{ex['id']}", type="secondary" if feedback else "primary"):
            _compare(cfg, module_id, ex, docs)
            feedback = data.get("exercise_feedback", {}).get(ex["id"])
    if feedback:
        with st.expander(f"🤖 Rückmeldung zu deiner Lösung (vom {feedback['created_at'][:10]})", expanded=True):
            st.markdown(feedback["text"])

    st.markdown("#### ❓ Fragen fürs Tutorium / die Übung")
    question_list(module_id, data, key_prefix=f"exq_{ex['id']}", unit=ex["id"])

    st.markdown("#### 🃏 Karteikarten zu dieser Übung")
    cards = unit_cards(data, ex)
    study.show_generation_message(ex["id"])
    if docs:
        study.generate_button(cfg, module_id, ex, cards, key=ex["id"],
                              label="✨ Karteikarten zu den Lösungswegen erstellen" if not cards else None)
    study.review_session(cfg, module_id, cards, key=f"ex_{ex['id']}")
    study.manage_cards(module_id, data, cards, key=ex["id"])

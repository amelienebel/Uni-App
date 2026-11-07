"""Seite einer einzelnen Übung (inkl. Tutorium): Blatt, Musterlösung, Fragen."""

from __future__ import annotations

import streamlit as st

from utils import planner
from utils.config import WEEKDAYS_SHORT, get_module
from utils.storage import chapter_label, get_schedule, lecture_breaks, load_module, load_todos, save_module
from utils.storage import now_iso
from utils.units import exercise_feedback, related_lectures, session_text, short_label, unit_docs
from views.common import done_button, open_unit
from views.module_tabs.files import file_list, show_messages, uploader
from views.module_tabs.notes import question_list

def _set_chapter(module_id: str, unit_id: str, widget_key: str) -> None:
    data = load_module(module_id)
    data.setdefault("exercise_chapters", {})[unit_id] = st.session_state[widget_key]
    save_module(module_id)


CHAT_PROMPT = ("Fasse kurz für meine Lern-App zusammen, wie diese Übung gelaufen ist – in zwei Teilen:\n"
               "Lief gut: welche Aufgaben/Themen/Rechenschritte ich sicher konnte (Stichpunkte).\n"
               "Lief schlecht: wo ich Fehler gemacht habe oder Hilfe brauchte – jeweils Thema, konkreter Fehler "
               "und warum (Stichpunkte, mit Aufgabennummer).")


def _feedback(module_id: str, ex: dict) -> None:
    """Rückmeldung aus dem Claude-Chat: was gut und was schlecht lief → fließt in Karten, Quiz und Korrektur ein."""
    data = load_module(module_id)
    fb = exercise_feedback(data, ex["id"])
    with st.container(border=True, key=f"fbbox_{ex['id'].replace(':', '_')}"):
        h1, h2 = st.columns([4, 1], vertical_alignment="center")
        h1.markdown("#### :material/forum: Rückmeldung aus dem Chat")
        with h2.popover("Frage für den Chat", icon=":material/content_copy:", width="stretch"):
            st.code(CHAT_PROMPT, language=None, wrap_lines=True)
        with st.form(f"exfb_{module_id}_{ex['id']}", border=False):
            c1, c2 = st.columns(2)
            good = c1.text_area(":green[:material/thumb_up:] Lief gut", fb["good"], height=150)
            bad = c2.text_area(":red[:material/thumb_down:] Lief schlecht", fb["bad"], height=150)
            if st.form_submit_button("Speichern", type="primary", width="stretch"):
                fb.update({"good": good.strip(), "bad": bad.strip(), "updated_at": now_iso()})
                save_module(module_id)
                _map_feedback(module_id, ex)
                st.toast("Rückmeldung gespeichert", icon=":material/check:")
        if fb.get("updated_at"):
            st.caption(f"Gespeichert am {fb['updated_at'][:16].replace('T', ' um ')}")


def _map_feedback(module_id: str, ex: dict) -> None:
    """Rückmeldung gleich den Minithemen zuordnen (fürs Wochentraining); klappt es nicht, beim Trainingsstart."""
    from utils import ai, planner, sessions
    from utils.config import load_config

    if not planner.LEARNING_V2 or not ai.is_available():
        return
    try:
        with st.spinner("Ordne die Rückmeldung den Minithemen zu …"):
            sessions.map_feedback(load_config(), module_id, ex)
    except ai.AIError:
        pass


def render(cfg: dict, module_id: str, ex: dict, lecs: list[dict], exs: list[dict]) -> None:
    data = load_module(module_id)
    state = load_todos()
    nav = st.columns([2, 1, 1])
    nav[0].button("Zum Ablauf", key=f"back_{ex['id']}", on_click=open_unit, args=(module_id, None))
    idx = exs.index(ex)
    if idx > 0:
        nav[1].button("vorige Übung", icon=":material/chevron_left:", key=f"prev_{ex['id']}", on_click=open_unit,
                      args=(module_id, exs[idx - 1]["id"]), width="stretch")
    if idx < len(exs) - 1:
        nav[2].button("nächste Übung", icon=":material/chevron_right:", key=f"next_{ex['id']}", on_click=open_unit,
                      args=(module_id, exs[idx + 1]["id"]), width="stretch")

    st.markdown(f"## :material/edit_note: {ex['title']}")
    st.caption(f"Besprechung: {session_text(ex)}")

    wkey = f"exdone_{module_id}_{ex['id']}"
    due = planner.exercise_due(get_module(cfg, module_id), ex, get_schedule(cfg), lecture_breaks(cfg))
    done_button(st.columns([1, 2])[0], f"Blatt gelöst (bis {WEEKDAYS_SHORT[due.weekday()]} {due:%d.%m.})",
                bool(state.get(ex["plan_key"])), {"key": ex["plan_key"], "module_id": module_id,
                                                  "chapter_id": ex.get("chapter_id"), "sync": "uebung"}, wkey)

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
        st.button(f"{short_label(lec)} – {lec['topic']}", key=f"tolec_{ex['id']}_{lec['id']}", type="tertiary",
                  on_click=open_unit, args=(module_id, lec["id"]))

    show_messages(module_id)
    all_units = lecs + exs
    docs = unit_docs(data, ex)
    cols = st.columns(2)
    for col, doc_type, title in ((cols[0], "uebung", "Übungsblatt"), (cols[1], "loesung", "Musterlösung")):
        with col.container(border=True):
            st.markdown(f"**{title}**")
            file_list(module_id, [d for d in docs if d["doc_type"] == doc_type], key=f"{ex['id']}_{doc_type}",
                      all_units=all_units, empty="Noch nichts hochgeladen.")
            uploader(cfg, module_id, ex, doc_type, "Hochladen (PDF oder Foto)", key=f"{ex['id']}_{doc_type}",
                     allow_images=True)

    _feedback(module_id, ex)

    st.markdown("#### Fragen fürs Tutorium / die Übung")
    question_list(module_id, data, key_prefix=f"exq_{ex['id']}", unit=ex["id"])

"""Reiter „Lernen & Klausur“: mehrere Vorlesungen auswählen und gemeinsam lernen (Karten, Quiz, Tutor, Altklausuren)."""

from __future__ import annotations

import streamlit as st

from utils.learning import unit_material
from utils.storage import load_module, today
from utils.units import scope_cards, short_label, unit_cards
from views.module_tabs import exams, study, tutor


def _select_all(key: str, ids: list[str]) -> None:
    st.session_state[key] = ids


def render(cfg: dict, module: dict, lecs: list[dict], exs: list[dict]) -> None:
    module_id = module["id"]
    data = load_module(module_id)
    held = [lec["id"] for lec in lecs if lec["date"] <= today()]
    all_ids = [lec["id"] for lec in lecs]
    by_id = {lec["id"]: lec for lec in lecs}
    key = f"learn_sel_{module_id}"
    if key not in st.session_state:
        st.session_state[key] = held or all_ids
    st.session_state[key] = [i for i in st.session_state[key] if i in by_id]

    st.markdown("**Welche Vorlesungen willst du lernen?** Die zugehörigen Übungen sind automatisch dabei.")
    b1, b2, b3 = st.columns(3)
    b1.button("Alle bisherigen", key=f"sel_held_{module_id}", on_click=_select_all, args=(key, held), width="stretch")
    b2.button("Alle", key=f"sel_all_{module_id}", on_click=_select_all, args=(key, all_ids), width="stretch")
    b3.button("Keine", key=f"sel_none_{module_id}", on_click=_select_all, args=(key, []), width="stretch")
    selected = st.multiselect("Vorlesungen", all_ids, key=key, label_visibility="collapsed",
                              format_func=lambda i: f"{short_label(by_id[i])} – {by_id[i]['topic'][:40]}")
    if not selected:
        st.info("Wähle mindestens eine Vorlesung aus.")
        return
    chosen = [by_id[i] for i in selected]
    cards = scope_cards(data, set(selected), exs, lecs)
    label = ", ".join(f"VL {lec['nr']}" for lec in chosen)

    t_cards, t_quiz, t_chat, t_exam = st.tabs([":material/style: Karteikarten", ":material/quiz: Quiz", ":material/forum: Tutor",
                                                       ":material/history_edu: Altklausuren"])
    with t_cards:
        missing = [lec for lec in chosen if not unit_cards(data, lec)]
        if missing:
            st.caption("Noch ohne Karten: " + ", ".join(f"VL {lec['nr']}" for lec in missing)
                       + " – Karten entstehen auf der Seite der jeweiligen Vorlesung.")
        study.review_session(cfg, module_id, cards, key=f"learn_{module_id}")
        study.forecast(cards)
    with t_quiz:
        chapters = sorted({lec["chapter_id"] for lec in chosen if lec.get("chapter_id")})
        context = "\n\n".join(f"## Vorlesung {lec['nr']}: {lec['topic']}\n{unit_material(data, lec)}" for lec in chosen)
        if len(context) > 250_000:  # sehr viel Stoff: Zusammenfassungen + Notizen statt Volltext
            context = "\n\n".join(f"## Vorlesung {lec['nr']}: {lec['topic']}\n{unit_material(data, lec, True)}"
                                    for lec in chosen)
        exams.quiz_section(cfg, module_id, data, scope_key="learn", scope_label=f"{label} (alle Themen)",
                           context=context, chapter_ids=chapters)
    with t_chat:
        tutor.render(cfg, module_id, scope_key="learn", context=context, scope_label=label)
    with t_exam:
        exams.altklausuren(cfg, module_id)

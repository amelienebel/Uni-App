"""📚 Modul-Bereich mit allen Reitern."""

from __future__ import annotations

import streamlit as st

from utils import planner
from utils.config import WEEKDAYS, get_module
from utils.storage import chapter_label, days_until_exam, get_exam_date, get_schedule, load_module, today
from views import event_detail
from views.common import MODULE_TAB_LABELS
from views.module_tabs import exams, flashcards, formulas_tab, notes, preparation, review, syllabus, tutor

TABS = list(MODULE_TAB_LABELS.values())


def render(cfg: dict, module_id: str) -> None:
    module = get_module(cfg, module_id)
    data = load_module(module_id)
    progress = planner.module_progress(data)
    days = days_until_exam(module_id)

    st.title(f"{module['icon']} {module['name']}")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Fortschritt", f"{progress['overall'] * 100:.0f} %")
    c2.metric("Kapitel komplett", f"{progress['chapters_done']}/{progress['n_chapters']}")
    c3.metric("Karten fällig", progress["card_stats"]["due"], help=f"{progress['card_stats']['total']} Karten insgesamt")
    exam = get_exam_date(module_id)
    c4.metric("Klausur", f"{days} Tage" if days is not None and days >= 0 else "–",
              help=f"Termin: {exam:%d.%m.%Y}" if exam else "Unter ⚙️ Einstellungen eintragen")
    st.progress(progress["overall"])

    nxt = planner.next_session(cfg, module, get_schedule(cfg), today())
    if nxt:
        when = f"{WEEKDAYS[nxt['date'].weekday()]}, {nxt['date']:%d.%m.} · {nxt.get('start', '')}" + (f"–{nxt['end']}" if nxt.get("end") else "") \
            + (f" · {nxt['room']}" if nxt.get("room") else "")
        about = nxt["topic"] or ""
        if nxt.get("chapter_id"):
            label = chapter_label(data, nxt["chapter_id"])
            about = f"{about} ({label})" if about and label.split(": ", 1)[-1] not in about else (about or label)
        st.info(f"**Als Nächstes: {nxt.get('type', '')}** am {when}" + (f"  \n{about}" if about else ""))

    sel = st.session_state.get("sel_event")
    if sel and sel.get("module_id") == module_id:
        event_detail.render(cfg, sel)

    if st.session_state.get(f"mtabs_{module_id}") not in TABS:
        st.session_state.pop(f"mtabs_{module_id}", None)
    tabs = st.tabs(TABS, key=f"mtabs_{module_id}")
    with tabs[0]:
        syllabus.render(cfg, module_id)
    with tabs[1]:
        preparation.render(cfg, module_id)
    with tabs[2]:
        review.render(cfg, module_id)
    with tabs[3]:
        flashcards.render(cfg, module_id)
    with tabs[4]:
        formulas_tab.render(cfg, module_id)
    with tabs[5]:
        exams.render(cfg, module_id)
    with tabs[6]:
        notes.render(cfg, module_id)
    with tabs[7]:
        tutor.render(cfg, module_id)

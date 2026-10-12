"""📚 Modul-Bereich mit allen Reitern."""

from __future__ import annotations

import streamlit as st

from utils import planner
from utils import spaced_repetition as sr
from utils.config import get_module
from utils.storage import days_until_exam, get_exam_date, load_module
from views.module_tabs import exams, flashcards, formulas_tab, preparation, review, syllabus, tutor

TABS = [
    "📖 Syllabus & Kapitel",
    "🎬 Vorlesungsvorbereitung",
    "📝 Nachbereitung",
    "🃏 Spaced Repetition",
    "📐 Formelsammlung",
    "🎯 Klausuren & Quiz",
    "💬 Verständnis-Chat",
]


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
    if days is not None and days >= 0:
        st.caption(f"Klausurdruck: {sr.exam_pressure(days)['label']} – beeinflusst Intervalle und Priorität der Wiederholungen.")
    st.progress(progress["overall"])

    tabs = st.tabs(TABS)
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
        tutor.render(cfg, module_id)

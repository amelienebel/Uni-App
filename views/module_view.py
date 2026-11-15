"""Modul-Bereich: Ablauf (Vorlesungen & Übungen) → Detailseiten; Lernen & Klausur; Formeln & Notizen."""

from __future__ import annotations

from datetime import date

import streamlit as st

from utils import planner, units
from utils.config import get_module
from utils.storage import (days_until_exam, get_exam_date, load_module, load_todos,
                           today)
from views.common import MODULE_TABS, micon
from views.module_tabs import ablauf, definitions_tab, files, exercise_page, learn, lecture_page, notes

TABS = MODULE_TABS


def _stats(module: dict, data: dict) -> None:
    """Fortschritt, Kapitel, Karten und Klausurtage – am Ende der Modulseite."""
    module_id = module["id"]
    if planner.LEARNING_V2:
        from views import progress

        stats = progress.module_stats(data)
        days = days_until_exam(module_id)
        st.divider()
        with st.container(key=f"kpis_{module_id}"):
            c1, c2, c3 = st.columns(3)
            c1.metric("Abgedeckt", f"{stats['asked']}/{stats['total']}", help="Minithemen, die schon abgefragt wurden")
            c2.metric("Sicher", stats["counts"]["sicher"])
            c3.metric("Klausur", f"{days} Tage" if days is not None and days >= 0 else "–")
        progress.render_status(data)
        return
    progress = planner.module_progress(data)
    days = days_until_exam(module_id)
    st.divider()
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Fortschritt", f"{progress['overall'] * 100:.0f} %")
    c2.metric("Kapitel komplett", f"{progress['chapters_done']}/{progress['n_chapters']}")
    c3.metric("Karten fällig", progress["card_stats"]["due"], help=f"{progress['card_stats']['total']} Karten insgesamt")
    exam = get_exam_date(module_id)
    c4.metric("Klausur", f"{days} Tage" if days is not None and days >= 0 else "–",
              help=f"Termin: {exam:%d.%m.%Y}" if exam else "Unter Einstellungen eintragen")
    st.progress(progress["overall"])


def _header(cfg: dict, module: dict, data: dict, lecs: list[dict], exs: list[dict]) -> None:
    from views import progress

    module_id = module["id"]
    with st.container(key=f"modhead_{module_id}"):
        st.title(f"{micon(module)} {module['name']}")
    if planner.LEARNING_V2:
        progress.week_board(cfg, module, data, lecs, exs, load_todos(), planner.monday_of(today()), key="mod",
                            with_title=False)


def render(cfg: dict, module_id: str) -> None:
    module = get_module(cfg, module_id)
    data = load_module(module_id)
    lecs, exs = units.all_units(cfg, module, data)

    # Klick auf eine Veranstaltung in der Wochenübersicht → passende Vorlesung/Übung öffnen
    sel = st.session_state.get("sel_event")
    if sel and sel.get("module_id") == module_id:
        st.session_state.pop("sel_event")
        st.session_state[f"unit_{module_id}"] = units.unit_for_event(cfg, module, data, sel.get("type", ""),
                                                                     date.fromisoformat(sel["date"]))

    unit_id = st.session_state.get(f"unit_{module_id}")
    unit = next((u for u in lecs + exs if u["id"] == unit_id), None) if unit_id else None
    if unit:
        st.caption(f"{module['name']}")
        if unit["kind"] == "lecture":
            lecture_page.render(cfg, module_id, unit, lecs, exs)
        else:
            exercise_page.render(cfg, module_id, unit, lecs, exs)
        return

    _header(cfg, module, data, lecs, exs)
    if st.session_state.get(f"mtabs_{module_id}") not in TABS:
        st.session_state.pop(f"mtabs_{module_id}", None)
    tabs = st.tabs(TABS, key=f"mtabs_{module_id}", on_change="rerun")
    with tabs[0]:
        ablauf.render(cfg, module, lecs, exs)
    with tabs[1]:
        learn.render(cfg, module, lecs, exs)
    with tabs[2]:
        definitions_tab.render(cfg, module, lecs, exs)
    with tabs[3]:
        files.all_files(cfg, module_id)
    with tabs[4]:
        notes.render(cfg, module_id)
    _stats(module, data)

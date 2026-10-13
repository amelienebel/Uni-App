"""📚 Modul-Bereich: Ablauf (Vorlesungen & Übungen) → Detailseiten; Lernen & Klausur; Formeln & Notizen."""

from __future__ import annotations

from datetime import date

import streamlit as st

from utils import planner, units
from utils.config import WEEKDAYS, get_module
from utils.storage import chapter_label, days_until_exam, get_exam_date, get_schedule, load_module, today
from views.module_tabs import ablauf, exercise_page, formulas_tab, learn, lecture_page, notes

TABS = ["📋 Ablauf", "🎓 Lernen & Klausur", "📐 Formeln & Notizen"]


def _header(cfg: dict, module: dict, data: dict) -> None:
    module_id = module["id"]
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
        when = f"{WEEKDAYS[nxt['date'].weekday()]}, {nxt['date']:%d.%m.} · {nxt.get('start', '')}" \
            + (f"–{nxt['end']}" if nxt.get("end") else "") + (f" · {nxt['room']}" if nxt.get("room") else "")
        about = nxt["topic"] or ""
        if nxt.get("chapter_id"):
            label = chapter_label(data, nxt["chapter_id"])
            about = f"{about} ({label})" if about and label.split(": ", 1)[-1] not in about else (about or label)
        st.info(f"**Als Nächstes: {nxt.get('type', '')}** am {when}" + (f"  \n{about}" if about else ""))


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
        st.caption(f"{module['icon']} {module['name']}")
        if unit["kind"] == "lecture":
            lecture_page.render(cfg, module_id, unit, lecs, exs)
        else:
            exercise_page.render(cfg, module_id, unit, lecs, exs)
        return

    _header(cfg, module, data)
    if st.session_state.get(f"mtabs_{module_id}") not in TABS:
        st.session_state.pop(f"mtabs_{module_id}", None)
    tabs = st.tabs(TABS, key=f"mtabs_{module_id}")
    with tabs[0]:
        ablauf.render(cfg, module, lecs, exs)
    with tabs[1]:
        learn.render(cfg, module, lecs, exs)
    with tabs[2]:
        formulas_tab.render(cfg, module_id)
        st.divider()
        notes.render(cfg, module_id)

"""Modul-Bereich: Ablauf (Vorlesungen & Übungen) → Detailseiten; Lernen & Klausur; Formeln & Notizen."""

from __future__ import annotations

from datetime import date

import streamlit as st

from utils import planner, units
from utils.config import WEEKDAYS, get_module
from utils.storage import (chapter_label, days_until_exam, get_exam_date, get_schedule, load_module, load_todos,
                           semester_dates, today)
from views.common import LECTURE_TABS, MODULE_TABS, micon, open_unit
from views.module_tabs import ablauf, definitions_tab, files, exercise_page, formulas_tab, learn, lecture_page, notes

TABS = MODULE_TABS


def _stats(module: dict, data: dict) -> None:
    """Fortschritt, Kapitel, Karten und Klausurtage – am Ende der Modulseite."""
    module_id = module["id"]
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


def _go_task(module_id: str, unit_id: str, tab: int | None) -> None:
    if tab:
        st.session_state[f"ltab_next_{unit_id}"] = LECTURE_TABS[tab]
    open_unit(module_id, unit_id)


def _short_date(d: date) -> str:
    return f"{WEEKDAYS[d.weekday()]}, {d:%d.%m.}"


def _header(cfg: dict, module: dict, data: dict, lecs: list[dict], exs: list[dict]) -> None:
    module_id = module["id"]
    now = today()
    with st.container(key=f"modhead_{module_id}"):
        st.title(f"{micon(module)} {module['name']}")
    sem_start, _ = semester_dates(cfg)
    tasks = units.open_tasks(cfg, module, lecs, exs, load_todos(), sem_start)
    nxt = planner.next_session(cfg, module, get_schedule(cfg), now)

    with st.container(border=True, key=f"nextbox_{module_id}"):
        c1, c2 = st.columns(2, gap="large")
        with c1:
            st.markdown(":material/task_alt: **Nächstes To-do**")
            if tasks:
                t = tasks[0]
                overdue = t["due"] < now
                when = "heute" if t["due"] == now else _short_date(t["due"])
                st.markdown(f"#### {t['label']}")
                st.markdown(("**überfällig** – war fällig " if overdue else "fällig ") + f"**{when}**")
                st.caption(t["about"])
                st.button("Jetzt öffnen →", key=f"gotask_{module_id}", type="primary",
                          on_click=_go_task, args=(module_id, t["unit"]["id"], t["tab"]))
                more = [x for x in tasks[1:] if x["due"] < now]
                if more:
                    st.caption(f"Außerdem überfällig: {len(more)} weitere Aufgabe(n)")
            else:
                st.markdown("Alles erledigt ")
        with c2:
            st.markdown(":material/event: **Nächster Termin**")
            if nxt:
                time = nxt.get("start", "") + (f"–{nxt['end']}" if nxt.get("end") else "")
                st.markdown(f"#### {nxt.get('type', '')}")
                st.markdown(f"**{_short_date(nxt['date'])}**" + (f" · {time} Uhr" if time else ""))
                about = nxt["topic"] or ""
                if nxt.get("chapter_id"):
                    label = chapter_label(data, nxt["chapter_id"])
                    about = f"{about} ({label})" if about and label.split(": ", 1)[-1] not in about else (about or label)
                st.caption(about + (f" · {nxt['room']}" if nxt.get("room") else ""))
                unit_id = units.unit_for_event(cfg, module, data, nxt.get("type", ""), nxt["date"])
                if unit_id:
                    st.button("Öffnen →", key=f"gonext_{module_id}", on_click=open_unit, args=(module_id, unit_id))
            else:
                st.markdown("Keine Termine mehr.")


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
        formulas_tab.render(cfg, module_id)
        st.divider()
        notes.render(cfg, module_id)
    _stats(module, data)

"""🏠 Wochenübersicht & Lernplan."""

from __future__ import annotations

from datetime import timedelta

import pandas as pd
import streamlit as st

from utils import planner
from utils import spaced_repetition as sr
from utils.config import WEEKDAYS, get_module, load_config, module_label
from utils.storage import (days_until_exam, get_exam_date, get_schedule, load_module, load_settings,
                           lecture_breaks, load_todos, save_module, save_todos, semester_dates, today)
from views.common import goto


def _toggle_todo(todo: dict, widget_key: str) -> None:
    value = st.session_state[widget_key]
    if todo.get("status_field"):
        data = load_module(todo["module_id"])
        for ch in data["chapters"]:
            if ch["id"] == todo["chapter_id"]:
                ch["status"][todo["status_field"]] = value
        save_module(todo["module_id"])
    else:
        state = load_todos()
        state[todo["key"]] = value
        save_todos()
        if todo.get("sync") and todo.get("chapter_id"):
            data = load_module(todo["module_id"])
            planner.sync_chapter_status(get_module(load_config(), todo["module_id"]), data, todo["chapter_id"],
                                        todo["sync"], state)
            save_module(todo["module_id"])


def render(cfg: dict) -> None:
    now = today()
    settings = load_settings()
    sem_start, sem_end = semester_dates(cfg)
    modules_data = {m["id"]: load_module(m["id"]) for m in cfg["modules"]}
    breaks = lecture_breaks(cfg)
    week_now = planner.semester_week(sem_start, now, breaks)

    st.title("🏠 Wochenübersicht & Lernplan")
    if week_now < 1:
        st.caption(f"Vorlesungsbeginn am {sem_start:%d.%m.%Y} – noch {(sem_start - now).days} Tage. "
                   "Perfekte Zeit, um Folien vorab anzusehen!")
    elif now > sem_end:
        st.caption("Die Vorlesungszeit ist vorbei – Fokus auf Klausurvorbereitung.")
    else:
        st.caption(f"Vorlesungswoche **{week_now}** · {WEEKDAYS[now.weekday()]}, {now:%d.%m.%Y}")

    # --- Klausur-Countdown -------------------------------------------------
    st.subheader("⏳ Prüfungs-Countdown")
    cols = st.columns(len(cfg["modules"]))
    for col, module in zip(cols, cfg["modules"]):
        days = days_until_exam(module["id"], now)
        exam = get_exam_date(module["id"])
        with col:
            if days is None:
                st.metric(f"{module['icon']} {module['short']}", "–", help="Kein Klausurtermin hinterlegt")
                st.caption("Termin fehlt")
            elif days < 0:
                st.metric(f"{module['icon']} {module['short']}", "vorbei")
                st.caption(f"{exam:%d.%m.%Y}")
            else:
                st.metric(f"{module['icon']} {module['short']}", f"{days} Tage")
                st.caption(f"{exam:%d.%m.%Y} · {sr.exam_pressure(days)['label']}")

    # --- Woche wählen --------------------------------------------------------
    st.divider()
    offset = st.session_state.setdefault("week_offset", 0)
    c1, c2, c3, c4 = st.columns([1, 1, 1, 4])
    if c1.button("◀ Vorwoche", width="stretch"):
        st.session_state["week_offset"] = offset - 1
        st.rerun()
    if c2.button("Heute", width="stretch"):
        st.session_state["week_offset"] = 0
        st.rerun()
    if c3.button("Nächste ▶", width="stretch"):
        st.session_state["week_offset"] = offset + 1
        st.rerun()
    monday = planner.monday_of(now) + timedelta(weeks=offset)
    week_no = planner.semester_week(sem_start, monday, breaks)
    c4.markdown(f"#### 📅 Woche {monday:%d.%m.} – {monday + timedelta(days=6):%d.%m.%Y}"
                + (" · 🎄 vorlesungsfrei" if planner.is_break_week(monday, breaks)
                   else f" · Vorlesungswoche {week_no}" if 1 <= week_no and monday <= sem_end else ""))

    schedule = get_schedule(cfg)
    events = planner.week_events(schedule, monday)
    todos = planner.generate_todos(cfg, modules_data, schedule, monday, sem_start, sem_end, settings["learning"], breaks)
    todo_state = load_todos()

    # --- Wochenraster ---------------------------------------------------------
    st.subheader("🗓️ Stundenplan & Fristen")
    day_cols = st.columns(7)
    for i, col in enumerate(day_cols):
        day = monday + timedelta(days=i)
        with col:
            is_today = day == now
            st.markdown(f"**{'🔵 ' if is_today else ''}{WEEKDAYS[i][:2]} {day:%d.%m.}**")
            day_break = planner.break_for(day, breaks)
            if day_break:
                st.caption(f"🎄 {day_break} – vorlesungsfrei")
            day_events = [] if day_break or day > sem_end or day < sem_start else [e for e in events if e["date"] == day]
            for ev in day_events:
                if ev.get("module_id") not in modules_data:
                    continue
                module = get_module(cfg, ev["module_id"])
                st.markdown(
                    f"<div style='border-left:4px solid {module['color']};padding:4px 6px;margin-bottom:6px;"
                    f"background:rgba(127,127,127,0.08);border-radius:4px;font-size:0.82rem'>"
                    f"<b>{ev.get('start', '')}–{ev.get('end', '')}</b><br>{module['icon']} {module['short']}<br>"
                    f"<i>{ev.get('type', '')}</i><br><span style='color:#888'>{ev.get('room', '')}</span></div>",
                    unsafe_allow_html=True)
            for mid in modules_data:
                exam = get_exam_date(mid)
                if exam == day:
                    st.error(f"📝 Klausur {get_module(cfg, mid)['short']}")
            due_today = [t for t in todos if t["due"] == day]
            for t in due_today:
                done = planner.todo_done(t, modules_data, todo_state)
                st.caption(f"{'✅' if done else '⬜'} {get_module(cfg, t['module_id'])['icon']} {t['kind']}")

    # --- To-do-Liste ---------------------------------------------------------
    left, right = st.columns([3, 2], gap="large")
    with left:
        st.subheader("✅ To-do-Liste dieser Woche")
        if not todos:
            st.info("Für diese Woche sind keine Aufgaben geplant (vorlesungsfreie Zeit oder kein Stundenplan).")
        open_count = sum(1 for t in todos if not planner.todo_done(t, modules_data, todo_state))
        if todos:
            st.progress(1 - open_count / len(todos), text=f"{len(todos) - open_count} von {len(todos)} erledigt")
        kinds = ["Alle", "Vorbereitung", "Nachbereitung", "Übungsblatt", "Aufgabe", "Wiederholung", "Klausurvorbereitung"]
        kind_filter = st.pills("Filter", kinds, default="Alle", key="todo_filter", label_visibility="collapsed")
        for t in todos:
            if kind_filter and kind_filter != "Alle" and t["kind"] != kind_filter:
                continue
            module = get_module(cfg, t["module_id"])
            key = f"todo_{t['key']}_{monday.isoformat()}"
            done = planner.todo_done(t, modules_data, todo_state)
            st.session_state[key] = done
            overdue = not done and t["due"] < now
            st.checkbox(
                f"{module['icon']} **{module['short']}** · {t['title']}  \n"
                f"{'⚠️ ' if overdue else ''}Frist: {planner.format_due(t['due'], now)}",
                key=key, on_change=_toggle_todo, args=(t, key))

    # --- Fortschritt & Empfehlungen -------------------------------------------
    with right:
        st.subheader("📈 Fortschritt pro Modul")
        for module in cfg["modules"]:
            progress = planner.module_progress(modules_data[module["id"]])
            stats = progress["card_stats"]
            st.progress(progress["overall"],
                        text=f"{module['icon']} {module['short']} – {progress['overall'] * 100:.0f} % "
                             f"({progress['chapters_done']}/{progress['n_chapters']} Kapitel komplett, "
                             f"{stats['due']} Karten fällig)")
        st.subheader("🎯 Lernfahrplan für heute")
        recs = planner.study_recommendations(cfg, modules_data, now)
        for rank, rec in enumerate(recs[:3], start=1):
            c_a, c_b = st.columns([4, 1])
            c_a.markdown(f"**{rank}. {module_label(cfg, rec['module_id'])}**  \n"
                         f"<span class='small-muted'>{rec['reason']} · Priorität {rec['score']}</span>",
                         unsafe_allow_html=True)
            c_b.button("Öffnen", key=f"rec_{rec['module_id']}", on_click=goto, args=(1, rec["module_id"]))

        due_total = sum(r["due"] for r in recs)
        if due_total:
            st.info(f"🃏 Heute insgesamt **{due_total}** Lernkarten fällig. "
                    f"Tageslimit laut Einstellungen: {settings['learning']['daily_review_limit']}.")

    # --- Kapitelübersicht ---------------------------------------------------
    with st.expander("📋 Kapitelstatus aller Module", expanded=False):
        rows = []
        for module in cfg["modules"]:
            for i, ch in enumerate(modules_data[module["id"]]["chapters"], start=1):
                rows.append({"Modul": module["short"], "Kapitel": f"{i}. {ch['title']}", "Woche": ch.get("week"),
                             "Vorbereitet": ch["status"]["vorbereitet"],
                             "Nachbereitet": ch["status"]["nachbereitet"], "Übung": ch["status"]["uebung"]})
        st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)

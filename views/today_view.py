"""Heute: Termine, fällige To-dos, Karteikarten und Klausur-Lernplan auf einen Blick."""

from __future__ import annotations

import re
from datetime import timedelta

import streamlit as st

from utils import exam_plan, notify, planner
from utils import spaced_repetition as sr
from utils.config import WEEKDAYS, get_module
from utils.storage import (days_until_exam, get_schedule, lecture_breaks, load_extra, load_module, load_settings,
                           load_todos, semester_dates, today)
from views import cards_center
from views.common import custom_todo_form, delete_custom_todo, goto, micon, open_todo, open_unit, todo_module, toggle_todo


def _safe(text: str) -> str:
    return re.sub(r"[^0-9A-Za-z]", "_", text)


def _open_event(cfg: dict, ev: dict) -> None:
    from utils import units

    module = get_module(cfg, ev["module_id"])
    unit_id = units.unit_for_event(cfg, module, load_module(module["id"]), ev.get("type", ""), ev["date"])
    open_unit(module["id"], unit_id)


def _todo_row(cfg: dict, t: dict, modules_data: dict, state: dict, now) -> None:
    module = todo_module(cfg, t)
    key = f"today_{t['key']}"
    st.session_state[key] = planner.todo_done(t, modules_data, state)
    with st.container(key=f"tdrow_{module['id']}_today_{_safe(t['key'])}"):
        c0, c1, c2, c3 = st.columns([0.5, 8, 3, 0.6], vertical_alignment="center")
        c0.checkbox("Erledigt", key=key, on_change=toggle_todo, args=(t, key), label_visibility="collapsed")
        c1.button(f"**{module['short']}** · {t['title']}", key=f"open_{key}", type="tertiary", icon=micon(module),
                  on_click=open_todo, args=(t,))
        c2.caption(planner.format_due(t["due"], now))
        if t.get("custom"):
            c3.button("", key=f"del_{key}", icon=":material/delete:", type="tertiary", help="Löschen",
                      on_click=delete_custom_todo, args=(t["key"],))


def render(cfg: dict) -> None:
    now = today()
    sem_start, sem_end = semester_dates(cfg)
    breaks = lecture_breaks(cfg)
    modules_data = {m["id"]: load_module(m["id"]) for m in cfg["modules"]}
    state = load_todos()
    if err := notify.ensure_scheduled(cfg, now):
        st.caption(err)

    st.title(f":material/today: Heute · {WEEKDAYS[now.weekday()]}, {now:%d.%m.}")

    # --- Kennzahlen ------------------------------------------------------------
    schedule = get_schedule(cfg)
    monday = planner.monday_of(now)
    todos = []
    for start in (monday - timedelta(weeks=1), monday):
        todos += planner.generate_todos(cfg, modules_data, schedule, start, sem_start, sem_end,
                                        load_settings()["learning"], breaks)
    todos += planner.custom_todos(state, end=now + timedelta(days=1))
    seen, open_todos = set(), []
    for t in todos:
        if t["key"] in seen or t["kind"] in ("Wiederholung", "Klausurvorbereitung"):
            continue
        seen.add(t["key"])
        if not planner.todo_done(t, modules_data, state) and t["due"] <= now + timedelta(days=1):
            open_todos.append(t)
    open_todos.sort(key=lambda t: (t["due"], t["module_id"] or ""))
    new_min = int(load_settings()["learning"].get("new_per_day", sr.DEFAULT_NEW_PER_DAY))
    card_plan = {mid: sr.daily_plan(d["cards"], days_until_exam(mid), new_min) for mid, d in modules_data.items()}
    due_cards = {mid: p["reviews"] + p["new"] for mid, p in card_plan.items()}
    c1, c2, _ = st.columns(3)
    c1.metric("Offene To-dos (bis morgen)", len(open_todos),
              help="Überfällig, heute und morgen fällig")
    c2.metric("Karteikarten heute", sum(due_cards.values()),
              help=f"{sum(p['reviews'] for p in card_plan.values())} Wiederholungen + "
              f"{sum(p['new'] for p in card_plan.values())} neue Karten")

    left, right = st.columns([3, 2], gap="large")
    with left:
        # --- Termine ---------------------------------------------------------------
        st.subheader(":material/event: Termine heute")
        events = [e for e in planner.week_events(schedule, monday) if e["date"] == now
                  and sem_start <= now <= sem_end and not planner.break_for(now, breaks)]
        if not events:
            st.caption("Heute keine Veranstaltungen.")
        for i, ev in enumerate(events):
            module = get_module(cfg, ev["module_id"])
            with st.container(key=f"tdrow_{module['id']}_ev_{i}"):
                c1, c2 = st.columns([3, 2], vertical_alignment="center")
                c1.button(f"**{module['short']}** · {ev.get('type', '')}", key=f"today_ev_{i}", type="tertiary",
                          icon=micon(module), on_click=_open_event, args=(cfg, ev))
                c2.caption(f"{ev.get('start', '')}–{ev.get('end', '')} · {ev.get('room', '')}")

        # --- To-dos ----------------------------------------------------------------
        h1, h2 = st.columns([3, 2], vertical_alignment="bottom")
        h1.subheader(":material/checklist: To-dos")
        with h2:
            custom_todo_form(cfg, "today_new", now)
        if not open_todos:
            st.caption("Nichts offen – stark!")
        for t in open_todos:
            _todo_row(cfg, t, modules_data, state, now)

        # --- Klausur-Lernplan --------------------------------------------------------
        conf = load_extra("exam_plan").get("settings", {})
        start_date = exam_plan.start_of(conf)
        if now >= start_date:
            st.subheader(":material/event_note: Klausur-Lernplan heute")
            plan = exam_plan.build_plan(cfg, modules_data, state, start_date, now,
                                        conf.get("weekday_blocks", 2), conf.get("weekend_blocks", 3))
            items = plan["days"][0]["items"] if plan["days"] and plan["days"][0]["date"] == now else []
            if not items:
                st.caption("Heute steht nichts aus dem Klausurplan an.")
            for item in items:
                if item["kind"] == "Klausur":
                    st.error(f"Klausur {get_module(cfg, item['module_id'])['short']} – viel Erfolg!")
                    continue
                key = exam_plan.plan_key(item["module_id"], item["id"])
                wkey = f"todayplan_{key}"
                st.session_state[wkey] = bool(state.get(key))
                module = get_module(cfg, item["module_id"])
                with st.container(key=f"tdrow_{module['id']}_plan_{_safe(key)}"):
                    st.checkbox(f"**{module['short']}** · {item['title']}", key=wkey, on_change=toggle_todo,
                                args=({"key": key, "module_id": module["id"]}, wkey))
            st.button("Ganzen Plan ansehen", key="today_plan", type="tertiary", icon=":material/arrow_forward:",
                      on_click=goto, args=("examplan",))

    with right:
        # --- Karteikarten ------------------------------------------------------------
        st.subheader(":material/style: Karteikarten")
        if not any(due_cards.values()):
            st.caption("Heute ist nichts fällig.")
        for module in cfg["modules"]:
            n = due_cards[module["id"]]
            if n:
                with st.container(key=f"tdrow_{module['id']}_cards"):
                    c1, c2 = st.columns([3, 2], vertical_alignment="center")
                    p = card_plan[module["id"]]
                    c1.markdown(f"{micon(module)} **{module['short']}** · {p['reviews']} wiederholen"
                                + (f" + {p['new']} neu" if p["new"] else ""))
                    c2.button("Lernen", key=f"learn_{module['id']}", on_click=cards_center.learn_due, args=(cfg, module["id"]),
                              width="stretch")

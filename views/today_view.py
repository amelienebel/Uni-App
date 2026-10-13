"""Heute: Termine, fällige To-dos, Karteikarten, Tages-Podcast, Klausur-Lernplan und Schwachstellen auf einen Blick."""

from __future__ import annotations

import re
from datetime import date, timedelta

import streamlit as st

from utils import ai, exam_plan, notify, planner, podcast
from utils import spaced_repetition as sr
from utils.config import WEEKDAYS, get_module
from utils.storage import (days_until_exam, get_schedule, lecture_breaks, load_extra, load_module, load_settings,
                           load_todos, semester_dates, today)
from utils.weakness import weakest
from views.common import MODULE_TABS, goto, micon, open_todo, open_unit, toggle_todo, tts_player
from views.module_tabs.study import WEAK_TAB_STATE


def _safe(text: str) -> str:
    return re.sub(r"[^0-9A-Za-z]", "_", text)


def _open_learn(module_id: str, weak: bool = False) -> None:
    st.session_state[f"mtabs_{module_id}"] = MODULE_TABS[1]
    if weak:
        st.session_state[WEAK_TAB_STATE.format(module_id)] = True
    open_unit(module_id, None)


def _open_event(cfg: dict, ev: dict) -> None:
    from utils import units

    module = get_module(cfg, ev["module_id"])
    unit_id = units.unit_for_event(cfg, module, load_module(module["id"]), ev.get("type", ""), ev["date"])
    open_unit(module["id"], unit_id)


def _todo_row(cfg: dict, t: dict, modules_data: dict, state: dict, now) -> None:
    module = get_module(cfg, t["module_id"])
    key = f"today_{t['key']}"
    st.session_state[key] = planner.todo_done(t, modules_data, state)
    with st.container(key=f"tdrow_{t['module_id']}_today_{_safe(t['key'])}"):
        c0, c1, c2 = st.columns([0.5, 8, 3], vertical_alignment="center")
        c0.checkbox("Erledigt", key=key, on_change=toggle_todo, args=(t, key), label_visibility="collapsed")
        c1.button(f"**{module['short']}** · {t['title']}", key=f"open_{key}", type="tertiary", icon=micon(module),
                  on_click=open_todo, args=(t,))
        c2.caption(planner.format_due(t["due"], now))


def _podcast(cfg: dict, now) -> None:
    lectures = podcast.lectures_on(cfg, now)
    entry = podcast.get(now)
    st.subheader(":material/podcasts: Podcast des Tages")
    if not lectures and not entry:
        older = sorted(podcast.store(), reverse=True)
        st.caption("Heute ist keine Vorlesung. Podcasts gibt es an Vorlesungstagen (Mo: Mathe & ExRW, "
                   "Di: I&F & VWL, Do: Statistik).")
        if older:
            _archive(older)
        return
    names = " & ".join(get_module(cfg, m["id"])["short"] for m, _ in lectures)
    if entry is None:
        if not ai.is_available():
            st.caption("Für den Podcast wird ein API-Key benötigt.")
            return
        auto = load_settings().setdefault("podcast", {}).get("auto", True)
        failed = st.session_state.get(f"podcast_failed_{now}")
        st.markdown(f"Etwa 10 Minuten zu den heutigen Vorlesungen ({names}).")
        if st.button("Podcast erstellen", key="podcast_make", type="primary", icon=":material/mic:") \
                or (auto and not failed):
            with st.spinner("Podcast wird geschrieben und eingesprochen … (1–3 Minuten)"):
                try:
                    entry = podcast.generate(cfg, now)
                except ai.AIError as exc:
                    st.session_state[f"podcast_failed_{now}"] = True
                    st.error(str(exc))
                    return
    _player(entry)
    older = sorted((d for d in podcast.store() if d != now.isoformat()), reverse=True)
    if older:
        _archive(older)


def _player(entry: dict) -> None:
    st.markdown(f"**{entry['title']}**")
    audio = podcast.audio_bytes(entry)
    if audio:
        st.audio(audio, format="audio/mp3")
    else:
        st.caption("Die Audio-Datei konnte nicht erzeugt werden – du kannst das Skript im Browser vorlesen lassen.")
        tts_player(podcast.plain_text(entry), key=f"pod_{entry['date']}")
    with st.expander("Skript lesen"):
        st.markdown(podcast.script_text(entry))


def _archive(days: list[str]) -> None:
    with st.expander(f"Frühere Podcasts ({len(days)})"):
        choice = st.selectbox("Tag", days, key="podcast_archive",
                              format_func=lambda d: f"{d[8:10]}.{d[5:7]}. – {podcast.store()[d]['title']}")
        if choice:
            _player(podcast.store()[choice])


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
    seen, open_todos = set(), []
    for t in todos:
        if t["key"] in seen or t["kind"] in ("Wiederholung", "Klausurvorbereitung"):
            continue
        seen.add(t["key"])
        if not planner.todo_done(t, modules_data, state) and t["due"] <= now + timedelta(days=1):
            open_todos.append(t)
    open_todos.sort(key=lambda t: (t["due"], t["module_id"]))
    due_cards = {mid: len(sr.due_queue(d["cards"], days_until_exam(mid))) for mid, d in modules_data.items()}
    exams = sorted((days_until_exam(m["id"]), m) for m in cfg["modules"] if (days_until_exam(m["id"]) or -1) >= 0)
    c1, c2, c3 = st.columns(3)
    c1.metric("Offene To-dos (bis morgen)", len(open_todos),
              help="Überfällig, heute und morgen fällig")
    c2.metric("Karteikarten fällig", sum(due_cards.values()))
    if exams:
        c3.metric(f"Nächste Klausur: {exams[0][1]['short']}", f"{exams[0][0]} Tage")

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
        st.subheader(":material/checklist: To-dos")
        if not open_todos:
            st.caption("Nichts offen – stark!")
        for t in open_todos:
            _todo_row(cfg, t, modules_data, state, now)

        # --- Klausur-Lernplan --------------------------------------------------------
        conf = load_extra("exam_plan").get("settings", {})
        start = conf.get("start")
        start_date = date.fromisoformat(start) if start else exam_plan.DEFAULT_START
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
        _podcast(cfg, now)

        # --- Karteikarten ------------------------------------------------------------
        st.subheader(":material/style: Karteikarten")
        if not any(due_cards.values()):
            st.caption("Heute ist nichts fällig.")
        for module in cfg["modules"]:
            n = due_cards[module["id"]]
            if n:
                with st.container(key=f"tdrow_{module['id']}_cards"):
                    c1, c2 = st.columns([3, 2], vertical_alignment="center")
                    c1.markdown(f"{micon(module)} **{module['short']}** · {n} fällig")
                    c2.button("Lernen", key=f"learn_{module['id']}", on_click=_open_learn, args=(module["id"],),
                              width="stretch")

        # --- Schwachstellen ------------------------------------------------------------
        weak = [(module, s) for module in cfg["modules"] for s in weakest(modules_data[module["id"]], 2)]
        weak.sort(key=lambda x: x[1]["mastery"])
        if weak:
            st.subheader(":material/troubleshoot: Schwachstellen")
            for module, s in weak[:4]:
                with st.container(key=f"tdrow_{module['id']}_weak_{s['chapter_id']}"):
                    c1, c2 = st.columns([3, 2], vertical_alignment="center")
                    c1.markdown(f"**{module['short']}** · {s['label']}  \n"
                                f"<span class='small-muted'>{s['mastery'] * 100:.0f} % sicher · "
                                f"{len(s['weak_cards'])} schwache Karten</span>", unsafe_allow_html=True)
                    c2.button("Üben", key=f"weak_{module['id']}_{s['chapter_id']}", width="stretch",
                              on_click=_open_learn, args=(module["id"], True))

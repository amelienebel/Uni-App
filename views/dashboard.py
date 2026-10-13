"""🏠 Wochenübersicht & Lernplan."""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import streamlit as st

from utils import ai, planner
from utils.config import WEEKDAYS, get_module, load_config, module_label
from utils.storage import (abs_data_path, chapter_label, get_exam_date, get_notes, get_schedule, lecture_breaks,
                           load_module, load_settings, load_todos, save_module, save_todos, semester_dates, today)
from views.common import goto, open_module_tab

SLOTS = [8, 10, 12, 14, 16, 18]
SLOT_LABELS = {s: f"{s:02d}–{s + 2:02d}" for s in SLOTS}
EXERCISE_TYPES = ("Übung", "Tutorium")


# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------

def _slot_of(start: str) -> int:
    try:
        hour = int(start.split(":")[0])
    except (ValueError, AttributeError):
        return SLOTS[0]
    hour = hour if hour % 2 == 0 else hour - 1
    return min(max(hour, SLOTS[0]), SLOTS[-1])


def _plans() -> dict:
    return load_todos().setdefault("_plan", {})


def _placement(todo: dict, monday: date) -> tuple[date, int | None]:
    """Tag/Zeitfenster eines To-dos: eigene Planung, sonst Frist (auf die angezeigte Woche begrenzt)."""
    plan = _plans().get(todo["key"])
    if plan:
        try:
            return date.fromisoformat(plan["date"]), plan.get("slot")
        except (KeyError, ValueError):
            pass
    sunday = monday + timedelta(days=6)
    return min(max(todo["due"], monday), sunday), None


def _toggle_todo(todo: dict, widget_key: str) -> None:
    value = st.session_state[widget_key]
    if todo.get("status_field"):
        data = load_module(todo["module_id"])
        for ch in data["chapters"]:
            if ch["id"] == todo["chapter_id"]:
                ch["status"][todo["status_field"]] = value
        save_module(todo["module_id"])
        return
    state = load_todos()
    state[todo["key"]] = value
    save_todos()
    if todo.get("sync") and todo.get("chapter_id"):
        data = load_module(todo["module_id"])
        planner.sync_chapter_status(get_module(load_config(), todo["module_id"]), data, todo["chapter_id"],
                                    todo["sync"], state)
        save_module(todo["module_id"])


def _move_todo(todo_key: str, day_key: str, slot_key: str) -> None:
    day = st.session_state.get(day_key)
    slot = st.session_state.get(slot_key)
    if day:
        _plans()[todo_key] = {"date": day, "slot": slot}
        save_todos()


def _reset_todo(todo_key: str) -> None:
    _plans().pop(todo_key, None)
    save_todos()


def _select_event(ev: dict) -> None:
    st.session_state["sel_event"] = {k: (v.isoformat() if isinstance(v, date) else v) for k, v in ev.items()}


def _todo_widget(t: dict, cfg: dict, modules_data: dict, todo_state: dict, monday: date, now: date,
                 place: str, compact: bool) -> None:
    module = get_module(cfg, t["module_id"])
    key = f"todo_{place}_{t['key']}_{monday.isoformat()}"
    done = planner.todo_done(t, modules_data, todo_state)
    st.session_state[key] = done
    overdue = not done and t["due"] < now
    if compact:
        label = f"{module['icon']} {t['kind']}: {t['title'].split(' – ', 1)[-1]}"
        help_text = f"{module['short']} · Frist: {planner.format_due(t['due'], now)}"
    else:
        label = (f"{module['icon']} **{module['short']}** · {t['title']}  \n"
                 f"{'⚠️ ' if overdue else ''}Frist: {planner.format_due(t['due'], now)}")
        help_text = None
    c_check, c_move = st.columns([6, 1], vertical_alignment="top")
    with c_check:
        st.checkbox(("⚠️ " if overdue and compact else "") + label, key=key, on_change=_toggle_todo,
                    args=(t, key), help=help_text)
    with c_move:
        with st.popover("↔️", help="Verschieben"):
            st.markdown(f"**{t['title']}**")
            days = [monday + timedelta(days=i) for i in range(7)]
            current_day, current_slot = _placement(t, monday)
            day_key, slot_key = f"mvd_{place}_{t['key']}", f"mvs_{place}_{t['key']}"
            day_options = [d.isoformat() for d in days]
            st.selectbox("Tag", day_options,
                         index=day_options.index(current_day.isoformat()) if current_day.isoformat() in day_options
                         else 0, key=day_key,
                         format_func=lambda iso: f"{WEEKDAYS[date.fromisoformat(iso).weekday()]}, "
                                                 f"{date.fromisoformat(iso):%d.%m.}")
            slot_options = [None] + SLOTS
            st.selectbox("Zeit", slot_options, index=slot_options.index(current_slot) if current_slot in slot_options
                         else 0, key=slot_key,
                         format_func=lambda s: "Ohne feste Zeit (Aufgabenzeile)" if s is None else f"{SLOT_LABELS[s]} Uhr")
            b1, b2 = st.columns(2)
            b1.button("Verschieben", key=f"mvb_{place}_{t['key']}", type="primary",
                      on_click=_move_todo, args=(t["key"], day_key, slot_key))
            b2.button("Zurücksetzen", key=f"mvr_{place}_{t['key']}", on_click=_reset_todo, args=(t["key"],))


# ---------------------------------------------------------------------------
# Detailansicht einer Veranstaltung
# ---------------------------------------------------------------------------

def _download_docs(docs: list[dict], prefix: str) -> None:
    for doc in docs:
        try:
            path = abs_data_path(doc["path"])
            content = path.read_bytes()
        except (ValueError, OSError, KeyError):
            continue
        st.download_button(f"📄 {doc['filename']}", content, file_name=doc["filename"], mime="application/pdf",
                           key=f"dl_{prefix}_{doc['id']}")


def _event_detail(cfg: dict, ev: dict, modules_data: dict) -> None:
    mid = ev["module_id"]
    module = get_module(cfg, mid)
    data = modules_data[mid]
    ev_date = date.fromisoformat(ev["date"])
    todo_state = load_todos()
    is_exercise = ev.get("type") in EXERCISE_TYPES

    with st.container(border=True):
        head, close = st.columns([8, 1])
        head.markdown(f"### {module['icon']} {module['name']} – {ev.get('type', '')}")
        close.button("✖", key="close_event", help="Schließen", on_click=lambda: st.session_state.pop("sel_event", None))
        st.caption(f"{WEEKDAYS[ev_date.weekday()]}, {ev_date:%d.%m.%Y} · {ev.get('start', '')}–{ev.get('end', '')} Uhr"
                   f" · {ev.get('room', '')}")

        chapter_id = None
        if is_exercise:
            monday = planner.monday_of(ev_date)
            exercises = planner.exercises_of(module)
            ex = next((e for e in exercises if e["due"] == ev_date), None) or \
                next((e for e in exercises if e["week_of"] == monday), None)
            if ex:
                chapter_id = ex.get("chapter_id")
                st.markdown(f"**✏️ {ex['title']}**")
                key = planner.exercise_key(mid, ex)
                wkey = f"evx_{key}"
                st.session_state[wkey] = bool(todo_state.get(key))
                st.checkbox("Übung vorbereitet / Blatt gelöst", key=wkey, on_change=_toggle_todo,
                            args=({"key": key, "module_id": mid, "chapter_id": chapter_id, "sync": "uebung"}, wkey))
            else:
                st.caption("Für diesen Termin ist im Kursplan kein Übungsblatt hinterlegt.")
        else:
            lecture = next((lec for lec in planner.lectures_of(module) if lec["date"] == ev_date), None)
            if lecture:
                chapter_id = lecture.get("chapter_id")
                st.markdown(f"**🎬 {lecture['topic']}**")
                c1, c2 = st.columns(2)
                for col, field, label in ((c1, "vorbereitet", "Vorbereitet"), (c2, "nachbereitet", "Nachbereitet")):
                    key = planner.lecture_key(mid, ev_date, field)
                    wkey = f"evl_{key}"
                    st.session_state[wkey] = bool(todo_state.get(key))
                    col.checkbox(label, key=wkey, on_change=_toggle_todo,
                                 args=({"key": key, "module_id": mid, "chapter_id": chapter_id, "sync": field}, wkey))
            else:
                st.caption("Für dieses Datum steht im Kursplan keine Vorlesung (z. B. Ausfall oder Ferien).")
        if chapter_id:
            st.caption(f"Kapitel: {chapter_label(data, chapter_id)}")

        tab_files, tab_prep, tab_notes, tab_q = st.tabs(["📂 Dateien", "🎬 Vorbereitung", "📝 Nachbereitung",
                                                         "❓ Fragen fürs Tutorium"])
        docs = [d for d in data["documents"] if chapter_id and d.get("chapter_id") == chapter_id]
        with tab_files:
            if docs:
                _download_docs(docs, f"{mid}_{ev['date']}")
            else:
                st.caption("Noch keine Dateien für dieses Kapitel. Hochladen über 📂 Bulk-Upload oder im Modul.")
        with tab_prep:
            analysed = [d for d in docs if d.get("analysis")]
            if analysed:
                a = analysed[0]["analysis"]
                st.markdown(a.get("summary", ""))
                for i, q in enumerate(a.get("check_questions", [])[:3], start=1):
                    with st.expander(f"❓ {q['question']}"):
                        st.markdown(q["answer"])
            elif docs:
                st.caption("Die Folien sind noch nicht analysiert.")
                if st.button("✨ Folien jetzt analysieren", key=f"evd_an_{mid}_{ev['date']}"):
                    from views.module_tabs.preparation import _run_analysis

                    with st.spinner("Analysiere …"):
                        try:
                            _run_analysis(cfg, mid, docs[0])
                            st.rerun()
                        except ai.AIError as exc:
                            st.error(str(exc))
            else:
                st.caption("Lade zuerst die Folien hoch.")
            st.button("🎬 Vorbereitung im Modul öffnen", key=f"evd_prep_{mid}_{ev['date']}",
                      on_click=open_module_tab, args=(mid, "prep", chapter_id))
        with tab_notes:
            if chapter_id:
                notes = get_notes(data, chapter_id)
                with st.form(f"ev_notes_{mid}_{chapter_id}_{ev['date']}"):
                    text = st.text_area("Notizen", notes["text"], height=120)
                    emphasized = st.text_area("Vom Dozenten betont", notes["emphasized"], height=80)
                    examples = st.text_area("Beispiele", notes["examples"], height=80)
                    if st.form_submit_button("💾 Speichern"):
                        notes.update({"text": text, "emphasized": emphasized, "examples": examples})
                        save_module(mid)
                        st.success("Gespeichert.")
            st.button("📝 Nachbereitung im Modul öffnen", key=f"evd_rev_{mid}_{ev['date']}",
                      on_click=open_module_tab, args=(mid, "review", chapter_id))
        with tab_q:
            from views.module_tabs.notes import question_list

            question_list(mid, data, key_prefix=f"evq_{ev['date']}")


# ---------------------------------------------------------------------------
# Seite
# ---------------------------------------------------------------------------

def _grid_css(cfg: dict) -> None:
    rules = ["[class*='st-key-cell_today_'] {background: rgba(127,127,127,0.16); border-radius: 8px;"
             " padding: 4px 6px;}",
             "[class*='st-key-head_today'] {background: rgba(127,127,127,0.22); border-radius: 8px;"
             " padding: 2px 6px;}",
             "[class*='st-key-ev_'] button {text-align: left; justify-content: flex-start; padding: 4px 8px;"
             " min-height: 0; font-size: 0.82rem; line-height: 1.25;}",
             "[class*='st-key-ev_'] button p {font-size: 0.82rem;}"]
    for m in cfg["modules"]:
        rules.append(f"[class*='st-key-ev_{m['id']}_'] button {{border-left: 5px solid {m['color']};}}")
    st.markdown(f"<style>{' '.join(rules)}</style>", unsafe_allow_html=True)


def render(cfg: dict) -> None:
    now = today()
    settings = load_settings()
    sem_start, sem_end = semester_dates(cfg)
    modules_data = {m["id"]: load_module(m["id"]) for m in cfg["modules"]}
    breaks = lecture_breaks(cfg)
    week_now = planner.semester_week(sem_start, now, breaks)
    _grid_css(cfg)

    st.title("🏠 Wochenübersicht & Lernplan")
    if week_now < 1:
        st.caption(f"Vorlesungsbeginn am {sem_start:%d.%m.%Y}.")
    elif now > sem_end:
        st.caption("Die Vorlesungszeit ist vorbei – Fokus auf Klausurvorbereitung.")
    else:
        st.caption(f"Vorlesungswoche **{week_now}** · {WEEKDAYS[now.weekday()]}, {now:%d.%m.%Y}")

    # --- Woche wählen --------------------------------------------------------
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
    events = [e for e in planner.week_events(schedule, monday)
              if e.get("module_id") in modules_data and sem_start <= e["date"] <= sem_end
              and not planner.break_for(e["date"], breaks)]
    todos = planner.generate_todos(cfg, modules_data, schedule, monday, sem_start, sem_end, settings["learning"], breaks)
    todo_state = load_todos()
    placed: dict[tuple[date, int | None], list[dict]] = {}
    for t in todos:
        placed.setdefault(_placement(t, monday), []).append(t)
    days = [monday + timedelta(days=i) for i in range(7)]

    list_view = st.toggle("📱 Listenansicht (fürs Handy)", key="dash_list_view")
    st.caption("Tippe auf eine Veranstaltung für Dateien, Vor- und Nachbereitung · ↔️ verschiebt ein To-do.")

    # --- Stundenplan-Raster ---------------------------------------------------
    if not list_view:
        widths = [0.55] + [1] * 7
        header = st.columns(widths)
        header[0].markdown("&nbsp;")
        for col, day in zip(header[1:], days):
            with col:
                with st.container(key=f"head_{'today' if day == now else 'day'}_{day:%Y%m%d}"):
                    st.markdown(f"**{WEEKDAYS[day.weekday()][:2]} {day:%d.%m.}**")
                    if planner.break_for(day, breaks):
                        st.caption("🎄 frei")
                    for mid in modules_data:
                        if get_exam_date(mid) == day:
                            st.error(f"📝 Klausur {get_module(cfg, mid)['short']}")
        for slot in SLOTS + [None]:
            row = st.columns(widths)
            row[0].markdown(f"**{SLOT_LABELS[slot]}**" if slot is not None else "**📋 Aufgaben**")
            for col, day in zip(row[1:], days):
                with col:
                    with st.container(key=f"cell_{'today' if day == now else 'day'}_{day:%Y%m%d}_{slot or 'x'}"):
                        if slot is not None:
                            for i, ev in enumerate(e for e in events if e["date"] == day
                                                   and _slot_of(e.get("start", "")) == slot):
                                module = get_module(cfg, ev["module_id"])
                                st.button(f"**{module['icon']} {module['short']}** · {ev.get('type', '')}  \n"
                                          f"{ev.get('start', '')}–{ev.get('end', '')}",
                                          key=f"ev_{ev['module_id']}_{day:%Y%m%d}_{slot}_{i}",
                                          help=ev.get("room", ""), width="stretch",
                                          on_click=_select_event, args=(ev,))
                        for t in placed.get((day, slot), []):
                            _todo_widget(t, cfg, modules_data, todo_state, monday, now,
                                         place=f"g{day:%d}{slot or 0}", compact=True)
    else:
        for day in days:
            day_events = [e for e in events if e["date"] == day]
            day_todos = [t for (d, _s), ts in placed.items() if d == day for t in ts]
            if not day_events and not day_todos:
                continue
            with st.container(key=f"cell_{'today' if day == now else 'day'}_{day:%Y%m%d}_list", border=True):
                st.markdown(f"**{WEEKDAYS[day.weekday()]}, {day:%d.%m.}**")
                for i, ev in enumerate(day_events):
                    module = get_module(cfg, ev["module_id"])
                    st.button(f"**{ev.get('start', '')}–{ev.get('end', '')}** · {module['icon']} {module['short']} · "
                              f"{ev.get('type', '')}", key=f"ev_{ev['module_id']}_{day:%Y%m%d}_l{i}",
                              help=ev.get("room", ""), width="stretch", on_click=_select_event, args=(ev,))
                for t in day_todos:
                    _todo_widget(t, cfg, modules_data, todo_state, monday, now, place=f"l{day:%d}", compact=True)

    if sel := st.session_state.get("sel_event"):
        if sel.get("module_id") in modules_data:
            _event_detail(cfg, sel, modules_data)

    # --- To-do-Liste & Fortschritt ----------------------------------------------
    left, right = st.columns([3, 2], gap="large")
    with left:
        with st.expander(f"✅ Alle To-dos dieser Woche als Liste ({len(todos)})", expanded=False):
            if not todos:
                st.info("Für diese Woche sind keine Aufgaben geplant.")
            open_count = sum(1 for t in todos if not planner.todo_done(t, modules_data, todo_state))
            if todos:
                st.progress(1 - open_count / len(todos), text=f"{len(todos) - open_count} von {len(todos)} erledigt")
            for t in sorted(todos, key=lambda t: t["due"]):
                _todo_widget(t, cfg, modules_data, todo_state, monday, now, place="list", compact=False)
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
                         f"<span class='small-muted'>{rec['reason']}</span>", unsafe_allow_html=True)
            c_b.button("Öffnen", key=f"rec_{rec['module_id']}", on_click=goto, args=(1, rec["module_id"]))
        due_total = sum(r["due"] for r in recs)
        if due_total:
            st.info(f"🃏 Heute insgesamt **{due_total}** Lernkarten fällig.")

    with st.expander("📋 Kapitelstatus aller Module", expanded=False):
        rows = []
        for module in cfg["modules"]:
            for i, ch in enumerate(modules_data[module["id"]]["chapters"], start=1):
                rows.append({"Modul": module["short"], "Kapitel": f"{i}. {ch['title']}",
                             "Vorbereitet": ch["status"]["vorbereitet"],
                             "Nachbereitet": ch["status"]["nachbereitet"], "Übung": ch["status"]["uebung"]})
        st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)

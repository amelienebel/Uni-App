"""🏠 Wochenübersicht & Lernplan."""

from __future__ import annotations

import re
from datetime import date, timedelta

import pandas as pd
import streamlit as st

from utils import planner
from utils.config import WEEKDAYS, get_module, module_label
from utils.storage import (get_exam_date, get_schedule, lecture_breaks,
                           load_module, load_settings, load_todos, save_todos, semester_dates, today)
from views.common import escape, goto, toggle_todo

SLOTS = [8, 10, 12, 14, 16, 18]
SLOT_LABELS = {s: f"{s:02d}–{s + 2:02d}" for s in SLOTS}


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


SHORT_KIND = {
    "Vorbereitung": "VL vorbereiten",
    "Nachbereitung": "VL nachbereiten",
    "Übungsblatt": "Übung vorbereiten",
    "Wiederholung": "Karten wiederholen",
    "Klausurvorbereitung": "Altklausur rechnen",
}


def _short_label(t: dict) -> str:
    if t["kind"] in SHORT_KIND:
        return SHORT_KIND[t["kind"]]
    title = t["title"].split(":")[0].split("(")[0].strip()
    return title if len(title) <= 34 else title[:32] + "…"


def _move_popover(t: dict, monday: date, place: str) -> None:
    with st.popover("↔️", help="Verschieben", type="tertiary"):
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


def _todo_widget(t: dict, cfg: dict, modules_data: dict, todo_state: dict, monday: date, now: date,
                 place: str, compact: bool = False) -> None:
    """Volle Zeile: Abhaken links, Frist in der Mitte, Verschieben rechts."""
    module = get_module(cfg, t["module_id"])
    key = f"todo_{place}_{t['key']}_{monday.isoformat()}"
    done = planner.todo_done(t, modules_data, todo_state)
    st.session_state[key] = done
    overdue = not done and t["due"] < now
    _, slot = _placement(t, monday)
    with st.container(key=f"tdrow_{t['module_id']}_{place}_{re.sub(r'[^0-9A-Za-z]', '_', t['key'])}"):
        c1, c2, c3 = st.columns([7, 3, 1], vertical_alignment="center")
        c1.checkbox(f"{module['icon']} **{module['short']}** · {t['title']}", key=key,
                    on_change=toggle_todo, args=(t, key))
        c2.caption(("⚠️ " if overdue else "") + f"Frist: {planner.format_due(t['due'], now)}"
                   + (f" · geplant {SLOT_LABELS[slot]} Uhr" if slot else ""))
        with c3:
            _move_popover(t, monday, place)


def _todo_chip(t: dict, cfg: dict, modules_data: dict, todo_state: dict, now: date) -> None:
    """Nur-Anzeige im Raster: kleines, gut lesbares Kärtchen (abhaken/verschieben in der Liste darunter)."""
    module = get_module(cfg, t["module_id"])
    done = planner.todo_done(t, modules_data, todo_state)
    overdue = not done and t["due"] < now
    style = "text-decoration: line-through; opacity: 0.55;" if done else ""
    mark = "✓ " if done else ("⚠ " if overdue else "")
    st.markdown(
        f"<div class='todo-chip' title='{escape(t['title'])}' style='border-left-color:{module['color']};{style}'>"
        f"<b>{mark}{escape(module['short'])}</b><br>{escape(_short_label(t))}</div>", unsafe_allow_html=True)


def _open_event(ev: dict) -> None:
    """Klick auf eine Veranstaltung: Details merken und direkt ins Modul springen."""
    _select_event(ev)
    goto(1, ev["module_id"])


def _event_card(cfg: dict, ev: dict, key: str, show_date: bool = False) -> None:
    module = get_module(cfg, ev["module_id"])
    with st.container(key=f"evcard_{ev['module_id']}_{key}"):
        st.button(f"{module['icon']} {module['short']} · {ev.get('type', '')}", key=f"evbtn_{key}",
                  type="tertiary", on_click=_open_event, args=(ev,), help="Vorlesung bzw. Übung mit allen Unterlagen öffnen")
        when = f"{ev.get('start', '')}–{ev.get('end', '')}"
        st.caption(f"{when}  \n{ev.get('room', '')}" if ev.get("room") else when)


# ---------------------------------------------------------------------------
# Seite
# ---------------------------------------------------------------------------

def _grid_css(cfg: dict) -> None:
    rules = ["[class*='st-key-cell_today_'] {background: rgba(127,127,127,0.16); border-radius: 8px;"
             " padding: 4px 6px;}",
             "[class*='st-key-head_today'] {background: rgba(127,127,127,0.22); border-radius: 8px;"
             " padding: 2px 6px;}",
             # Veranstaltungs-Karten
             "[class*='st-key-evcard_'] {background: rgba(127,127,127,0.08); border-radius: 6px;"
             " padding: 4px 8px 6px 8px; gap: 0 !important;}",
             "[class*='st-key-evcard_'] button {padding: 0; min-height: 0; font-weight: 600; text-align: left;}",
             "[class*='st-key-evcard_'] button p {font-size: 0.85rem; font-weight: 600;}",
             "[class*='st-key-evcard_'] [data-testid='stCaptionContainer'] p {font-size: 0.75rem;"
             " line-height: 1.25; margin: 0;}",
             # To-do-Kärtchen im Raster (nur Anzeige)
             ".todo-chip {border: 1px solid rgba(127,127,127,0.25); border-left: 4px solid #888;"
             " border-radius: 6px; padding: 3px 7px; margin: 3px 0; font-size: 0.78rem; line-height: 1.3;}",
             # To-do-Zeilen in der Liste
             "[class*='st-key-tdrow_'] {border-bottom: 1px solid rgba(127,127,127,0.15); padding: 2px 0;}",
             "[class*='st-key-tdrow_'] [data-testid='stPopover'] button {padding: 0 6px; min-height: 0;}"]
    for m in cfg["modules"]:
        rules.append(f"[class*='st-key-evcard_{m['id']}_'] {{border-left: 4px solid {m['color']};}}")
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
    c4.markdown(f"#### Woche {monday:%d.%m.} – {monday + timedelta(days=6):%d.%m.%Y}"
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
    calendar: dict[date, list[str]] = {}
    for entry in cfg["app"].get("calendar", []):
        try:
            calendar.setdefault(date.fromisoformat(entry["date"]), []).append(entry["text"])
        except (KeyError, ValueError):
            continue

    list_view = st.toggle("📱 Listenansicht (fürs Handy)", key="dash_list_view")

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
                            st.error(f"Klausur {get_module(cfg, mid)['short']}")
                    for entry in calendar.get(day, []):
                        st.warning(entry)
        for slot in SLOTS + [None]:
            row = st.columns(widths)
            row[0].markdown(f"**{SLOT_LABELS[slot]}**" if slot is not None else "**Aufgaben**")
            for col, day in zip(row[1:], days):
                with col:
                    with st.container(key=f"cell_{'today' if day == now else 'day'}_{day:%Y%m%d}_{slot or 'x'}"):
                        if slot is not None:
                            for i, ev in enumerate(e for e in events if e["date"] == day
                                                   and _slot_of(e.get("start", "")) == slot):
                                _event_card(cfg, ev, f"{day:%Y%m%d}_{slot}_{i}")
                        for t in placed.get((day, slot), []):
                            _todo_chip(t, cfg, modules_data, todo_state, now)
    else:
        for day in days:
            day_events = [e for e in events if e["date"] == day]
            day_todos = [t for (d, _s), ts in placed.items() if d == day for t in ts]
            if not day_events and not day_todos and not calendar.get(day):
                continue
            with st.container(key=f"cell_{'today' if day == now else 'day'}_{day:%Y%m%d}_list", border=True):
                st.markdown(f"**{WEEKDAYS[day.weekday()]}, {day:%d.%m.}**")
                for entry in calendar.get(day, []):
                    st.warning(entry)
                for i, ev in enumerate(day_events):
                    _event_card(cfg, ev, f"{day:%Y%m%d}_l{i}")
                for t in day_todos:
                    _todo_chip(t, cfg, modules_data, todo_state, now)

    # --- Aufgaben dieser Woche (abhaken & verschieben) ---------------------------
    st.subheader("Aufgaben dieser Woche")
    if not todos:
        st.caption("Für diese Woche sind keine Aufgaben geplant.")
    else:
        open_count = sum(1 for t in todos if not planner.todo_done(t, modules_data, todo_state))
        st.progress(1 - open_count / len(todos), text=f"{len(todos) - open_count} von {len(todos)} erledigt")
        for day in days:
            day_todos = sorted((t for t in todos if _placement(t, monday)[0] == day),
                               key=lambda t: (_placement(t, monday)[1] or 99, t["module_id"]))
            if not day_todos:
                continue
            st.markdown(f"**{WEEKDAYS[day.weekday()]}, {day:%d.%m.}**")
            for t in day_todos:
                _todo_widget(t, cfg, modules_data, todo_state, monday, now, place="list", compact=False)

    st.divider()
    with st.container():
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

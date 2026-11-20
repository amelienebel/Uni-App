"""Wochenübersicht."""

from __future__ import annotations

import re
from datetime import date, timedelta

import pandas as pd
import streamlit as st

from utils import planner
from utils import spaced_repetition as sr
from utils.config import WEEKDAYS, get_module
from utils.storage import (chapter_number, days_until_exam, get_exam_date, get_schedule, lecture_breaks,
                           load_module, load_settings, load_todos, save_todos, semester_dates, today)
from views import cards_center
from views.common import park_button, parked_list, NEXT_GROUP, grouped, group_header, prio_button, prio_of, kind_icon, todo_text, custom_todo_form, delete_custom_todo, goto, micon, open_todo, todo_module, toggle_todo

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
    """Tag/Zeitfenster eines To-dos: eigene Planung, sonst Frist (auf die angezeigte Woche begrenzt);
    Liegengebliebenes aus früheren Wochen steht bei heute."""
    plan = _plans().get(todo["key"])
    if plan:
        try:
            planned = date.fromisoformat(plan["date"])
            if not todo.get("carried") or planned >= monday:
                return planned, plan.get("slot")
        except (KeyError, ValueError):
            pass
    if todo.get("carried"):
        return min(max(today(), monday), monday + timedelta(days=6)), None
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
    "Übungsblatt": "Übungsblatt lösen",
    "Wiederholung": "Karten wiederholen",
    "Klausurvorbereitung": "Altklausur rechnen",
    "Wochentraining": "Wochentraining",
}


def _short_label(t: dict) -> str:
    if t.get("chip"):
        return t["chip"]
    if t["kind"] in SHORT_KIND:
        return SHORT_KIND[t["kind"]]
    title = t["title"].split(":")[0].split("(")[0].strip()
    return title if len(title) <= 34 else title[:32] + "…"


def _move_popover(t: dict, monday: date, place: str) -> None:
    with st.popover("", icon=":material/swap_horiz:", help="Verschieben", type="tertiary"):
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
        if t.get("custom"):
            st.button("Löschen", key=f"mvdel_{place}_{t['key']}", icon=":material/delete:",
                      on_click=delete_custom_todo, args=(t["key"],))


def _todo_widget(t: dict, cfg: dict, modules_data: dict, todo_state: dict, monday: date, now: date,
                 place: str, compact: bool = False, with_kind: bool = False) -> None:
    """Volle Zeile: Abhaken links, Frist in der Mitte, Verschieben rechts."""
    module = todo_module(cfg, t)
    key = f"todo_{place}_{t['key']}_{monday.isoformat()}"
    done = planner.todo_done(t, modules_data, todo_state)
    st.session_state[key] = done
    _, slot = _placement(t, monday)
    with st.container(key=f"tdrow_{module['id']}_{place}_{re.sub(r'[^0-9A-Za-z]', '_', t['key'])}"):
        c0, c1, c2, c3 = st.columns([0.5, 7, 3, 1.5], vertical_alignment="center")
        c0.checkbox("Erledigt", key=key, on_change=toggle_todo, args=(t, key), label_visibility="collapsed")
        c1.button(f"**{module['short']}** · " + (f"{kind_icon(t['kind'])} " if with_kind else "") + todo_text(t),
                  key=f"open_{key}", type="tertiary", icon=micon(module), on_click=open_todo, args=(t,),
                  help=t["title"])
        c2.caption(f"Frist: {planner.format_due(t['due'], now)}"
                   + (f" · geplant {SLOT_LABELS[slot]} Uhr" if slot else ""))
        with c3.container(horizontal=True, gap="small"):
            prio_button(st, t["key"], key)
            park_button(st, t, key, now)
            _move_popover(t, monday, place)


def _todo_chip(t: dict, cfg: dict, modules_data: dict, todo_state: dict, now: date, key: str) -> None:
    """Kärtchen im Raster – Antippen öffnet die passende Vorlesung/Übung (abhaken in der Liste darunter)."""
    module = todo_module(cfg, t)
    done = planner.todo_done(t, modules_data, todo_state)
    overdue = not done and t["due"] < now
    mark = ":material/check: " if done else (":material/schedule: " if overdue else "")
    state = "done" if done else "open"
    with st.container(key=f"chip_{state}_{module['id']}_{key}"):
        prio = prio_of(t["key"])
        st.button(f"{mark}**{module['short']}**" + (f" · {prio}" if prio else "")
                  + f"  \n{kind_icon(t['kind'])} {_short_label(t)}", key=f"chipbtn_{key}",
                  type="tertiary",
                  on_click=open_todo, args=(t,), help=t["title"])


def _card_counts(modules_data: dict, day: date, now: date, new_min: int) -> dict[str, int]:
    """Karteikarten pro Modul an einem Tag: heute fällige + neue, später die dann fälligen Wiederholungen."""
    if day < now:
        return {}
    counts = {}
    for mid, data in modules_data.items():
        if day == now:
            plan = sr.daily_plan(data["cards"], days_until_exam(mid), new_min)
            n = plan["reviews"] + plan["new"]
        else:
            n = sum(1 for c in data["cards"] if not sr.is_new(c) and c["due"][:10] == day.isoformat())
        if n:
            counts[mid] = n
    return counts


def _card_chip(cfg: dict, mid: str, n: int, today_chip: bool, key: str) -> None:
    module = get_module(cfg, mid)
    with st.container(key=f"chip_open_{mid}_{key}"):
        if today_chip:
            st.button(f"**{module['short']}**  \n{n} Karten", key=f"cardchip_{key}", type="tertiary",
                      on_click=cards_center.learn_due, args=(cfg, mid), help="Jetzt lernen")
        else:
            st.markdown(f"**{module['short']}**  \n{n} Karten")


def _open_event(ev: dict) -> None:
    """Klick auf eine Veranstaltung: Details merken und direkt ins Modul springen."""
    _select_event(ev)
    goto("module", ev["module_id"])


def _event_card(cfg: dict, ev: dict, key: str, show_date: bool = False) -> None:
    module = get_module(cfg, ev["module_id"])
    with st.container(key=f"evcard_{ev['module_id']}_{key}"):
        room = ev.get("room", "")
        # eine kompakte Zeile: Modul · Art · Zeit (Raum nur beim Drüberfahren)
        st.button(f"**{module['short']}** {ev.get('type', '')}  \n{_short_time(ev)}", key=f"evbtn_{key}",
                  type="tertiary", on_click=_open_event, args=(ev,), help=room or None)


def _short_time(ev: dict) -> str:
    """„10:00–12:00“ → „10–12“ (Minuten nur, wenn nicht volle Stunde)."""
    def part(t: str) -> str:
        return t[:-3] if t.endswith(":00") else t
    return f"{part(ev.get('start', ''))}–{part(ev.get('end', ''))}"


# ---------------------------------------------------------------------------
# Seite
# ---------------------------------------------------------------------------

def _grid_css(cfg: dict) -> None:
    rules = ["[class*='st-key-cell_'] {min-height: 1.6rem; padding: 2px 3px; gap: 0.25rem !important;}",
             ".st-key-ttgrid {gap: 0.3rem !important;}",
             ".st-key-ttgrid [data-testid='stHorizontalBlock'] {gap: 0.4rem !important;}",
             ".st-key-ttgrid [data-testid='stMarkdownContainer'] p {font-size: 0.85rem; margin: 0;}",
             "[class*='st-key-cell_today_'] {background: rgba(127,127,127,0.16); border-radius: 8px;"
             " padding: 4px 6px;}",
             "[class*='st-key-head_today'] {background: rgba(127,127,127,0.22); border-radius: 8px;"
             " padding: 2px 6px;}",
             # Veranstaltungs-Karten
             "[class*='st-key-evcard_'] {background: rgba(127,127,127,0.08); border-radius: 6px;"
             " padding: 2px 6px; gap: 0 !important;}",
             "[class*='st-key-evcard_'] button {padding: 0; min-height: 0; text-align: left;"
             " justify-content: flex-start;}",
             "[class*='st-key-evcard_'] button div {justify-content: flex-start; text-align: left;}",
             "[class*='st-key-evcard_'] button p {font-size: 0.8rem; line-height: 1.25; font-weight: 400;}",
             "[class*='st-key-evcard_'] [data-testid='stCaptionContainer'] p {font-size: 0.82rem;"
             " line-height: 1.3; margin: 0;}",
             # To-do-Kärtchen im Raster (antippen = öffnen)
             "[class*='st-key-chip_'] {border: 1px solid rgba(127,127,127,0.25); border-left: 4px solid #888;"
             " border-radius: 6px; padding: 4px 8px; gap: 0 !important;}",
             "[class*='st-key-chip_'] button {padding: 0; min-height: 0; text-align: left; justify-content: flex-start;}",
             "[class*='st-key-chip_'] button div {justify-content: flex-start; text-align: left;}",
             "[class*='st-key-chip_'] button p {font-size: 0.86rem; line-height: 1.3;}",
             "[class*='st-key-chip_done_'] {opacity: 0.55;}",
             "[class*='st-key-chip_done_'] button p {text-decoration: line-through;}",
             "[class*='st-key-tdrow_'] button {text-align: left; justify-content: flex-start;}",
             "[class*='st-key-tdrow_'] button div {justify-content: flex-start; text-align: left;}",
             # To-do-Zeilen in der Liste
             "[class*='st-key-tdrow_'] {border-bottom: 1px solid rgba(127,127,127,0.15); padding: 2px 0 2px 0.9rem;}",
             "[class*='st-key-tdrow_'] [data-testid='stPopover'] button {padding: 0 6px; min-height: 0;}"]
    for m in cfg["modules"]:
        rules.append(f"[class*='st-key-evcard_{m['id']}_'] {{border-left: 4px solid {m['color']};}}")
        rules.append(f"[class*='st-key-chip_open_{m['id']}_'], [class*='st-key-chip_done_{m['id']}_'] "
                     f"{{border-left-color: {m['color']};}}")
    st.markdown(f"<style>{' '.join(rules)}</style>", unsafe_allow_html=True)


def render(cfg: dict) -> None:
    now = today()
    settings = load_settings()
    sem_start, sem_end = semester_dates(cfg)
    modules_data = {m["id"]: load_module(m["id"]) for m in cfg["modules"]}
    breaks = lecture_breaks(cfg)
    week_now = planner.semester_week(sem_start, now, breaks)
    _grid_css(cfg)

    st.title(":material/calendar_month: Wochenübersicht")
    if week_now < 1:
        st.caption(f"Vorlesungsbeginn am {sem_start:%d.%m.%Y}.")
    elif now > sem_end:
        st.caption("Die Vorlesungszeit ist vorbei – Fokus auf Klausurvorbereitung.")
    else:
        st.caption(f"Vorlesungswoche **{week_now}** · {WEEKDAYS[now.weekday()]}, {now:%d.%m.%Y}")

    # --- Woche wählen --------------------------------------------------------
    offset = st.session_state.setdefault("week_offset", 0)
    monday = planner.monday_of(now) + timedelta(weeks=offset)
    week_no = planner.semester_week(sem_start, monday, breaks)
    st.markdown(f"#### Woche {monday:%d.%m.} – {monday + timedelta(days=6):%d.%m.%Y}"
                + (" · vorlesungsfrei" if planner.is_break_week(monday, breaks)
                   else f" · Vorlesungswoche {week_no}" if 1 <= week_no and monday <= sem_end else ""))
    c1, c2, c3, _ = st.container(key="weeknav").columns([1, 1, 1, 4])
    if c1.button("Vorwoche", icon=":material/chevron_left:", width="stretch"):
        st.session_state["week_offset"] = offset - 1
        st.rerun()
    if c2.button("Heute", width="stretch"):
        st.session_state["week_offset"] = 0
        st.rerun()
    if c3.button("Nächste", icon=":material/chevron_right:", width="stretch"):
        st.session_state["week_offset"] = offset + 1
        st.rerun()

    schedule = get_schedule(cfg)
    todos = planner.generate_todos(cfg, modules_data, schedule, monday, sem_start, sem_end, settings["learning"], breaks)
    todo_state = load_todos()
    if monday <= now <= monday + timedelta(days=6):  # Liegengebliebenes aus früheren Wochen wandert mit
        known = {t["key"] for t in todos}
        todos += [t for t in planner.overdue_before(cfg, modules_data, schedule, monday, sem_start, sem_end,
                                                    settings["learning"], todo_state, breaks) if t["key"] not in known]
        todos += [{**t, "carried": True} for t in planner.custom_todos(todo_state, None, monday - timedelta(days=1))
                  if not planner.todo_done(t, modules_data, todo_state)]
    todos += planner.custom_todos(todo_state, monday, monday + timedelta(days=6))
    todos = [t for t in todos if t["kind"] != "Wiederholung"]  # Karteikarten haben eine eigene Zeile
    parked = [t for t in todos if planner.is_parked(todo_state, t["key"])
              and not planner.todo_done(t, modules_data, todo_state)]
    todos = [t for t in todos if t not in parked]
    days = [monday + timedelta(days=i) for i in range(7)]
    calendar: dict[date, list[str]] = {}
    for entry in cfg["app"].get("calendar", []):
        try:
            calendar.setdefault(date.fromisoformat(entry["date"]), []).append(entry["text"])
        except (KeyError, ValueError):
            continue

    if planner.LEARNING_V2:  # je Modul: wo stehe ich im Wochenablauf (Upload bis Wochentraining)
        from views import progress

        progress.week_boards(cfg, monday, key=f"w{monday:%Y%m%d}")

    # Stundenplan nur noch auf „Heute“ – hier nur Klausuren und Kalender-Hinweise der Woche
    for day in days:
        notes = [f"Klausur {get_module(cfg, mid)['short']}" for mid in modules_data if get_exam_date(mid) == day]
        notes += calendar.get(day, [])
        for note in notes:
            st.warning(f"{WEEKDAYS[day.weekday()]}, {day:%d.%m.}: {note}")
    if not planner.LEARNING_V2:  # altes System: Karteikarten je Tag
        new_min = int(settings["learning"].get("new_per_day", sr.DEFAULT_NEW_PER_DAY))
        for day in days:
            counts = _card_counts(modules_data, day, now, new_min)
            if counts:
                st.caption(f"Karteikarten · {WEEKDAYS[day.weekday()]}, {day:%d.%m.}")
                for mid, n in counts.items():
                    _card_chip(cfg, mid, n, day == now, f"{day:%Y%m%d}_c_{mid}")

    # --- Aufgaben dieser Woche (abhaken & verschieben) ---------------------------
    h1, h2 = st.columns([3, 1], vertical_alignment="bottom")
    h1.subheader(":material/checklist: Aufgaben dieser Woche")
    with h2:
        custom_todo_form(cfg, f"week_new_{monday.isoformat()}",
                         now if monday <= now <= monday + timedelta(days=6) else monday)
    if not todos:
        st.caption("Für diese Woche sind keine Aufgaben geplant.")
    else:
        open_count = sum(1 for t in todos if not planner.todo_done(t, modules_data, todo_state))
        st.progress(1 - open_count / len(todos), text=f"{len(todos) - open_count} von {len(todos)} erledigt")
        for day in days:
            day_todos = [t for t in todos if _placement(t, monday)[0] == day]
            if not day_todos:
                continue
            st.markdown(f"#### {WEEKDAYS[day.weekday()]}, {day:%d.%m.}")
            for name, items in grouped(day_todos):
                group_header(name, len(items))
                for t in items:
                    _todo_widget(t, cfg, modules_data, todo_state, monday, now, place="list", compact=False,
                                 with_kind=name == NEXT_GROUP)
    parked_list(cfg, parked, f"week_{monday.isoformat()}")

    st.divider()
    with st.expander("Kapitelstatus aller Module", expanded=False):
        rows = []
        for module in cfg["modules"]:
            for ch in modules_data[module["id"]]["chapters"]:
                nr = chapter_number(modules_data[module["id"]], ch["id"])
                rows.append({"Modul": module["short"], "Kapitel": f"{nr}. {ch['title']}",
                             **({"Vorbereitet": ch["status"]["vorbereitet"]} if planner.PREP_ENABLED else {}),
                             "Nachbereitet": ch["status"]["nachbereitet"], "Übung": ch["status"]["uebung"]})
        st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)

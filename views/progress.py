"""Fortschritts-Bausteine: Schritte je Vorlesung, Abdeckung, Wissensstand-Chips (ohne Emojis)."""

from __future__ import annotations

import html
from datetime import date, datetime, timedelta

import streamlit as st

from utils import mastery, planner, sessions, topics
from utils.storage import get_schedule, lecture_breaks, today

STEP_NAMES = ("Upload", "Nacharbeit", "Check 1", "Übungsblatt", "Check 2", "Wochentraining")
_STEP_CSS = {"done": "step-done", "open": "step-open", "overdue": "step-late", "na": "step-na",
             "optional": "step-optional", "parked": "step-optional"}
_STEP_ICON = {"done": "check", "open": "radio_button_unchecked", "overdue": "schedule", "na": "remove",
              "optional": "radio_button_unchecked", "parked": "pause_circle"}


def _finished_dates(data: dict, kind: str) -> list[date]:
    out = []
    for s in sessions.finished(data, kind):
        try:
            out.append(datetime.fromisoformat(s["finished_at"]).date())
        except (TypeError, ValueError):
            continue
    return out


def lecture_steps(cfg: dict, module: dict, data: dict, lec: dict, exs: list[dict], state: dict,
                  with_keys: bool = False) -> list[tuple]:
    """[(Name, Status, Ziel)] in fester Reihenfolge Upload · Nacharbeit · Check 1 · Übungsblatt · Check 2 ·
    Wochentraining; Status done / open / overdue / na; Ziel = wohin ein Klick führt. `with_keys` hängt die
    To-do-Schlüssel des Schritts an (zum Zurückstellen)."""
    from utils import nacharbeit

    now = today()
    module_id = module["id"]
    schedule, breaks = get_schedule(cfg), lecture_breaks(cfg)

    def due(step: str) -> date:
        return planner.step_due(module, lec["date"], step)

    def status(done: bool, due_: date | None, optional: bool = False, todo_key: str | None = None) -> str:
        if done:
            return "done"
        if optional:  # frühere Vorlesung: freiwillig, ohne Frist
            return "optional"
        if due_ and due_ < now:
            return "parked" if todo_key and planner.is_parked(state, todo_key) else "overdue"
        return "open"

    def lkey(field: str) -> str:
        return planner.lecture_key(module_id, lec["date"], field)

    def key(field: str) -> bool:
        return bool(state.get(lkey(field)))

    legacy = sessions.is_legacy(data, lec["id"])
    whole = sessions.single_check(data, lec["id"])
    keys = {"Upload": [lkey("nachbereitet")], "Nacharbeit": [lkey("nacharbeit")], "Check 1": [lkey("check")],
            "Check 2": [lkey("check2")]}
    steps = [("Upload", status(key("nachbereitet"), due("upload"), todo_key=lkey("nachbereitet")),
              ("lecture", "nachbereitet"))]
    steps.append(("Nacharbeit", status(key("nacharbeit") or nacharbeit.has_summary(data, lec["id"]),
                                       due("nacharbeit"), legacy or whole, lkey("nacharbeit")), ("lecture", "nacharbeit")))
    steps.append(("Check 1", status(key("check") or sessions.check_done(data, lec["id"], 1), due("check1"), legacy,
                                    lkey("check")), ("check", 1)))
    sheet = planner.lecture_sheet(module, lec, schedule, breaks)
    ex = next((e for e in exs if sheet and e.get("index") == sheet["index"]), None)
    if ex:
        sheets = [e for e in exs if e.get("index") == ex["index"]]  # mit Tutoriumsblatt (VWL): beide gelöst
        undone = [e["plan_key"] for e in sheets if not state.get(e["plan_key"])]
        parked = bool(undone) and all(planner.is_parked(state, k) for k in undone)
        keys["Übungsblatt"] = undone
        steps.append(("Übungsblatt", status(not undone, due("uebung"), todo_key=undone[0] if parked else None),
                      ("exercise", next((e["id"] for e in sheets if not state.get(e["plan_key"])), ex["id"]))))
    else:
        steps.append(("Übungsblatt", "na", None))
    no_second = topics.minitopics(data, lec["id"]) and not sessions.halves(data, lec["id"])[1]
    steps.append(("Check 2", "na" if no_second or (whole and not sessions.check_done(data, lec["id"], 2)) else
                  status(key("check2") or sessions.check_done(data, lec["id"], 2), due("check2"), legacy,
                         lkey("check2")),
                  ("check", 2)))
    window = next((w for w in planner.training_windows(cfg, module, schedule, breaks)
                   if w.get("lecture_date") == lec["date"]), None)
    if window:
        keys["Wochentraining"] = [window["key"]]
        trained = bool(state.get(window["key"])) or any(d >= window["start"] for d in _finished_dates(data, "training"))
        steps.append(("Wochentraining", status(trained, window["due"], todo_key=window["key"]), ("training", None)))
    else:
        steps.append(("Wochentraining", "na", ("training", None)))
    if with_keys:
        return [(name, st_, target, keys.get(name, [])) for name, st_, target in steps]
    return steps


STEP_ICONS = {"Upload": "upload_file", "Nacharbeit": "forum", "Check 1": "fact_check", "Übungsblatt": "assignment",
              "Check 2": "fact_check", "Wochentraining": "fitness_center"}


def _go(module_id: str, lec_id: str, target: tuple) -> None:
    from views import session_ui
    from views.common import LECTURE_TAB, PAGES, open_training, open_unit

    kind, arg = target
    if kind == "training":
        open_training(module_id)
    elif kind == "exercise":
        open_unit(module_id, arg)
    elif kind == "check":
        from utils.storage import load_module

        run = sessions.running_check(load_module(module_id), lec_id, arg)
        if run:  # angefangenen Check direkt fortsetzen
            session_ui.open_session(module_id, run["id"])
            st.session_state["nav"] = PAGES["cards"]
            return
        st.session_state[f"ltab_next_{lec_id}"] = LECTURE_TAB["check"]
        open_unit(module_id, lec_id)
    else:
        st.session_state[f"ltab_next_{lec_id}"] = LECTURE_TAB[arg]
        open_unit(module_id, lec_id)


def step_buttons(module_id: str, lec: dict, steps: list[tuple], key: str) -> None:
    """Schritte als anklickbare Pillen: führt direkt zu Upload, Nacharbeit, Check 1/2, Übungsblatt, Wochentraining."""
    with st.container(horizontal=True, gap="small", key=f"steps_{key}"):
        for i, (name, state_, target) in enumerate(steps):
            icon = {"done": "check", "overdue": "schedule", "parked": "pause_circle"}.get(state_, STEP_ICONS[name])
            st.button(name, key=f"stp_{state_}_{key}_{i}", icon=f":material/{icon}:", width="content",
                      disabled=target is None or state_ == "na", on_click=_go if target else None,
                      args=(module_id, lec["id"], target) if target else None)


def steps_html(steps: list[tuple]) -> str:
    pills = []
    for name, st_, *_ in steps:
        pills.append(f"<span class='step-pill {_STEP_CSS[st_]}'><span class='material-symbols-rounded'>"
                     f"{_STEP_ICON[st_]}</span>{html.escape(name)}</span>")
    return "<div class='step-row'>" + "".join(pills) + "</div>"


def chips_html(data: dict, mts: list[dict], limit: int | None = None) -> str:
    out = []
    for mt in mts[:limit] if limit else mts:
        s = mastery.status(data, mt)
        color = mastery.STATUS_COLORS[s]
        ex = mastery.in_exercise(data, mt)  # kam im Übungsblatt dran → Symbol
        out.append(f"<span class='mt-chip' style='border-color:{color};background:{color}1f' "
                   f"title='{html.escape(s)}{' · im Übungsblatt' if ex else ''}'>"
                   + ("<span class='material-symbols-rounded mt-ex'>assignment</span>" if ex else "")
                   + f"{html.escape(mt['title'])}</span>")
    return "<div class='mt-chips'>" + "".join(out) + "</div>"


def legend_html() -> str:
    return "<div class='mt-legend'>" + "".join(
        f"<span><i style='background:{c}'></i>{html.escape(s)}</span>" for s, c in mastery.STATUS_COLORS.items()) \
        + "</div>"


def module_stats(data: dict, lec_ids: set[str] | None = None) -> dict:
    mts = [m for m in topics.minitopics(data) if lec_ids is None or m["lecture_id"] in lec_ids]
    counts = {s: 0 for s in mastery.STATUS_ORDER}
    for m in mts:
        counts[mastery.status(data, m)] += 1
    asked, total = mastery.coverage(data, mts)
    avg = sum(mastery.score(data, m) for m in mts) / len(mts) if mts else 0.0
    return {"total": total, "asked": asked, "counts": counts, "score": avg}


def status_bar_html(counts: dict) -> str:
    total = sum(counts.values()) or 1
    parts = "".join(f"<i style='width:{counts[s] / total * 100:.1f}%;background:{mastery.STATUS_COLORS[s]}' "
                    f"title='{s}: {counts[s]}'></i>" for s in mastery.STATUS_ORDER if counts[s])
    return f"<div class='status-bar'>{parts}</div>"


def render_status(data: dict, lec_ids: set[str] | None = None) -> None:
    stats = module_stats(data, lec_ids)
    if not stats["total"]:
        return
    st.markdown(status_bar_html(stats["counts"]) + legend_html(), unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Wochenablauf je Modul (Modulseite und Wochenübersicht)
# ---------------------------------------------------------------------------

def week_cycle(cfg: dict, module: dict, data: dict, lecs: list[dict], exs: list[dict], state: dict,
               monday: date) -> dict:
    """Vorlesungen, deren Schritte in die Woche ab `monday` fallen (Upload dieser Woche und der Vorwoche, deren
    Check 2 und Wochentraining jetzt dran sind), plus Liegengebliebenes aus früheren Vorlesungen."""
    sunday = monday + timedelta(days=6)
    current, stuck = [], []
    for lec in lecs:
        if lec["is_break"]:
            continue
        start = planner.step_due(module, lec["date"], "upload")
        end = planner.step_due(module, lec["date"], "training")
        if start > sunday:
            continue
        steps = lecture_steps(cfg, module, data, lec, exs, state, with_keys=True)
        if end >= monday:
            current.append((lec, [s[:3] for s in steps]))
        elif monday <= today() + timedelta(days=6):  # nur bis zur aktuellen Woche: was ist hängen geblieben?
            late = [s for s in steps if s[1] == "overdue"]
            if late:
                stuck.append((lec, late))
    return {"current": current, "stuck": stuck}


def _cycle_counts(cycle: dict) -> tuple[int, int, int]:
    steps = [s for _, ss in cycle["current"] for s in ss if s[1] not in ("na", "optional", "parked")]
    done = sum(1 for s in steps if s[1] == "done")
    return done, len(steps), sum(len(ss) for _, ss in cycle["stuck"])


def _park_steps(keys: list[str]) -> None:
    from views.common import set_parked

    for k in keys:
        set_parked(k, True)


def _lecture_label(lec: dict) -> str:
    from utils.config import WEEKDAYS_SHORT

    return f"VL {lec['nr']} · {WEEKDAYS_SHORT[lec['date'].weekday()]} {lec['date']:%d.%m.}"


def week_board(cfg: dict, module: dict, data: dict, lecs: list[dict], exs: list[dict], state: dict, monday: date,
               key: str, with_title: bool = True) -> None:
    """Karte: wo stehe ich im Wochenablauf (Upload bis Wochentraining) – alles anklickbar."""
    from views.common import micon, open_unit

    module_id = module["id"]
    cycle = week_cycle(cfg, module, data, lecs, exs, state, monday)
    done, total, late = _cycle_counts(cycle)
    with st.container(border=True, key=f"board_{module_id}_{key}"):
        h1, h2 = st.columns([3, 2], vertical_alignment="center")
        if with_title:
            h1.button(f"**{module['short']}**", key=f"bdhead_{module_id}_{key}", type="tertiary", icon=micon(module),
                      on_click=open_unit, args=(module_id, None), help=module["name"])
        else:
            h1.markdown(f"<div class='board-title'>Diese Woche · {monday:%d.%m.} – "
                        f"{monday + timedelta(days=6):%d.%m.}</div>", unsafe_allow_html=True)
        badge = f"{done}/{total} erledigt" if total else "frei"
        h2.markdown(f"<div class='board-count'>{badge}"
                    + (f"<span class='board-late'>{late} hängt</span>" if late else "") + "</div>",
                    unsafe_allow_html=True)
        if total:
            st.markdown(f"<div class='board-bar'><i style='width:{done / total * 100:.0f}%'></i></div>",
                        unsafe_allow_html=True)
        if not cycle["current"]:
            st.caption("Diese Woche keine Vorlesung.")
        for lec, steps in cycle["current"]:
            safe = lec["id"].replace(":", "_")
            with st.container(key=f"bdlec_{module_id}_{key}_{safe}"):
                st.button(f"{_lecture_label(lec)}  \n{lec['topic']}", key=f"bdopen_{module_id}_{key}_{safe}",
                          type="tertiary", on_click=open_unit, args=(module_id, lec["id"]), help=lec["topic"])
                step_buttons(module_id, lec, steps, key=f"bd_{module_id}_{key}_{safe}")
        if cycle["stuck"]:
            with st.container(key=f"bdstuck_{module_id}_{key}"):
                with st.expander(f"Aus früheren Wochen · {late} offen", icon=":material/history:",
                                 expanded=late <= 4):
                    for lec, steps in cycle["stuck"]:
                        safe = lec["id"].replace(":", "_")
                        with st.container(horizontal=True, gap="small", vertical_alignment="center",
                                          key=f"bdold_{module_id}_{key}_{safe}"):
                            st.button(f"VL {lec['nr']}", key=f"bdoldopen_{module_id}_{key}_{safe}", type="tertiary",
                                      on_click=open_unit, args=(module_id, lec["id"]), help=lec["topic"])
                            for i, (name, state_, target, keys) in enumerate(steps):
                                st.button(name, key=f"stp_{state_}_bdo_{module_id}_{key}_{safe}_{i}",
                                          icon=f":material/{STEP_ICONS[name]}:", width="content",
                                          on_click=_go if target else None,
                                          args=(module_id, lec["id"], target) if target else None)
                                if keys:
                                    st.button("", key=f"bdpark_{module_id}_{key}_{safe}_{i}",
                                              icon=":material/pause_circle:", type="tertiary",
                                              help=f"{name} zurückstellen", on_click=_park_steps, args=(keys,))
                    all_keys = [k for _, steps in cycle["stuck"] for *_, keys in steps for k in keys]
                    if all_keys:
                        st.button("Alle zurückstellen", key=f"bdparkall_{module_id}_{key}", type="tertiary",
                                  icon=":material/pause_circle:", on_click=_park_steps, args=(all_keys,))


def week_boards(cfg: dict, monday: date, key: str) -> None:
    """Alle Module nebeneinander (umbrechend) – oben in der Wochenübersicht."""
    from utils import units
    from utils.storage import load_module, load_todos

    state = load_todos()
    with st.container(horizontal=True, gap="medium", key=f"wkboards_{key}"):
        for module in cfg["modules"]:
            data = load_module(module["id"])
            lecs, exs = units.all_units(cfg, module, data)
            week_board(cfg, module, data, lecs, exs, state, monday, key)

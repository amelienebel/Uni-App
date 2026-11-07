"""Fortschritts-Bausteine: Schritte je Vorlesung, Abdeckung, Wissensstand-Chips (ohne Emojis)."""

from __future__ import annotations

import html
from datetime import date, datetime, timedelta

import streamlit as st

from utils import mastery, planner, sessions, topics
from utils.storage import get_schedule, lecture_breaks, today

STEP_NAMES = ("Nacharbeiten", "Check", "Übungsblatt", "Wochentraining")
_STEP_CSS = {"done": "step-done", "open": "step-open", "overdue": "step-late", "na": "step-na"}
_STEP_ICON = {"done": "check", "open": "radio_button_unchecked", "overdue": "schedule", "na": "remove"}


def _finished_dates(data: dict, kind: str) -> list[date]:
    out = []
    for s in sessions.finished(data, kind):
        try:
            out.append(datetime.fromisoformat(s["finished_at"]).date())
        except (TypeError, ValueError):
            continue
    return out


def lecture_steps(cfg: dict, module: dict, data: dict, lec: dict, exs: list[dict], state: dict) -> list[tuple]:
    """[(Name, Status, Ziel)] mit Status done / open / overdue / na; Ziel = wohin ein Klick führt."""
    now = today()
    module_id = module["id"]
    review = planner.review_due(module, lec["date"])

    def status(done: bool, due: date | None) -> str:
        if done:
            return "done"
        return "overdue" if due and due < now else "open"

    steps = [("Nacharbeiten", status(bool(state.get(planner.lecture_key(module_id, lec["date"], "nachbereitet"))),
                                     review), ("lecture", "nachbereitet"))]
    if sessions.is_legacy(data, lec["id"]):
        steps.append(("Check", "na", ("lecture", "check")))
    else:
        steps.append(("Check", status(bool(state.get(planner.lecture_key(module_id, lec["date"], "check")))
                                      or sessions.check_done(data, lec["id"]), review), ("lecture", "check")))
    schedule, breaks = get_schedule(cfg), lecture_breaks(cfg)
    related = [ex for ex in exs if ex.get("chapter_id") and ex["chapter_id"] == lec.get("chapter_id")]
    if related:
        ex = related[-1]
        ex_due = planner.exercise_due(module, ex, schedule, breaks)
        steps.append(("Übungsblatt", status(bool(state.get(ex["plan_key"])), ex_due), ("exercise", ex["id"])))
        trained = any(d >= ex_due - timedelta(days=3) for d in _finished_dates(data, "training"))
        nxt = next((w for w in planner.training_windows(cfg, module, schedule, breaks) if w["due"] >= ex_due), None)
        steps.append(("Wochentraining", status(trained, nxt["due"] if nxt else None), ("training", None)))
    else:
        steps += [("Übungsblatt", "na", None), ("Wochentraining", "na", ("training", None))]
    return steps


STEP_ICONS = {"Nacharbeiten": "edit_note", "Check": "fact_check", "Übungsblatt": "assignment",
              "Wochentraining": "fitness_center"}


def _go(module_id: str, lec_id: str, target: tuple) -> None:
    from views import session_ui
    from views.common import LECTURE_TAB, PAGES, open_training, open_unit

    kind, arg = target
    if kind == "training":
        open_training(module_id)
    elif kind == "exercise":
        open_unit(module_id, arg)
    elif kind == "lecture" and arg == "check":
        from utils.storage import load_module

        run = sessions.running(load_module(module_id), "check", lec_id)
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
    """Schritte als anklickbare Pillen: führt direkt zu Nacharbeiten, Check, Übungsblatt oder Wochentraining."""
    with st.container(horizontal=True, gap="small", key=f"steps_{key}"):
        for i, (name, state_, target) in enumerate(steps):
            icon = "check" if state_ == "done" else "schedule" if state_ == "overdue" else STEP_ICONS[name]
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
        out.append(f"<span class='mt-chip' style='border-color:{color};background:{color}1f' "
                   f"title='{html.escape(s)}'>{html.escape(mt['title'])}</span>")
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

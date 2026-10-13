"""Reiter „Ablauf“: Kapitel mit ihren Vorlesungen, Übungen und Tutorien – jede Zeile öffnet die Detailseite."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from utils import planner
from utils.config import WEEKDAYS_SHORT
from utils.storage import (CHAPTER_STATUS_FIELDS, chapter_label, get_schedule, lecture_breaks, load_module, load_todos,
                           new_id, save_module, today)
from utils.units import session_text, short_label, unit_cards, unit_docs
from views.common import open_unit, toggle_todo


def _mark(ok: bool) -> str:
    return "✓" if ok else "○"


def _due(d) -> str:
    return f"{WEEKDAYS_SHORT[d.weekday()]} {d:%d.%m.}"


def _check(col, label: str, todo: dict, state: dict, wkey: str) -> None:
    st.session_state[wkey] = bool(state.get(todo["key"]))
    col.checkbox(label, key=wkey, on_change=toggle_todo, args=(todo, wkey))


def _lecture_row(module: dict, data: dict, lec: dict, state: dict, is_next: bool) -> None:
    module_id = module["id"]
    docs = unit_docs(data, lec)
    cards = unit_cards(data, lec)
    with st.container(key=f"row_{module_id}_{lec['id'].replace(':', '_')}"):
        c1, c2, c3 = st.columns([6, 2, 2], vertical_alignment="center")
        c1.button(f"{short_label(lec)} – {lec['topic']}" + ("  als Nächstes" if is_next else ""),
                  key=f"open_{module_id}_{lec['id']}", type="tertiary", on_click=open_unit,
                  args=(module_id, lec["id"]))
        c1.caption(f"{'Folien' if docs else 'keine Folien'}" + (f" · 🃏 {len(cards)} Karten" if cards else "")
                   + f" · vorbereiten bis {_due(planner.prep_due(module, lec['date']))}"
                   + f" · nachbereiten bis {_due(planner.review_due(module, lec['date']))}")
        for col, field, label in ((c2, "vorbereitet", "Vorbereitet"), (c3, "nachbereitet", "Nachbereitet")):
            todo = {"key": planner.lecture_key(module_id, lec["date"], field), "module_id": module_id,
                    "chapter_id": lec.get("chapter_id"), "sync": field}
            _check(col, label, todo, state, f"abl_{field}_{module_id}_{lec['id']}")


def _exercise_row(module: dict, data: dict, ex: dict, state: dict, is_next: bool, due) -> None:
    module_id = module["id"]
    have = {d["doc_type"] for d in unit_docs(data, ex)}
    with st.container(key=f"row_{module_id}_{ex['id'].replace(':', '_')}"):
        c1, c2, c3 = st.columns([6, 2, 2], vertical_alignment="center")
        c1.button(f"{ex['title']}" + ("  als Nächstes" if is_next else ""),
                  key=f"open_{module_id}_{ex['id']}", type="tertiary", on_click=open_unit,
                  args=(module_id, ex["id"]))
        files = " · ".join(label for key, label in (("uebung", "Blatt"), ("loesung", "Lösung"),
                                                     ("eigene_loesung", "meine Lösung")) if key in have)
        c1.caption(f"{session_text(ex)}" + (f" · {files}" if files else "") + f" · lösen bis {_due(due)}")
        todo = {"key": ex["plan_key"], "module_id": module_id, "chapter_id": ex.get("chapter_id"), "sync": "uebung"}
        _check(c2, "Gelöst", todo, state, f"abl_ex_{module_id}_{ex['id']}")


def _chapter_editor(module_id: str, data: dict) -> None:
    with st.expander("Kapitel bearbeiten"):
        df = pd.DataFrame([{
            "id": ch["id"], "Titel": ch["title"], "Woche": ch.get("week"),
            **{label: ch["status"][key] for key, label in CHAPTER_STATUS_FIELDS.items()},
        } for ch in data["chapters"]])
        edited = st.data_editor(
            df, key=f"syllabus_{module_id}", num_rows="dynamic", hide_index=True, width="stretch",
            column_config={"id": None, "Titel": st.column_config.TextColumn(required=True, width="large"),
                           "Woche": st.column_config.NumberColumn(min_value=1, max_value=20, step=1)})
        if st.button("Kapitel speichern", key=f"save_syllabus_{module_id}"):
            old = {ch["id"]: ch for ch in data["chapters"]}
            new_chapters = []
            for _, row in edited.iterrows():
                if pd.isna(row["Titel"]) or not str(row["Titel"]).strip():
                    continue
                cid = row["id"] if isinstance(row["id"], str) and row["id"] else f"k{new_id()[:6]}"
                ch = old.get(cid, {"id": cid, "status": {}})
                ch["title"] = str(row["Titel"]).strip()
                ch["week"] = int(row["Woche"]) if pd.notna(row["Woche"]) else None
                ch["status"] = {key: bool(row[label]) if pd.notna(row[label]) else False
                                for key, label in CHAPTER_STATUS_FIELDS.items()}
                new_chapters.append(ch)
            removed = set(old) - {ch["id"] for ch in new_chapters}
            data["removed_chapters"] = sorted(set(data.get("removed_chapters", [])) | removed)
            data["chapters"] = new_chapters
            save_module(module_id)
            st.rerun()


def render(cfg: dict, module: dict, lecs: list[dict], exs: list[dict]) -> None:
    module_id = module["id"]
    data = load_module(module_id)
    state = load_todos()
    now = today()
    next_lec = next((lec for lec in lecs if lec["date"] >= now and not lec["is_break"]), None)
    next_ex = next((ex for ex in exs if ex["session"] >= now), None)
    next_id = None
    if next_lec or next_ex:
        candidates = [u for u in (next_lec, next_ex) if u]
        next_id = min(candidates, key=lambda u: u["date"] if u["kind"] == "lecture" else u["session"])["id"]

    schedule, breaks = get_schedule(cfg), lecture_breaks(cfg)
    st.caption("Tippe auf eine Vorlesung oder Übung, um Dateien hochzuladen, vor- und nachzubereiten und zu lernen. "
               "Erledigtes kannst du direkt hier abhaken.")
    groups = [(ch["id"], chapter_label(data, ch["id"])) for ch in data["chapters"]] + [(None, "Weitere Termine")]
    for chapter_id, label in groups:
        ch_lecs = [lec for lec in lecs if lec.get("chapter_id") == chapter_id]
        ch_exs = [ex for ex in exs if ex.get("chapter_id") == chapter_id]
        if not ch_lecs and not ch_exs:
            continue
        with st.container(border=True):
            st.markdown(f"**{label}**")
            items = sorted(ch_lecs + ch_exs, key=lambda u: u["date"] if u["kind"] == "lecture" else u["session"])
            for u in items:
                if u["kind"] == "lecture":
                    _lecture_row(module, data, u, state, u["id"] == next_id)
                else:
                    _exercise_row(module, data, u, state, u["id"] == next_id,
                                  planner.exercise_due(module, u, schedule, breaks))

    tasks = planner.tasks_of(module)
    if tasks:
        st.markdown("**Weitere Termine**")
        for t in tasks:
            done = bool(state.get(f"{module_id}:task:{t['index']}"))
            st.markdown(f"- {_mark(done)} **{t['title']}** "
                        f"({t['start']:%d.%m.} – {t['due']:%d.%m.%Y})")
    _chapter_editor(module_id, data)

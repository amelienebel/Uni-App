"""Reiter „Ablauf“: Kapitel mit ihren Vorlesungen, Übungen und Tutorien – jede Zeile öffnet die Detailseite."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from utils import planner
from utils.storage import CHAPTER_STATUS_FIELDS, chapter_label, load_module, load_todos, new_id, save_module, today
from utils.units import session_text, short_label, unit_cards, unit_docs
from views.common import open_unit


def _mark(ok: bool) -> str:
    return "✅" if ok else "⬜"


def _lecture_row(module_id: str, data: dict, lec: dict, state: dict, is_next: bool) -> None:
    docs = unit_docs(data, lec)
    cards = unit_cards(data, lec)
    prep = state.get(planner.lecture_key(module_id, lec["date"], "vorbereitet"))
    review = state.get(planner.lecture_key(module_id, lec["date"], "nachbereitet"))
    with st.container(key=f"row_{module_id}_{lec['id'].replace(':', '_')}"):
        c1, c2 = st.columns([3, 2], vertical_alignment="center")
        c1.button(f"🎬 {short_label(lec)} – {lec['topic']}" + ("  ⬅ als Nächstes" if is_next else ""),
                  key=f"open_{module_id}_{lec['id']}", type="tertiary", on_click=open_unit,
                  args=(module_id, lec["id"]))
        c2.caption(f"{'📄 Folien' if docs else '· keine Folien'} · {_mark(prep)} vorbereitet · "
                   f"{_mark(review)} nachbereitet" + (f" · 🃏 {len(cards)}" if cards else ""))


def _exercise_row(module_id: str, data: dict, ex: dict, state: dict, is_next: bool) -> None:
    docs = unit_docs(data, ex)
    have = {d["doc_type"] for d in docs}
    with st.container(key=f"row_{module_id}_{ex['id'].replace(':', '_')}"):
        c1, c2 = st.columns([3, 2], vertical_alignment="center")
        c1.button(f"✏️ {ex['title']}" + ("  ⬅ als Nächstes" if is_next else ""),
                  key=f"open_{module_id}_{ex['id']}", type="tertiary", on_click=open_unit,
                  args=(module_id, ex["id"]))
        c2.caption(f"{session_text(ex)} · {_mark('uebung' in have)} Blatt · {_mark('loesung' in have)} Lösung · "
                   f"{_mark(bool(state.get(ex['plan_key'])))} gelöst")


def _chapter_editor(module_id: str, data: dict) -> None:
    with st.expander("⚙️ Kapitel bearbeiten"):
        df = pd.DataFrame([{
            "id": ch["id"], "Titel": ch["title"], "Woche": ch.get("week"),
            **{label: ch["status"][key] for key, label in CHAPTER_STATUS_FIELDS.items()},
        } for ch in data["chapters"]])
        edited = st.data_editor(
            df, key=f"syllabus_{module_id}", num_rows="dynamic", hide_index=True, width="stretch",
            column_config={"id": None, "Titel": st.column_config.TextColumn(required=True, width="large"),
                           "Woche": st.column_config.NumberColumn(min_value=1, max_value=20, step=1)})
        if st.button("💾 Kapitel speichern", key=f"save_syllabus_{module_id}"):
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

    st.caption("Tippe auf eine Vorlesung oder Übung, um Dateien hochzuladen, vor- und nachzubereiten und zu lernen.")
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
                row = _lecture_row if u["kind"] == "lecture" else _exercise_row
                row(module_id, data, u, state, u["id"] == next_id)

    tasks = planner.tasks_of(module)
    if tasks:
        st.markdown("**Weitere Termine**")
        for t in tasks:
            done = bool(state.get(f"{module_id}:task:{t['index']}"))
            st.markdown(f"- {_mark(done)} **{t['title']}** "
                        f"({t['start']:%d.%m.} – {t['due']:%d.%m.%Y})")
    _chapter_editor(module_id, data)

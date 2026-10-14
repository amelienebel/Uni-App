"""Reiter „Definitionen“: alle Fachbegriffe des Moduls zum Nachschlagen – jede Definition ist auch eine Karteikarte."""

from __future__ import annotations

import streamlit as st

from utils import ai
from utils import definitions as defs
from utils.learning import extract_definitions
from utils.storage import chapter_label, load_module, save_module
from utils.units import short_label, unit_docs
from views.common import ai_hint


def _save_edit(module_id: str, def_id: str, key: str) -> None:
    data = load_module(module_id)
    defs.update_definition(data, def_id, st.session_state[f"dt_{key}"], st.session_state[f"dd_{key}"])
    save_module(module_id)


def _delete(module_id: str, def_id: str) -> None:
    data = load_module(module_id)
    defs.delete_definition(data, def_id)
    save_module(module_id)


def render(cfg: dict, module: dict, lecs: list[dict], exs: list[dict]) -> None:
    module_id = module["id"]
    data = load_module(module_id)
    items = defs.definitions(data)
    units = {u["id"]: u for u in lecs + exs}

    c1, c2 = st.columns([3, 2], vertical_alignment="bottom")
    query = c1.text_input("Begriff suchen", key=f"defq_{module_id}", placeholder="z. B. Kapitalwert, Merkmal …",
                          label_visibility="collapsed")
    chapter_ids = [ch["id"] for ch in data["chapters"]]
    chapter = c2.selectbox("Kapitel", [None] + chapter_ids, key=f"defch_{module_id}", label_visibility="collapsed",
                           format_func=lambda cid: "Alle Kapitel" if cid is None else chapter_label(data, cid))
    st.caption("Jede Definition ist automatisch auch eine Karteikarte. Definitionen entstehen beim Erstellen der "
               "Karteikarten – oder hier über „Definitionen sammeln“.")

    shown = [d for d in items if (not chapter or d.get("chapter_id") == chapter)
             and (not query or query.lower() in d["term"].lower() or query.lower() in d["definition"].lower())]
    shown.sort(key=lambda d: d["term"].lower())
    if not items:
        st.info("Noch keine Definitionen. Erstelle Karteikarten zu einer Vorlesung oder tippe unten auf "
                "„Definitionen sammeln“.")
    elif not shown:
        st.caption("Keine Treffer.")
    letter = None
    for d in shown:
        first = d["term"][:1].upper()
        if first != letter:
            letter = first
            st.markdown(f"##### {letter}")
        with st.container(border=True, key=f"defrow_{module_id}_{d['id']}"):
            c1, c2 = st.columns([12, 1], vertical_alignment="top")
            unit = units.get(d.get("unit"))
            where = " · ".join(x for x in (chapter_label(data, d["chapter_id"]) if d.get("chapter_id") else "",
                                           short_label(unit) if unit else "") if x)
            c1.markdown(f"**{d['term']}**  \n{d['definition']}")
            if where:
                c1.caption(where)
            with c2.popover("⋯", help="Bearbeiten oder löschen"):
                key = f"{module_id}_{d['id']}"
                st.text_input("Begriff", d["term"], key=f"dt_{key}")
                st.text_area("Definition", d["definition"], key=f"dd_{key}", height=120)
                b1, b2 = st.columns(2)
                b1.button("Speichern", key=f"ds_{key}", type="primary", on_click=_save_edit,
                          args=(module_id, d["id"], key))
                b2.button("Löschen", key=f"dx_{key}", on_click=_delete, args=(module_id, d["id"]))

    st.divider()
    with st.expander("Definition selbst hinzufügen", icon=":material/add:"):
        with st.form(f"def_add_{module_id}", clear_on_submit=True):
            term = st.text_input("Begriff")
            text = st.text_area("Definition", height=100)
            cid = st.selectbox("Kapitel", [None] + chapter_ids,
                               format_func=lambda c: "— ohne Kapitel —" if c is None else chapter_label(data, c))
            if st.form_submit_button("Hinzufügen", type="primary") and term.strip() and text.strip():
                if defs.add_definition(data, term, text, None, cid, "manuell"):
                    save_module(module_id)
                    st.success("Hinzugefügt – auch als Karteikarte.")
                else:
                    st.warning("Diesen Begriff gibt es schon.")

    open_units = [u for u in lecs + exs if unit_docs(data, u) and u["id"] not in data.get("definitions_done", {})
                  and u["id"] not in data.get("cards_generated", {})]
    with st.expander(f"Definitionen sammeln ({len(open_units)} Vorlesung(en)/Übung(en) noch offen)",
                     icon=":material/auto_awesome:"):
        has_ai = ai_hint("Das Sammeln der Definitionen")
        st.caption("Liest die Unterlagen aller Vorlesungen und Übungen, zu denen noch keine Karteikarten erstellt "
                   "wurden, und legt alle Definitionen an. Kostet wenig (Standard-Modell)." if has_ai else "")
        if st.button("Definitionen sammeln", key=f"def_collect_{module_id}", disabled=not open_units,
                     icon=":material/auto_awesome:"):
            total, bar = 0, st.progress(0.0)
            for i, u in enumerate(open_units):
                bar.progress(i / len(open_units), text=f"Lese {short_label(u)} …")
                try:
                    total += extract_definitions(cfg, module_id, u)
                except ai.AIError as exc:
                    st.error(f"{short_label(u)}: {exc}")
            bar.empty()
            st.success(f"{total} Definition(en) hinzugefügt.")

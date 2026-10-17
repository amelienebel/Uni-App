"""Modulübergreifende Formelsammlung – nur die ausgewählten Formeln."""

from __future__ import annotations

import streamlit as st

from utils.config import get_module, module_label
from utils.export import to_markdown
from utils.storage import chapter_label, load_module, save_module
from views.common import render_formula


def in_sheet(formula: dict) -> bool:
    return formula.get("in_sheet", True)


def _toggle(module_id: str, formula: dict, key: str) -> None:
    formula["in_sheet"] = bool(st.session_state[key])
    save_module(module_id)


def _set_all(module_id: str, formulas: list[dict], value: bool) -> None:
    for f in formulas:
        f["in_sheet"] = value
    save_module(module_id)


def _choose(data: dict, module_id: str, formulas: list[dict]) -> None:
    c1, c2, _ = st.columns([1, 1, 4])
    c1.button("Alle", key=f"fs_all_{module_id}", on_click=_set_all, args=(module_id, formulas, True), width="stretch")
    c2.button("Keine", key=f"fs_none_{module_id}", on_click=_set_all, args=(module_id, formulas, False),
              width="stretch")
    current = object()
    for f in formulas:
        if f.get("chapter_id") != current:
            current = f.get("chapter_id")
            st.markdown(f"##### {chapter_label(data, current)}")
        key = f"fs_sel_{f['id']}"
        st.session_state[key] = in_sheet(f)
        c1, c2 = st.columns([1, 12], vertical_alignment="center")
        c1.checkbox("In die Formelsammlung", key=key, on_change=_toggle, args=(module_id, f, key),
                    label_visibility="collapsed")
        with c2:
            render_formula(f, show_meta=False)


def render(cfg: dict) -> None:
    st.title(":material/functions: Formelsammlung")
    ids = [m["id"] for m in cfg["modules"]]
    c1, c2 = st.columns([2, 3])
    selected = c1.multiselect("Module", ids, default=ids, format_func=lambda mid: module_label(cfg, mid, short=True))
    search = c2.text_input("Suche in Name, LaTeX und Erklärung", placeholder="z. B. Elastizität, Barwert, \\sum")
    t1, t2 = st.columns(2)
    choose = t1.toggle("Formeln auswählen", key="fs_choose")
    compact = t2.toggle("Kompaktansicht (zwei Spalten, ohne Erklärungen)", disabled=choose)

    blocks = [("title", "Formelsammlung")]
    total = 0
    for mid in selected:
        module = get_module(cfg, mid)
        data = load_module(mid)
        formulas = [f for f in data["formulas"]
                    if not search or search.lower() in (f["name"] + f["latex"] + f.get("explanation", "")).lower()]
        order = {ch["id"]: i for i, ch in enumerate(data["chapters"])}
        formulas.sort(key=lambda f: order.get(f.get("chapter_id"), 999))
        if choose:
            if formulas:
                chosen = sum(in_sheet(f) for f in formulas)
                with st.expander(f"{module['name']} – {chosen} von {len(formulas)} ausgewählt", expanded=True):
                    _choose(data, mid, formulas)
                total += len(formulas)
            continue
        formulas = [f for f in formulas if in_sheet(f)]
        if not formulas:
            continue
        total += len(formulas)
        blocks.append(("h1", module["name"]))
        with st.expander(f"{module['name']} – {len(formulas)} Formel(n)", expanded=True):
            current = object()
            cols = st.columns(2) if compact else [st.container()]
            for i, f in enumerate(formulas):
                if not compact and f.get("chapter_id") != current:
                    current = f.get("chapter_id")
                    st.markdown(f"##### {chapter_label(data, current)}")
                with cols[i % len(cols)]:
                    render_formula(f, show_meta=not compact)
                    if compact:
                        st.caption(chapter_label(data, f.get("chapter_id")))
                blocks.append(("formula", f))
    if not total:
        st.info("Keine Formeln gefunden.")
        return
    if not choose:
        st.download_button("Formelsammlung als Markdown", to_markdown(blocks).encode("utf-8"),
                           file_name="formelsammlung.md", mime="text/markdown")

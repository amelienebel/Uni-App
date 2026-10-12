"""📐 Zentrale, modulübergreifende Formelsammlung."""

from __future__ import annotations

import streamlit as st

from utils.config import get_module, module_label
from utils.export import to_markdown
from utils.storage import chapter_label, load_module
from views.common import render_formula


def render(cfg: dict) -> None:
    st.title("📐 Zentrale Formelsammlung")
    ids = [m["id"] for m in cfg["modules"]]
    c1, c2 = st.columns([2, 3])
    selected = c1.multiselect("Module", ids, default=ids, format_func=lambda mid: module_label(cfg, mid, short=True))
    search = c2.text_input("🔍 Suche in Name, LaTeX und Erklärung", placeholder="z. B. Elastizität, Barwert, \\sum")
    compact = st.toggle("Kompaktansicht (zwei Spalten, ohne Erklärungen)")

    blocks = [("title", "Zentrale Formelsammlung")]
    total = 0
    for mid in selected:
        module = get_module(cfg, mid)
        data = load_module(mid)
        formulas = [f for f in data["formulas"]
                    if not search or search.lower() in (f["name"] + f["latex"] + f.get("explanation", "")).lower()]
        if not formulas:
            continue
        total += len(formulas)
        blocks.append(("h1", module["name"]))
        with st.expander(f"{module['icon']} {module['name']} – {len(formulas)} Formel(n)", expanded=True):
            order = {ch["id"]: i for i, ch in enumerate(data["chapters"])}
            formulas.sort(key=lambda f: order.get(f.get("chapter_id"), 999))
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
    st.download_button("⬇️ Gefilterte Formelsammlung als Markdown", to_markdown(blocks).encode("utf-8"),
                       file_name="formelsammlung.md", mime="text/markdown")

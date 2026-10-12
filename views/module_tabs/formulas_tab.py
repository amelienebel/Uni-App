"""Reiter: Formelsammlung eines Moduls."""

from __future__ import annotations

import streamlit as st

from utils import ai
from utils.config import get_module
from utils.pdf_parser import find_formula_candidates
from utils.storage import (add_formulas, chapter_label, get_document_pages, get_document_text, load_module,
                           save_module)
from views.common import ai_hint, chapter_select, render_formula

EXTRACT_PROMPT = """Extrahiere ALLE mathematischen und betriebswirtschaftlichen Formeln aus den folgenden Unterlagen
des Moduls „{module}“. Für jede Formel: aussagekräftiger Name, sauberes LaTeX (ohne $-Zeichen, kompatibel mit
KaTeX), kurze Erklärung aller Variablen, Seitennummer. Keine Duplikate, keine reinen Zahlenrechnungen – nur
allgemeingültige Formeln. Bereits vorhanden (nicht erneut liefern): {existing}

<unterlagen>
{material}
</unterlagen>"""


def render(cfg: dict, module_id: str) -> None:
    module = get_module(cfg, module_id)
    data = load_module(module_id)

    st.subheader("📐 Formelsammlung")
    with st.expander("🔎 Formeln aus Dokumenten extrahieren"):
        has_ai = ai_hint("Die Formelextraktion")
        docs = data["documents"]
        selected = st.multiselect("Dokumente", docs, format_func=lambda d: d["filename"], key=f"fx_docs_{module_id}")
        if st.button("Extrahieren", key=f"fx_run_{module_id}", disabled=not selected, type="primary"):
            total = 0
            for doc in selected:
                with st.spinner(f"Extrahiere aus {doc['filename']} …"):
                    try:
                        if has_ai:
                            existing = "; ".join(f["name"] for f in data["formulas"]) or "keine"
                            result = ai.complete_json(EXTRACT_PROMPT.format(
                                module=module["name"], existing=existing, material=get_document_text(doc)),
                                ai.FORMULAS_SCHEMA)
                            formulas, source = result.get("formulas", []), f"{doc['filename']} (KI)"
                        else:
                            formulas = find_formula_candidates(get_document_pages(doc))
                            source = f"{doc['filename']} (heuristisch)"
                        total += add_formulas(module_id, formulas, source, chapter_id=doc.get("chapter_id"))
                    except ai.AIError as exc:
                        st.error(str(exc))
            st.success(f"{total} neue Formel(n) übernommen.")

    with st.expander("➕ Formel manuell hinzufügen"):
        name = st.text_input("Name", key=f"f_name_{module_id}")
        latex = st.text_area("LaTeX", key=f"f_latex_{module_id}", height=80,
                             placeholder=r"C_0 = -I_0 + \sum_{t=1}^{T} \frac{CF_t}{(1+i)^t}")
        if latex.strip():
            st.caption("Vorschau:")
            st.latex(latex)
        explanation = st.text_input("Erklärung", key=f"f_expl_{module_id}")
        chapter_id = chapter_select(data, f"f_ch_{module_id}", include_none=True)
        if st.button("Hinzufügen", key=f"f_add_{module_id}") and name.strip() and latex.strip():
            added = add_formulas(module_id, [{"name": name, "latex": latex, "explanation": explanation}],
                                 "manuell", chapter_id)
            st.success("Formel hinzugefügt." if added else "Diese Formel existiert bereits.")

    search = st.text_input("🔍 Suchen", key=f"f_search_{module_id}", placeholder="z. B. Kapitalwert, Varianz …")
    formulas = [f for f in data["formulas"]
                if not search or search.lower() in (f["name"] + f["latex"] + f.get("explanation", "")).lower()]
    if not formulas:
        st.caption("Keine Formeln gefunden.")
        return

    groups: dict = {}
    for f in formulas:
        groups.setdefault(f.get("chapter_id"), []).append(f)
    order = [ch["id"] for ch in data["chapters"]] + [None]
    for cid in sorted(groups, key=lambda c: order.index(c) if c in order else len(order)):
        st.markdown(f"#### {chapter_label(data, cid)}")
        for f in groups[cid]:
            with st.container(border=True):
                c1, c2 = st.columns([6, 1])
                with c1:
                    render_formula(f)
                    st.caption(f"Quelle: {f.get('source', '–')}" + (f" · S. {f['page']}" if f.get("page") else ""))
                with c2:
                    edit_key = f"edit_f_{f['id']}"
                    if st.button("✏️", key=f"btn_{edit_key}", help="Bearbeiten"):
                        st.session_state[edit_key] = not st.session_state.get(edit_key, False)
                    if st.button("🗑️", key=f"del_f_{f['id']}", help="Löschen"):
                        data["formulas"].remove(f)
                        save_module(module_id)
                        st.rerun()
                if st.session_state.get(f"edit_f_{f['id']}"):
                    with st.form(f"form_edit_{f['id']}"):
                        new_name = st.text_input("Name", f["name"])
                        new_latex = st.text_area("LaTeX", f["latex"])
                        new_expl = st.text_input("Erklärung", f.get("explanation", ""))
                        new_ch = chapter_select(data, f"edit_ch_{f['id']}", include_none=True,
                                                default=f.get("chapter_id"))
                        if st.form_submit_button("Speichern"):
                            f.update({"name": new_name, "latex": new_latex, "explanation": new_expl,
                                      "chapter_id": new_ch})
                            save_module(module_id)
                            st.session_state[f"edit_f_{f['id']}"] = False
                            st.rerun()

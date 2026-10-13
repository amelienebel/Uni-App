"""Reiter: Notizen – Fragen fürs Tutorium/die Übung und allgemeine Notizen zum Modul."""

from __future__ import annotations

import streamlit as st

from utils.storage import load_module, new_id, now_iso, save_module


def _notes(data: dict) -> dict:
    notes = data.setdefault("general_notes", {})
    notes.setdefault("questions", [])
    notes.setdefault("text", "")
    notes.setdefault("todo", "")
    return notes


def _toggle_question(module_id: str, qid: str, widget_key: str) -> None:
    data = load_module(module_id)
    for q in _notes(data)["questions"]:
        if q["id"] == qid:
            q["done"] = st.session_state[widget_key]
    save_module(module_id)


def _delete_question(module_id: str, qid: str) -> None:
    data = load_module(module_id)
    notes = _notes(data)
    notes["questions"] = [q for q in notes["questions"] if q["id"] != qid]
    save_module(module_id)


def question_list(module_id: str, data: dict, key_prefix: str = "q", show_done: bool = False,
                  unit: str | None = None) -> None:
    """Fragenliste mit Eingabefeld – auf den Übungs-/Vorlesungsseiten nur die Fragen dieser Einheit."""
    notes = _notes(data)
    with st.form(f"{key_prefix}_add_{module_id}", clear_on_submit=True):
        c1, c2 = st.columns([5, 1], vertical_alignment="bottom")
        text = c1.text_input("Neue Frage", placeholder="z. B. Warum ist bei Aufgabe 3b der Zins nachschüssig?")
        if c2.form_submit_button("➕ Hinzufügen") and text.strip():
            notes["questions"].append({"id": new_id(), "text": text.strip(), "done": False, "answer": "",
                                       "created_at": now_iso(), "unit": unit})
            save_module(module_id)
    questions = [q for q in notes["questions"] if unit is None or q.get("unit") == unit]
    open_q = [q for q in questions if not q["done"]]
    done_q = [q for q in questions if q["done"]]
    if not open_q:
        st.caption("Keine offenen Fragen. 🎉")
    for q in open_q + (done_q if show_done else []):
        key = f"{key_prefix}_chk_{q['id']}"
        st.session_state[key] = q["done"]
        c1, c2 = st.columns([12, 1])
        c1.checkbox(q["text"], key=key, on_change=_toggle_question, args=(module_id, q["id"], key),
                    help=f"Notiert am {q['created_at'][:10]} – abhaken, wenn geklärt")
        c2.button("🗑️", key=f"{key_prefix}_del_{q['id']}", on_click=_delete_question, args=(module_id, q["id"]),
                  help="Löschen")
    if done_q and not show_done:
        st.caption(f"{len(done_q)} geklärte Frage(n) – unter „Formeln & Notizen“ einsehbar.")


def render(cfg: dict, module_id: str) -> None:
    data = load_module(module_id)
    notes = _notes(data)
    st.subheader("🗒️ Notizen")
    st.markdown("#### ❓ Fragen fürs Tutorium / die Übung")
    st.caption("Alle Fragen aus dem Modul – auch die, die du direkt bei einer Übung notiert hast.")
    question_list(module_id, data, key_prefix="nq", show_done=True)

    st.markdown("#### 📌 Sonstige Notizen")
    with st.form(f"general_notes_{module_id}"):
        c1, c2 = st.columns(2)
        todo = c1.text_area("Organisatorisches & Erinnerungen", notes["todo"], height=200,
                            placeholder="Anmeldung Tutorium, Abgabefristen, Raumänderungen, Literatur …")
        text = c2.text_area("Freie Notizen", notes["text"], height=200,
                            placeholder="Gedanken, Zusammenhänge, Merksätze …")
        if st.form_submit_button("💾 Speichern", type="primary"):
            notes.update({"todo": todo, "text": text})
            save_module(module_id)
            st.success("Gespeichert.")

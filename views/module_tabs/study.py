"""Lernen: Karteikarten-Abfrage (Spaced Repetition), Karten-Chat, Kartenverwaltung – für eine oder mehrere Vorlesungen."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from utils import ai
from utils import spaced_repetition as sr
from utils.config import get_module
from utils.learning import generate_unit_cards
from utils.storage import chapter_label, days_until_exam, load_module, load_settings, save_module

CARD_CHAT_SYSTEM = (
    ai.BASE_SYSTEM + "\n\nDer Studierende lernt gerade mit einer Lernkarte und hat eine Rückfrage dazu. "
    "Erkläre verständlich, nutze bei Bedarf ein kleines Zahlenbeispiel und weise auf typische Klausurfallen hin. "
    "Halte dich kurz (max. ~200 Wörter), sofern nicht ausdrücklich mehr gewünscht ist."
)


def _card_chat(card: dict, module_name: str, key: str) -> bool:
    with st.expander(f"Nachfragen zu dieser Karte ({len(card.get('chat', []))})"):
        for msg in card.get("chat", []):
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])
        if not ai.is_available():
            st.caption("Für den Karten-Chat wird ein API-Key benötigt.")
            return False
        with st.form(f"card_chat_{key}", clear_on_submit=True):
            question = st.text_input("Deine Frage", placeholder="Warum ist das so? Kannst du ein Beispiel geben?")
            submitted = st.form_submit_button("Fragen")
        if submitted and question.strip():
            system = (CARD_CHAT_SYSTEM + f"\n\nModul: {module_name}\n<lernkarte>\nFrage: {card['front']}\n"
                      f"Antwort: {card['back']}\n</lernkarte>")
            history = card.setdefault("chat", [])
            history.append({"role": "user", "content": question.strip()})
            with st.chat_message("user"):
                st.markdown(question)
            with st.chat_message("assistant"):
                answer = st.write_stream(ai.stream_chat(history, system=system))
            history.append({"role": "assistant", "content": answer if isinstance(answer, str) else "".join(answer)})
            return True
    return False


def review_session(cfg: dict, module_id: str, cards: list[dict], key: str) -> None:
    """Abfrage der übergebenen Karten. Standard: fällige Karten; optional alle (z. B. vor der Klausur)."""
    module = get_module(cfg, module_id)
    days = days_until_exam(module_id)
    limit = int(load_settings()["learning"].get("daily_review_limit", 60))
    if not cards:
        st.caption("Noch keine Karteikarten vorhanden.")
        return
    stats = sr.card_stats(cards)
    c = st.columns(4)
    c[0].metric("Karten", stats["total"])
    c[1].metric("Heute fällig", stats["due"])
    c[2].metric("Neu", stats["new"])
    c[3].metric("Beherrscht", stats["mastered"])

    all_mode = st.toggle("Alle Karten üben (nicht nur die heute fälligen)", key=f"allmode_{key}")
    done_key = f"sessiondone_{key}"
    if all_mode:
        done = set(st.session_state.get(done_key, []))
        queue = sorted((c for c in cards if c["id"] not in done), key=lambda c: c["due"])
        if not queue and cards:
            st.success("Alle Karten einmal durchgearbeitet!")
            if st.button("Nochmal von vorn", key=f"restart_{key}"):
                st.session_state[done_key] = []
                st.rerun()
            return
    else:
        queue = sr.due_queue(cards, days, limit=limit)
    if not queue:
        st.success("Keine fälligen Karten – alles wiederholt! Mit dem Schalter oben kannst du trotzdem üben.")
        return

    card = queue[0]
    data = load_module(module_id)
    st.caption(f"Noch {len(queue)} Karte(n) in dieser Runde · {chapter_label(data, card.get('chapter_id'))}")
    state_key = f"reveal_{card['id']}"
    with st.container(border=True):
        st.markdown("**Frage**")
        st.markdown(f"#### {card['front']}")
        answer = st.text_area("Deine Antwort", key=f"answer_{card['id']}", height=100,
                              placeholder="Antwort eintippen (oder im Kopf beantworten) …")
        if not st.session_state.get(state_key):
            if st.button("Auflösen", type="primary", key=f"reveal_btn_{card['id']}"):
                st.session_state[state_key] = True
                st.rerun()
        else:
            col_user, col_solution = st.columns(2)
            with col_user:
                st.markdown("**Deine Antwort**")
                st.info(answer or "_(keine Eingabe)_")
            with col_solution:
                st.markdown("**Lösung**")
                st.success(card["back"])
            if answer.strip() and ai.is_available():
                if st.button("Antwort von der KI prüfen lassen", key=f"check_{card['id']}"):
                    with st.spinner("Prüfe …"):
                        try:
                            st.session_state[f"fb_{card['id']}"] = ai.complete(
                                f"Lernkarte – Frage: {card['front']}\nMusterantwort: {card['back']}\n\n"
                                f"Antwort des Studierenden: {answer}\n\nBewerte knapp (max. 80 Wörter): Was ist "
                                "richtig, was fehlt oder ist falsch? Schlage eine Selbstbewertung vor "
                                "(Gar nicht / Etwas / Gut / Perfekt).", max_tokens=2000, effort="low")
                        except ai.AIError as exc:
                            st.error(str(exc))
                if fb := st.session_state.get(f"fb_{card['id']}"):
                    st.markdown(fb)
            st.markdown("**Wie gut konntest du die Karte?**")
            for col, grade in zip(st.columns(4), sr.GRADES):
                if col.button(f"{grade['label']}", key=f"grade_{key}_{card['id']}_{grade['value']}",
                              width="stretch"):
                    sr.review(card, grade["value"], days)
                    save_module(module_id)
                    if all_mode:
                        st.session_state[done_key] = st.session_state.get(done_key, []) + [card["id"]]
                    for k in (state_key, f"answer_{card['id']}", f"fb_{card['id']}"):
                        st.session_state.pop(k, None)
                    st.rerun()
    if _card_chat(card, module["name"], f"{key}_{card['id']}"):
        save_module(module_id)


def generate_button(cfg: dict, module_id: str, unit: dict, existing: list[dict], key: str,
                    label: str | None = None) -> None:
    label = label or ("Karten ergänzen (neue Notizen/Dateien berücksichtigen)" if existing
                      else "Karteikarten erstellen (gesamter Stoff)")
    if st.button(label, key=f"gen_{key}", type="secondary" if existing else "primary"):
        run_generation(cfg, module_id, unit, existing)


def run_generation(cfg: dict, module_id: str, unit: dict, existing: list[dict]) -> None:
    with st.spinner("Erstelle Karteikarten zum gesamten Stoff … (kann 1–2 Minuten dauern)"):
        try:
            added = generate_unit_cards(cfg, module_id, unit, existing)
            st.session_state[f"genmsg_{unit['id']}"] = (
                ("success", f"{added} neue Karteikarte(n) angelegt.") if added else
                ("info", "Keine neuen Karten nötig – alles ist schon abgedeckt."))
        except ai.AIError as exc:
            st.session_state[f"genmsg_{unit['id']}"] = ("error", str(exc))
    st.rerun()


def show_generation_message(unit_id: str) -> None:
    if msg := st.session_state.pop(f"genmsg_{unit_id}", None):
        getattr(st, msg[0])(msg[1])


def manual_card(module_id: str, data: dict, unit: dict | None, key: str) -> None:
    with st.expander("Karte selbst anlegen"):
        with st.form(f"manual_card_{key}", clear_on_submit=True):
            front = st.text_area("Vorderseite (Frage)", height=80)
            back = st.text_area("Rückseite (Antwort) – Markdown & $LaTeX$ erlaubt", height=100)
            if st.form_submit_button("Anlegen") and front.strip() and back.strip():
                card = sr.new_card(front, back, chapter_id=unit.get("chapter_id") if unit else None)
                card["unit"] = unit["id"] if unit else None
                data["cards"].append(card)
                save_module(module_id)
                st.success("Karte angelegt.")


def manage_cards(module_id: str, data: dict, cards: list[dict], key: str) -> None:
    if not cards:
        return
    with st.expander(f"Karten bearbeiten oder löschen ({len(cards)})"):
        df = pd.DataFrame([{
            "id": c["id"], "Löschen": False, "Vorderseite": c["front"], "Rückseite": c["back"],
            "Fällig": c["due"], "Quelle": c.get("source", ""),
        } for c in cards])
        edited = st.data_editor(df, hide_index=True, width="stretch", key=f"cards_editor_{key}",
                                column_config={"id": None}, disabled=["Fällig", "Quelle"])
        if st.button("Änderungen übernehmen", key=f"cards_save_{key}"):
            rows = {row["id"]: row for _, row in edited.iterrows()}
            keep = []
            for card in data["cards"]:
                row = rows.get(card["id"])
                if row is not None:
                    if row["Löschen"]:
                        continue
                    card["front"], card["back"] = str(row["Vorderseite"]), str(row["Rückseite"])
                keep.append(card)
            data["cards"] = keep
            save_module(module_id)
            st.rerun()


def forecast(cards: list[dict]) -> None:
    if cards:
        with st.expander("Wiederholungsprognose (14 Tage)"):
            st.bar_chart(pd.DataFrame(sr.forecast(cards)), x="Datum", y="Karten")

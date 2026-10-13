"""Reiter: Spaced Repetition – Kartengenerierung, Review-Modus, Karten-Chat, Kartenverwaltung."""

from __future__ import annotations

import re

import pandas as pd
import streamlit as st

from utils import ai
from utils import spaced_repetition as sr
from utils.config import get_module
from utils.storage import (chapter_label, days_until_exam, get_document_text, get_notes, load_module, load_settings,
                           save_module)
from views.common import ai_hint, chapter_select

CARDS_PROMPT = """Erstelle {n} hochwertige Lernkarten (Karteikarten) für das Modul „{module}“ aus den folgenden
Unterlagen. Regeln:
- Eine Karte = ein abfragbarer Gedanke (Definition, Zusammenhang, Rechenschritt, Formel, typischer Fehler).
- Vorderseite als konkrete Frage, Rückseite als präzise, klausurtaugliche Antwort (max. ~80 Wörter).
- Mische Wissens-, Verständnis- und Anwendungsfragen; bei Formeln auch nach Bedeutung der Variablen fragen.
- Formeln in LaTeX mit $...$.
- Vermeide Duplikate zu diesen bestehenden Karten: {existing}
- chapter_hint: Titel des passenden Kapitels aus dieser Liste: {chapters}

<unterlagen>
{material}
</unterlagen>"""

CARD_CHAT_SYSTEM = (
    ai.BASE_SYSTEM + "\n\nDer Studierende lernt gerade mit einer Lernkarte und hat eine Rückfrage dazu. "
    "Erkläre verständlich, nutze bei Bedarf ein kleines Zahlenbeispiel und weise auf typische Klausurfallen hin. "
    "Halte dich kurz (max. ~200 Wörter), sofern nicht ausdrücklich mehr gewünscht ist."
)


def _offline_cards(data: dict, sources: list[str]) -> list[dict]:
    """Ohne KI: Karten aus Analyse-Fragen, Kernbegriffen, Formeln und Notizzeilen der Form „Begriff: Erklärung“."""
    cards = []
    for doc in data["documents"]:
        if f"doc:{doc['id']}" not in sources:
            continue
        analysis = doc.get("analysis") or {}
        for q in analysis.get("check_questions", []):
            cards.append({"front": q["question"], "back": q["answer"], "chapter_id": doc.get("chapter_id")})
        for c in analysis.get("key_concepts", []):
            if not c["term"].startswith("Folie"):
                cards.append({"front": f"Was versteht man unter „{c['term']}“?", "back": c["explanation"],
                              "chapter_id": doc.get("chapter_id")})
    if "formulas" in sources:
        for f in data["formulas"]:
            cards.append({"front": f"Wie lautet die Formel: {f['name']}?",
                          "back": f"$${f['latex']}$$\n\n{f.get('explanation', '')}",
                          "chapter_id": f.get("chapter_id"), "type": "formula"})
    for ch in data["chapters"]:
        if f"notes:{ch['id']}" not in sources:
            continue
        notes = get_notes(data, ch["id"])
        for line in (notes["text"] + "\n" + notes["emphasized"]).splitlines():
            m = re.match(r"^\s*[-•*]?\s*([^:]{3,60}):\s+(.{5,})$", line)
            if m:
                cards.append({"front": f"{m.group(1).strip()}?", "back": m.group(2).strip(), "chapter_id": ch["id"]})
    return cards


def _ai_cards(cfg: dict, module_id: str, data: dict, sources: list[str], n: int) -> list[dict]:
    module = get_module(cfg, module_id)
    material = []
    for doc in data["documents"]:
        if f"doc:{doc['id']}" in sources:
            material.append(f"<dokument name=\"{doc['filename']}\" kapitel=\"{chapter_label(data, doc.get('chapter_id'))}\">\n"
                            f"{get_document_text(doc)}\n</dokument>")
    for ch in data["chapters"]:
        if f"notes:{ch['id']}" in sources:
            notes = get_notes(data, ch["id"])
            material.append(f"<notizen kapitel=\"{chapter_label(data, ch['id'])}\">\n{notes['text']}\n"
                            f"Betont: {notes['emphasized']}\nBeispiele: {notes['examples']}\n</notizen>")
    if "formulas" in sources:
        material.append("<formeln>\n" + "\n".join(f"{f['name']}: {f['latex']}" for f in data["formulas"]) + "\n</formeln>")
    chapters = {ch["title"]: ch["id"] for ch in data["chapters"]}
    existing = "; ".join(c["front"] for c in data["cards"][-80:]) or "keine"
    result = ai.complete_json(CARDS_PROMPT.format(n=n, module=module["name"], existing=existing,
                                                  chapters=", ".join(chapters), material="\n\n".join(material)),
                              ai.CARDS_SCHEMA)
    cards = []
    for c in result.get("cards", []):
        cards.append({"front": c["front"], "back": c["back"], "chapter_id": chapters.get(c.get("chapter_hint"))})
    return cards


def _card_chat(card: dict, module_name: str, key: str) -> bool:
    with st.expander(f"💬 Nachfragen zu dieser Karte ({len(card.get('chat', []))})"):
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


def render(cfg: dict, module_id: str) -> None:
    module = get_module(cfg, module_id)
    data = load_module(module_id)
    days = days_until_exam(module_id)
    stats = sr.card_stats(data["cards"])
    limit = int(load_settings()["learning"].get("daily_review_limit", 60))

    st.subheader("🃏 Spaced Repetition")
    c = st.columns(4)
    c[0].metric("Karten", stats["total"])
    c[1].metric("Heute fällig", stats["due"])
    c[2].metric("Neu", stats["new"])
    c[3].metric("Beherrscht", stats["mastered"])

    # --- Generierung -------------------------------------------------------
    with st.expander("✨ Lernkarten automatisch generieren", expanded=not data["cards"]):
        has_ai = ai_hint("Die Kartengenerierung")
        options = {f"doc:{d['id']}": f"📄 {d['filename']}" for d in data["documents"]}
        options.update({f"notes:{ch['id']}": f"🗒️ Notizen – {chapter_label(data, ch['id'])}"
                        for ch in data["chapters"] if ch["id"] in data["notes"] and get_notes(data, ch["id"])["text"]})
        options["formulas"] = f"📐 Formelsammlung ({len(data['formulas'])} Formeln)"
        sources = st.multiselect("Quellen (Folien, Übungsblätter, Musterlösungen, Notizen)", list(options),
                                 format_func=options.get, key=f"card_src_{module_id}")
        n = st.slider("Anzahl Karten", 5, 40, 15, key=f"card_n_{module_id}", disabled=not has_ai)
        if st.button("Karten erzeugen", type="primary", key=f"gen_cards_{module_id}", disabled=not sources):
            with st.spinner("Erzeuge Lernkarten …"):
                try:
                    raw = _ai_cards(cfg, module_id, data, sources, n) if has_ai else _offline_cards(data, sources)
                except ai.AIError as exc:
                    st.error(str(exc))
                    raw = []
            known = {card["front"].strip().lower() for card in data["cards"]}
            added = 0
            for item in raw:
                if item["front"].strip().lower() in known:
                    continue
                data["cards"].append(sr.new_card(item["front"], item["back"], source="KI" if has_ai else "auto",
                                                 chapter_id=item.get("chapter_id"),
                                                 card_type=item.get("type", "basic")))
                known.add(item["front"].strip().lower())
                added += 1
            save_module(module_id)
            if added:
                st.success(f"{added} neue Karten angelegt.")
            else:
                st.warning("Keine neuen Karten gefunden. Tipp: Folien zuerst analysieren oder Notizen im Format "
                           "„Begriff: Erklärung“ schreiben.")

    with st.expander("➕ Karte manuell anlegen"):
        with st.form(f"manual_card_{module_id}", clear_on_submit=True):
            front = st.text_area("Vorderseite (Frage)", height=80)
            back = st.text_area("Rückseite (Antwort) – Markdown & $LaTeX$ erlaubt", height=100)
            chapter_id = chapter_select(data, f"manual_card_ch_{module_id}", include_none=True)
            if st.form_submit_button("Anlegen") and front.strip() and back.strip():
                data["cards"].append(sr.new_card(front, back, chapter_id=chapter_id))
                save_module(module_id)
                st.success("Karte angelegt.")

    # --- Review-Modus -------------------------------------------------------
    st.markdown("### 🔁 Review-Modus")
    chapter_filter = st.multiselect("Nur Kapitel", [ch["id"] for ch in data["chapters"]],
                                    format_func=lambda cid: chapter_label(data, cid), key=f"rev_filter_{module_id}")
    queue = sr.due_queue(data["cards"], days, limit=limit, chapter_ids=chapter_filter or None)
    if not queue:
        st.success("🎉 Keine fälligen Karten – alles wiederholt!" if data["cards"] else "Noch keine Karten vorhanden.")
    else:
        card = queue[0]
        st.caption(f"Noch {len(queue)} fällige Karte(n) in dieser Sitzung · Priorität {sr.priority(card, days)} · "
                   f"{chapter_label(data, card.get('chapter_id'))}")
        state_key = f"reveal_{card['id']}"
        with st.container(border=True):
            st.markdown("**Frage**")
            st.markdown(f"#### {card['front']}")
            answer = st.text_area("Deine Antwort", key=f"answer_{card['id']}", height=100,
                                  placeholder="Antwort eintippen (oder im Kopf beantworten) …")
            if not st.session_state.get(state_key):
                if st.button("👀 Auflösen", type="primary", key=f"reveal_btn_{card['id']}"):
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
                    if st.button("🤖 Antwort von der KI prüfen lassen", key=f"check_{card['id']}"):
                        with st.spinner("Prüfe …"):
                            try:
                                feedback = ai.complete(
                                    f"Lernkarte – Frage: {card['front']}\nMusterantwort: {card['back']}\n\n"
                                    f"Antwort des Studierenden: {answer}\n\nBewerte knapp (max. 80 Wörter): Was ist "
                                    "richtig, was fehlt oder ist falsch? Schlage eine Selbstbewertung vor "
                                    "(Gar nicht / Etwas / Gut / Perfekt).", max_tokens=2000, effort="low")
                                st.session_state[f"fb_{card['id']}"] = feedback
                            except ai.AIError as exc:
                                st.error(str(exc))
                    if fb := st.session_state.get(f"fb_{card['id']}"):
                        st.markdown(fb)
                st.markdown("**Wie gut konntest du die Karte?**")
                grade_cols = st.columns(4)
                for col, grade in zip(grade_cols, sr.GRADES):
                    if col.button(f"{grade['icon']} {grade['label']}", key=f"grade_{card['id']}_{grade['value']}",
                                  width="stretch"):
                        sr.review(card, grade["value"], days)
                        save_module(module_id)
                        for k in (state_key, f"answer_{card['id']}", f"fb_{card['id']}"):
                            st.session_state.pop(k, None)
                        st.rerun()
        if _card_chat(card, module["name"], card["id"]):
            save_module(module_id)

    # --- Prognose & Verwaltung ----------------------------------------------
    if data["cards"]:
        with st.expander("📊 Wiederholungsprognose (14 Tage)"):
            st.bar_chart(pd.DataFrame(sr.forecast(data["cards"])), x="Datum", y="Karten")
        with st.expander(f"🗂️ Alle Karten verwalten ({len(data['cards'])})"):
            df = pd.DataFrame([{
                "id": c["id"], "Löschen": False, "Vorderseite": c["front"], "Rückseite": c["back"],
                "Kapitel": chapter_label(data, c.get("chapter_id")), "Fällig": c["due"], "Intervall (T.)": c["interval"],
                "Leichtigkeit": c["ease"], "Quelle": c.get("source", ""),
            } for c in data["cards"]])
            edited = st.data_editor(df, hide_index=True, width="stretch", key=f"cards_editor_{module_id}",
                                    column_config={"id": None},
                                    disabled=["Kapitel", "Fällig", "Intervall (T.)", "Leichtigkeit", "Quelle"])
            if st.button("💾 Änderungen übernehmen", key=f"cards_save_{module_id}"):
                by_id = {c["id"]: c for c in data["cards"]}
                keep = []
                for _, row in edited.iterrows():
                    card = by_id.get(row["id"])
                    if card is None or row["Löschen"]:
                        continue
                    card["front"], card["back"] = str(row["Vorderseite"]), str(row["Rückseite"])
                    keep.append(card)
                data["cards"] = keep
                save_module(module_id)
                st.rerun()

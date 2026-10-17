"""Lernen: Karteikarten-Abfrage (Spaced Repetition), Karten-Chat, Kartenverwaltung – für eine oder mehrere Vorlesungen."""

from __future__ import annotations

import re
from datetime import date

import pandas as pd
import streamlit as st

from utils import ai, learning
from utils import spaced_repetition as sr
from utils.config import get_module
from utils.pdf_parser import render_page
from utils.storage import chapter_label, days_until_exam, load_module, load_settings, read_data_file, save_module
from utils.units import unit_cards

WEAK_TAB_STATE = "learn_weak_{}"

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
                      f"Antwort: {card['back']}\nErklärung: {card.get('explanation', '')}\n</lernkarte>")
            history = card.setdefault("chat", [])
            history.append({"role": "user", "content": question.strip()})
            with st.chat_message("user"):
                st.markdown(question)
            with st.chat_message("assistant"):
                answer = st.write_stream(ai.stream_chat(history, system=system))
            history.append({"role": "assistant", "content": answer if isinstance(answer, str) else "".join(answer)})
            return True
    return False


TYPE_LABELS = {"definition": "Definition", "list": "Aufzählung", "process": "Ablauf", "formula": "Formel",
               "calculation": "Rechenschema", "comparison": "Vergleich", "application": "Anwendung",
               "graphic": "Grafik"}
PRIORITY_LABELS = {"high": "hoch", "normal": "normal", "low": "niedrig"}


def _norm(text: str) -> str:
    return re.sub(r"[\s$\\{}^_]+", " ", text.lower())


def keyword_hits(answer: str, keywords: list[str]) -> list[tuple[str, bool]]:
    """Welche Stichwörter kommen in der getippten Antwort vor? (Wortstämme, Groß/klein egal)"""
    typed = _norm(answer)
    hits = []
    for kw in keywords:
        words = [w for w in re.findall(r"\w+", _norm(kw)) if len(w) >= 3] or [_norm(kw).strip()]
        hits.append((kw, all(w[:max(4, round(len(w) * 0.6))] in typed for w in words if w)))
    return hits


def suggested_grade(hits: list[tuple[str, bool]]) -> int | None:
    if not hits:
        return None
    share = sum(hit for _, hit in hits) / len(hits)
    return 2 if share >= 0.85 else 1 if share >= 0.5 else 0


def _badge(color: str, text: str) -> str:
    return f":{color}-badge[{text.replace('[', '(').replace(']', ')')}]"


def _doc_by_id(data: dict, doc_id: str) -> dict | None:
    return next((d for d in data["documents"] if d["id"] == doc_id), None)


@st.cache_data(show_spinner=False, max_entries=30)
def _slide_png(path: str, page: int) -> bytes | None:
    return render_page(read_data_file(path), page)


def _sources(data: dict, card: dict, key: str) -> None:
    parts, pages = [], []
    for src in card.get("sources", []):
        doc = _doc_by_id(data, src["doc_id"])
        if doc:
            label = "Folie" if doc["doc_type"] == "folien" else "S."
            parts.append(f"{doc['filename']}, {label} {', '.join(map(str, src['pages']))}")
            if doc["filename"].lower().endswith(".pdf"):
                pages += [(doc["path"], p) for p in src["pages"]]
    if card.get("from_notes"):
        parts.append("deine Nachbereitung")
    if not parts:
        return
    st.caption("Quelle: " + " · ".join(parts))
    if pages and st.toggle("Folie anzeigen", key=f"slide_{key}", value=card.get("type") == "graphic"):
        for path, page in pages[:3]:
            try:
                png = _slide_png(path, page)
            except Exception:  # noqa: BLE001 – Vorschau ist nur ein Extra
                png = None
            if png:
                st.image(png, caption=f"Seite {page}", width="stretch")


def _edit_card(module_id: str, card: dict, key: str) -> None:
    with st.expander("Karte ist falsch / unklar – bearbeiten"):
        with st.form(f"edit_{key}"):
            front = st.text_area("Frage", card["front"], height=70)
            back = st.text_area("Musterantwort (Stichpunkte mit „- “, $LaTeX$ erlaubt)", card["back"], height=140)
            explanation = st.text_area("Erklärung", card.get("explanation", ""), height=100)
            keywords = st.text_input("Stichwörter (mit Komma getrennt)", ", ".join(card.get("keywords", [])))
            c1, c2 = st.columns(2)
            prio = c1.selectbox("Priorität", list(PRIORITY_LABELS), format_func=PRIORITY_LABELS.get,
                                index=list(PRIORITY_LABELS).index(card.get("priority", "normal")))
            review = c2.checkbox("Noch prüfen", card.get("needs_review", False))
            if st.form_submit_button("Speichern") and front.strip() and back.strip():
                card.update({"front": front.strip(), "back": back.strip(), "explanation": explanation.strip(),
                             "keywords": [k.strip() for k in keywords.split(",") if k.strip()],
                             "priority": prio, "needs_review": review})
                if not review:
                    card.pop("review_note", None)
                save_module(module_id)
                st.rerun()


def _queue(cards: list[dict], module_cards: list[dict], days: int | None, key: str, module_id: str,
           all_mode: bool) -> list[dict]:
    if all_mode:
        done = set(st.session_state.get(f"sessiondone_{key}", []))
        return sorted((c for c in cards if c["id"] not in done), key=lambda c: c["due"])
    prefs = load_settings()["learning"]
    quota = sr.new_per_day(module_cards, days, int(prefs.get("new_per_day", sr.DEFAULT_NEW_PER_DAY)))
    new_left = max(0, quota - sr.introduced_on(module_cards, date.today())) + st.session_state.get(
        f"extra_new_{module_id}", 0)
    queue = sr.due_queue(cards, days, limit=int(prefs.get("daily_review_limit", 60)), new_limit=new_left)
    # „Nochmal“-Karten erst nach ein paar anderen Karten wieder zeigen
    wait, step = st.session_state.get(f"wait_{key}", {}), st.session_state.get(f"step_{key}", 0)
    return [c for c in queue if wait.get(c["id"], 0) <= step] + [c for c in queue if wait.get(c["id"], 0) > step]


def review_session(cfg: dict, module_id: str, cards: list[dict], key: str, default_all: bool = False) -> None:
    """Abfrage der übergebenen Karten: fällige Wiederholungen + neue Karten im Tageskontingent (oder alle)."""
    module = get_module(cfg, module_id)
    days = days_until_exam(module_id)
    if not cards:
        st.caption("Noch keine Karteikarten vorhanden.")
        return
    data = load_module(module_id)
    prefs = load_settings()["learning"]
    plan = sr.daily_plan(data["cards"], days, int(prefs.get("new_per_day", sr.DEFAULT_NEW_PER_DAY)))
    stats = sr.card_stats(cards)
    c = st.columns(4)
    c[0].metric("Wiederholen", stats["due"], help="Heute fällige Wiederholungen")
    c[1].metric("Noch neu", stats["new"], help="Karten, die du noch nie gelernt hast")
    c[2].metric("Sicher", stats["mastered"], help="Karten, die du auch in 3 Wochen noch zu 90 % weißt")
    c[3].metric("Karten", stats["total"])
    if days is not None and days >= 0:
        st.caption(f"Klausur in {days} Tagen · Ziel: {sr.target_retention(days) * 100:.0f} % sicher · "
                   f"heute noch {plan['quota']} neue Karte(n) im ganzen Modul"
                   + (" · Endspurt: jede Karte kommt noch einmal dran" if days <= sr.FINAL_DAYS + 3 else ""))

    all_mode = st.toggle("Alle Karten üben (nicht nur die heute fälligen)", key=f"allmode_{key}", value=default_all)
    queue = _queue(cards, data["cards"], days, key, module_id, all_mode)
    if not queue:
        if all_mode:
            st.success("Alle Karten einmal durchgearbeitet!")
            if st.button("Nochmal von vorn", key=f"restart_{key}"):
                st.session_state[f"sessiondone_{key}"] = []
                st.rerun()
        else:
            st.success("Für heute alles geschafft!")
            if stats["new"] and st.button("10 weitere neue Karten lernen", key=f"morenew_{key}"):
                st.session_state[f"extra_new_{module_id}"] = st.session_state.get(f"extra_new_{module_id}", 0) + 10
                st.rerun()
        return

    card = queue[0]
    sr._upgrade(card)
    info = [chapter_label(data, card.get("chapter_id"))] + ([" › ".join(card["section"])] if card.get("section") else [])
    st.caption(f"Noch {len(queue)} Karte(n) in dieser Runde · " + " · ".join(info))
    state_key = f"reveal_{card['id']}"
    with st.container(border=True):
        badges = [_badge("blue", "neu")] if sr.is_new(card) else []
        if card.get("type") in TYPE_LABELS:
            badges.append(_badge("violet", TYPE_LABELS[card["type"]]))
        if card.get("priority") == "high":
            badges.append(_badge("orange", "wichtig"))
        elif card.get("priority") == "low":
            badges.append(_badge("gray", "Randthema"))
        if card.get("needs_review"):
            badges.append(_badge("red", "bitte prüfen"))
        if badges:
            st.markdown(" ".join(badges))
        st.markdown(f"#### {card['front']}")
        answer = st.text_area("Deine Antwort", key=f"answer_{card['id']}", height=100,
                              placeholder="Antwort eintippen (oder im Kopf beantworten) …")
        if not st.session_state.get(state_key):
            if st.button("Auflösen", type="primary", key=f"reveal_btn_{card['id']}"):
                st.session_state[state_key] = True
                st.rerun()
        else:
            hits = keyword_hits(answer, card.get("keywords", [])) if answer.strip() else []
            col_user, col_solution = st.columns(2)
            with col_user:
                st.markdown("**Deine Antwort**")
                st.info(answer or "_(keine Eingabe)_")
                if hits:
                    st.markdown("Stichwörter: " + " ".join(_badge("green", f"✓ {kw}") if hit else _badge("gray", kw)
                                                            for kw, hit in hits))
            with col_solution:
                st.markdown("**Lösung**")
                st.success(card["back"])
            if card.get("review_note"):
                st.warning(f"Hinweis der Prüfung: {card['review_note']}")
            if card.get("explanation"):
                with st.expander("Warum? – Erklärung"):
                    st.markdown(card["explanation"])
            _sources(data, card, f"{key}_{card['id']}")
            if answer.strip() and ai.is_available():
                if st.button("Antwort von der KI prüfen lassen", key=f"check_{card['id']}",
                             help="Günstig mit Haiku (Bruchteil eines Cents)"):
                    with st.spinner("Prüfe …"):
                        try:
                            st.session_state[f"fb_{card['id']}"] = ai.complete(
                                f"Lernkarte – Frage: {card['front']}\nMusterantwort:\n{card['back']}\n\n"
                                f"Antwort des Studierenden: {answer}\n\nBewerte knapp (max. 80 Wörter): Was ist "
                                "richtig, was fehlt oder ist falsch? Schlage eine Selbstbewertung vor "
                                "(Nochmal / Schwer / Gut / Einfach).", max_tokens=2000, effort="low", task="check")
                        except ai.AIError as exc:
                            st.error(str(exc))
                if fb := st.session_state.get(f"fb_{card['id']}"):
                    st.markdown(fb)
            suggestion = suggested_grade(hits)
            st.markdown("**Wie gut konntest du die Karte?**"
                        + (" _(Vorschlag nach deinen Stichwörtern ist markiert)_" if suggestion is not None else ""))
            nxt = sr.preview(card, days)
            for col, grade in zip(st.columns(4), sr.GRADES):
                if col.button(f"{grade['label']}  \n{sr.interval_label(nxt[grade['value']])}",
                              key=f"grade_{key}_{card['id']}_{grade['value']}", width="stretch",
                              type="primary" if grade["value"] == suggestion else "secondary"):
                    sr.review(card, grade["value"], days)
                    save_module(module_id)
                    step = st.session_state.get(f"step_{key}", 0) + 1
                    st.session_state[f"step_{key}"] = step
                    if card["interval"] == 0:
                        st.session_state.setdefault(f"wait_{key}", {})[card["id"]] = step + 3
                    elif all_mode:
                        st.session_state[f"sessiondone_{key}"] = st.session_state.get(
                            f"sessiondone_{key}", []) + [card["id"]]
                    for k in (state_key, f"answer_{card['id']}", f"fb_{card['id']}"):
                        st.session_state.pop(k, None)
                    st.rerun()
    if st.session_state.get(state_key):
        _edit_card(module_id, card, f"{key}_{card['id']}")
    if _card_chat(card, module["name"], f"{key}_{card['id']}"):
        save_module(module_id)


def generate_button(cfg: dict, module_id: str, unit: dict, existing: list[dict], key: str,
                    label: str | None = None) -> None:
    label = label or ("Karten ergänzen (neue Notizen/Dateien berücksichtigen)" if existing
                      else "Karteikarten erstellen")
    cost = learning.cards_cost_estimate(load_module(module_id), unit) if ai.is_available() else 0.0
    if st.button(label, key=f"gen_{key}", type="secondary" if existing else "primary",
                 help=f"Geschätzte Kosten: ca. {cost * 100:.0f} Cent" if cost else None):
        run_generation(cfg, module_id, unit)
    if cost and not existing:
        st.caption(f"Geschätzte Kosten: ca. {max(1, round(cost * 100))} Cent · Am besten erst nach der "
                   "Nachbereitung (betont / kurz angerissen eingetragen).")


def run_generation(cfg: dict, module_id: str, unit: dict, existing: list[dict] | None = None,
                   only: dict[str, set[int]] | None = None) -> None:
    with st.spinner("Erstelle Karteikarten … (kann 1–3 Minuten dauern)"):
        try:
            added = learning.generate_unit_cards(cfg, module_id, unit, only=only)
            st.session_state[f"genmsg_{unit['id']}"] = (
                ("success", f"{added} neue Karteikarte(n) angelegt.") if added else
                ("info", "Keine neuen Karten nötig – alles ist schon abgedeckt."))
        except ai.AIError as exc:
            st.session_state[f"genmsg_{unit['id']}"] = ("error", str(exc))
    st.rerun()


def show_generation_message(unit_id: str) -> None:
    if msg := st.session_state.pop(f"genmsg_{unit_id}", None):
        getattr(st, msg[0])(msg[1])


def coverage_panel(cfg: dict, module_id: str, unit: dict, key: str) -> None:
    """Sind alle Seiten abgedeckt? Fehlende nachholen, Karten prüfen lassen, Karten neu erstellen."""
    data = load_module(module_id)
    cards = unit_cards(data, unit)
    if not ai.is_available() or not data.get("cards_generated", {}).get(unit["id"]):
        return
    coverage = learning.card_coverage(data, unit)
    total = sum(c["pages"] for c in coverage)
    if total:
        covered = sum(len(c["covered"]) for c in coverage)
        skipped = sum(len(c["skipped"]) for c in coverage)
        missing = {c["doc"]["id"]: set(c["missing"]) for c in coverage if c["missing"]}
        line = f"**Abdeckung:** {covered} von {total} Seiten mit Karten · {skipped} bewusst übersprungen"
        if missing:
            st.warning(line + " · Noch ohne Karte: " + "; ".join(
                f"{c['doc']['filename']} S. {', '.join(map(str, c['missing']))}" for c in coverage if c["missing"]))
            cost = learning.cards_cost_estimate(data, unit, only=missing)
            if st.button(f"Fehlende Seiten nachholen (ca. {max(1, round(cost * 100))} Cent)", key=f"gapfill_{key}"):
                run_generation(cfg, module_id, unit, only=missing)
        else:
            st.success(line + " · Alles abgedeckt.")
        empty = [f"{c['doc']['filename']} S. {', '.join(map(str, c['empty']))}" for c in coverage if c["empty"]]
        if empty:
            st.caption("Ohne lesbaren Text (vermutlich nur Bild): " + "; ".join(empty) + " – lass sie unter "
                       "„Vorbereiten“ genau lesen und ergänze dann die Karten.")
    warnings = data.get("card_warnings", {}).get(unit["id"], [])
    skipped_lines = [f"- {c['doc']['filename']} S. {p}: {reason}" for c in coverage for p, reason in c["skipped"].items()]
    if warnings or skipped_lines:
        with st.expander(f"Hinweise der KI ({len(warnings)}) und übersprungene Seiten ({len(skipped_lines)})"):
            for w in warnings:
                st.warning(w)
            st.markdown("\n".join(skipped_lines))
    flagged = sum(1 for c in cards if c.get("needs_review"))
    if flagged:
        st.caption(f"{flagged} Karte(n) sind als „bitte prüfen“ markiert – du siehst den Hinweis beim Lernen.")
    c1, c2 = st.columns(2)
    if cards:
        checked = data.get("cards_checked", {}).get(unit["id"])
        cost = learning.check_cost_estimate(data, unit)
        if c1.button(f"Karten gegen die Unterlagen prüfen (ca. {max(1, round(cost * 100))} Cent)",
                     key=f"cardcheck_{key}", help="Haiku vergleicht jede Karte mit den Folien (Formeln, Fakten)."
                     + (f" Zuletzt geprüft am {checked[:10]}." if checked else "")):
            with st.spinner("Prüfe die Karten …"):
                try:
                    found = learning.check_unit_cards(cfg, module_id, unit)
                    st.session_state[f"genmsg_{unit['id']}"] = (
                        ("warning", f"{found} Karte(n) mit möglichem Fehler markiert („bitte prüfen“).") if found
                        else ("success", "Keine Fehler gefunden."))
                except ai.AIError as exc:
                    st.session_state[f"genmsg_{unit['id']}"] = ("error", str(exc))
            st.rerun()
    with c2.popover("Alle Karten neu erstellen"):
        st.markdown(f"Löscht die {len(cards)} Karte(n) dieser Einheit samt Lernstand und erstellt sie neu.")
        if st.checkbox("Ja, wirklich", key=f"regen_ok_{key}") and st.button("Löschen & neu erstellen",
                                                                            key=f"regen_{key}", type="primary"):
            learning.delete_unit_cards(module_id, unit)
            run_generation(cfg, module_id, unit)


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
            "Priorität": PRIORITY_LABELS.get(c.get("priority", "normal"), "normal"),
            "Prüfen": bool(c.get("needs_review")), "Fällig": c["due"], "Quelle": c.get("source", ""),
        } for c in cards])
        edited = st.data_editor(df, hide_index=True, width="stretch", key=f"cards_editor_{key}",
                                column_config={"id": None, "Priorität": st.column_config.SelectboxColumn(
                                    options=list(PRIORITY_LABELS.values()), required=True)},
                                disabled=["Fällig", "Quelle"])
        if st.button("Änderungen übernehmen", key=f"cards_save_{key}"):
            rows = {row["id"]: row for _, row in edited.iterrows()}
            keep = []
            for card in data["cards"]:
                row = rows.get(card["id"])
                if row is not None:
                    if row["Löschen"]:
                        continue
                    card["front"], card["back"] = str(row["Vorderseite"]), str(row["Rückseite"])
                    card["priority"] = {v: k for k, v in PRIORITY_LABELS.items()}.get(row["Priorität"], "normal")
                    card["needs_review"] = bool(row["Prüfen"])
                keep.append(card)
            data["cards"] = keep
            save_module(module_id)
            st.rerun()


def forecast(cards: list[dict]) -> None:
    if cards:
        with st.expander("Wiederholungsprognose (14 Tage, ohne neue Karten)"):
            st.bar_chart(pd.DataFrame(sr.forecast(cards)), x="Datum", y="Karten")

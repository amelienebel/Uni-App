"""Lernen: Karteikarten-Abfrage (Spaced Repetition), Karten-Chat, Kartenverwaltung – für eine oder mehrere Vorlesungen."""

from __future__ import annotations

import re
from datetime import date

import pandas as pd
import streamlit as st

from utils import ai, learning
from utils import spaced_repetition as sr
from utils.pdf_parser import render_page
from utils.storage import days_until_exam, load_module, load_settings, read_data_file, save_module
from utils.units import unit_cards

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


def _queue(cards: list[dict], module_cards: list[dict], days: int | None, module_id: str,
           all_mode: bool) -> list[dict]:
    if all_mode:
        return sorted(cards, key=lambda c: c["due"])
    prefs = load_settings()["learning"]
    quota = sr.new_per_day(module_cards, days, int(prefs.get("new_per_day", sr.DEFAULT_NEW_PER_DAY)))
    new_left = max(0, quota - sr.introduced_on(module_cards, date.today())) + st.session_state.get(
        f"extra_new_{module_id}", 0)
    return sr.due_queue(cards, days, limit=int(prefs.get("daily_review_limit", 60)), new_limit=new_left)


def review_session(cfg: dict, module_id: str, cards: list[dict], key: str, default_all: bool = False) -> None:
    """Abfrage der übergebenen Karten im Lernmodus: fällige Wiederholungen + neue Karten (oder alle)."""
    from views import cards_center

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
    queue = _queue(cards, data["cards"], days, module_id, all_mode)
    if not queue:
        st.success("Für heute alles geschafft!")
        if stats["new"] and st.button("10 weitere neue Karten lernen", key=f"morenew_{key}"):
            st.session_state[f"extra_new_{module_id}"] = st.session_state.get(f"extra_new_{module_id}", 0) + 10
            st.rerun()
        return
    st.button(f"Karteikarten lernen ({len(queue)})", key=f"focus_{key}", type="primary", icon=":material/play_arrow:",
              on_click=cards_center.start_focus, args=([[module_id, c["id"]] for c in queue],))


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
                   "Nachbereitung (sehr wichtig / nicht so wichtig / streichen eingetragen).")


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
    slim_panel(cfg, module_id, unit, cards, key)
    c1, c2, c3 = st.columns(3)
    if cards:
        cost = learning.slim_cost_estimate(data, unit)
        if c3.button(f"Karten ausdünnen (ca. {max(1, round(cost * 100))} Cent)", key=f"slim_{key}",
                     disabled=bool(data.get("card_slim", {}).get(unit["id"]))):
            with st.spinner("Gehe die Karten mit deiner Nachbereitung, den Übungen und Altklausuren durch …"):
                try:
                    proposal = learning.propose_slim(cfg, module_id, unit)
                    if not proposal.get("delete") and not proposal.get("rewrite"):
                        learning.discard_slim(module_id, unit)
                        st.session_state[f"genmsg_{unit['id']}"] = ("success", "Die Karten passen so.")
                except ai.AIError as exc:
                    st.session_state[f"genmsg_{unit['id']}"] = ("error", str(exc))
            st.rerun()
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


def slim_panel(cfg: dict, module_id: str, unit: dict, cards: list[dict], key: str) -> None:
    """Vorschlag „Karten ausdünnen“ ansehen und übernehmen oder verwerfen."""
    proposal = load_module(module_id).get("card_slim", {}).get(unit["id"])
    if not proposal:
        return
    delete, rewrite = proposal.get("delete", []), proposal.get("rewrite", [])
    with st.container(border=True):
        st.markdown(f"**Vorschlag:** {len(cards)} → {len(cards) - len(delete)} Karten · {len(rewrite)} gekürzt")
        if delete:
            with st.expander(f"Löschen ({len(delete)})"):
                st.markdown("\n".join(f"- ~~{d['front']}~~ – _{d['reason']}_" for d in delete))
        if rewrite:
            with st.expander(f"Kürzen / zusammenführen ({len(rewrite)})"):
                for r in rewrite:
                    st.markdown(f"**{r['front']}**  \n_{r['reason']}_")
                    st.markdown(r["back"])
                    st.divider()
        c1, c2 = st.columns(2)
        if c1.button("Übernehmen", key=f"slim_ok_{key}", type="primary", icon=":material/check:", width="stretch"):
            removed, changed = learning.apply_slim(module_id, unit)
            st.session_state[f"genmsg_{unit['id']}"] = (
                "success", f"{removed} Karte(n) gelöscht, {changed} gekürzt.")
            st.rerun()
        if c2.button("Verwerfen", key=f"slim_no_{key}", icon=":material/close:", width="stretch"):
            learning.discard_slim(module_id, unit)
            st.rerun()


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

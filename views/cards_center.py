"""Karteikarten: Lernstand aller Module, Empfehlung, freie Auswahl und ablenkungsfreier Lernmodus."""

from __future__ import annotations

import copy
from datetime import date

import pandas as pd
import streamlit as st

from utils import ai, learning, units
from utils import spaced_repetition as sr
from utils.config import exam_format, get_module, module_label
from utils.storage import chapter_label, days_until_exam, load_module, load_settings, save_module
from views.common import go_back, goto, micon
from views.module_tabs import study

SESSION = "cc_session"
OTHER = "__other__"  # Karten ohne Vorlesung (z. B. selbst angelegt)
_SCHEDULE_FIELDS = ("state", "stability", "difficulty", "interval", "reps", "due", "last_review", "history", "lapses")


def session_active() -> bool:
    return bool(st.session_state.get(SESSION))


def _prefs() -> tuple[int, int]:
    prefs = load_settings()["learning"]
    return int(prefs.get("new_per_day", sr.DEFAULT_NEW_PER_DAY)), int(prefs.get("daily_review_limit", 60))


# ---------------------------------------------------------------------------
# Kartenauswahl
# ---------------------------------------------------------------------------

def _pool(cfg: dict, module_id: str, lecture_ids: list[str]) -> tuple[dict, list[dict]]:
    module = get_module(cfg, module_id)
    data = load_module(module_id)
    lecs, exs = units.all_units(cfg, module, data)
    cards = units.scope_cards(data, {i for i in lecture_ids if i != OTHER}, exs, lecs)
    if OTHER in lecture_ids:
        scoped = {c["id"] for c in units.scope_cards(data, {lec["id"] for lec in lecs}, exs, lecs)}
        cards += [c for c in data["cards"] if c["id"] not in scoped]
    return data, cards


FILTERS = {
    "due": "Heute fällige + neue (empfohlen)",
    "all": "Alle Karten",
    "weak": "Nur schwache Karten",
    "new": "Nur neue (noch nie gelernt)",
    "learned": "Nur schon gelernte",
    "flagged": "Nur „bitte prüfen“",
    "high": "Nur wichtige",
}
BROWSE_FILTERS = {"all": "Alle", "weak": "Schwach", "due": "Heute fällig", "new": "Neu", "learned": "Gelernt",
                  "mastered": "Sicher", "flagged": "Bitte prüfen", "high": "Wichtig", "low": "Randthema"}


def is_weak(card: dict) -> bool:
    """Schwach: zuletzt „Gar nicht“/„Etwas“, öfter vergessen oder nur noch < 70 % Erinnerung."""
    sr._upgrade(card)
    if sr.is_new(card):
        return False
    history = card.get("history") or []
    r = sr.retrievability(card)
    return bool(history and history[-1]["grade"] <= 1) or card.get("lapses", 0) >= 2 or (r is not None and r < 0.7)


def matches(card: dict, mode: str) -> bool:
    sr._upgrade(card)
    return {
        "all": lambda: True,
        "weak": lambda: is_weak(card),
        "due": lambda: not sr.is_new(card) and sr.is_due(card),
        "new": lambda: sr.is_new(card),
        "learned": lambda: not sr.is_new(card),
        "mastered": lambda: (card.get("stability") or 0) >= sr.MASTERED_STABILITY,
        "flagged": lambda: bool(card.get("needs_review")),
        "high": lambda: card.get("priority") == "high",
        "low": lambda: card.get("priority") == "low",
    }[mode]()


def _weak_order(card: dict) -> float:
    r = sr.retrievability(card)
    return r if r is not None else 1.0


def _queue_for(cfg: dict, module_id: str, lecture_ids: list[str], mode: str) -> list[dict]:
    data, cards = _pool(cfg, module_id, lecture_ids)
    if mode != "due":
        chosen = [c for c in cards if matches(c, mode)]
        return sorted(chosen, key=_weak_order) if mode == "weak" else sorted(chosen, key=lambda c: c["due"])
    minimum, limit = _prefs()
    days = days_until_exam(module_id)
    quota = sr.new_per_day(data["cards"], days, minimum)
    new_left = max(0, quota - sr.introduced_on(data["cards"], date.today()))
    return sr.due_queue(cards, days, limit=limit, new_limit=new_left)


def _all_lectures(cfg: dict, module_id: str) -> list[str]:
    module = get_module(cfg, module_id)
    lecs, _ = units.all_units(cfg, module, load_module(module_id))
    return [lec["id"] for lec in lecs] + [OTHER]


def _start(cfg: dict, selection: dict[str, list[str]], mode: str) -> None:
    """Callback: Session starten – Karten der Module abwechselnd gemischt."""
    per_module = [[[mid, c["id"]] for c in _queue_for(cfg, mid, ids, mode)] for mid, ids in selection.items()]
    queue = []
    while any(per_module):
        for q in per_module:
            if q:
                queue.append(q.pop(0))
    if queue:
        st.session_state[SESSION] = {"queue": queue, "done": [], "view": None, "step": 0}


# ---------------------------------------------------------------------------
# Übersicht
# ---------------------------------------------------------------------------

def _overview_rows(cfg: dict) -> list[dict]:
    minimum, limit = _prefs()
    rows = []
    for module in cfg["modules"]:
        mid = module["id"]
        cards = load_module(mid)["cards"]
        days = days_until_exam(mid)
        stats = sr.card_stats(cards)
        plan = sr.daily_plan(cards, days, minimum)
        load = min(plan["reviews"], limit) + plan["new"]
        rows.append({"id": mid, "module": module, "stats": stats, "plan": plan, "days": days, "load": load,
                     "score": load * sr.exam_pressure(days)["weight"]})
    return rows


def _recommendation(cfg: dict, rows: list[dict]) -> None:
    candidates = [r for r in rows if r["load"]]
    with st.container(border=True, key="nextbox_cc"):
        st.markdown(":material/lightbulb: **Empfehlung**")
        if not candidates:
            st.markdown("#### Für heute alles geschafft")
            st.caption("Unten kannst du trotzdem beliebige Karten üben (z. B. „Alle Karten“).")
            return
        best = max(candidates, key=lambda r: r["score"])
        module = best["module"]
        parts = [f"{best['plan']['reviews']} Wiederholung(en)" if best["plan"]["reviews"] else "",
                 f"{best['plan']['new']} neue Karte(n)" if best["plan"]["new"] else ""]
        st.markdown(f"#### {micon(module)} {module['short']}: {' und '.join(p for p in parts if p)}")
        days = best["days"]
        st.caption((f"Klausur in {days} Tagen" if days is not None and days >= 0 else "Kein Klausurtermin")
                   + f" · Klausurformat: {exam_format(module)['label']}")
        c1, c2 = st.columns(2)
        c1.button("Jetzt lernen", key="cc_reco", type="primary", width="stretch", icon=":material/play_arrow:",
                  on_click=_start, args=(cfg, {best["id"]: _all_lectures(cfg, best["id"])}, "due"))
        if len(candidates) > 1:
            c2.button(f"Alles Fällige aus {len(candidates)} Modulen", key="cc_all_due", width="stretch",
                      on_click=_start, args=(cfg, {r["id"]: _all_lectures(cfg, r["id"]) for r in candidates}, "due"))


def _stats_table(rows: list[dict]) -> None:
    total = sum(r["stats"]["total"] for r in rows)
    c = st.columns(4)
    c[0].metric("Karten", total)
    c[1].metric("Heute fällig", sum(r["load"] - r["plan"]["new"] for r in rows))
    c[2].metric("Neu heute", sum(r["plan"]["new"] for r in rows))
    c[3].metric("Sicher", f"{sum(r['stats']['mastered'] for r in rows) / total * 100:.0f} %" if total else "–")
    st.dataframe(pd.DataFrame([{
        "Modul": r["module"]["short"],
        "Karten": r["stats"]["total"],
        "Wiederholen": r["plan"]["reviews"],
        "Neu heute": r["plan"]["new"],
        "Noch nie gelernt": r["stats"]["new"],
        "Sicher": r["stats"]["mastery"],
        "Klausur": f"in {r['days']} Tagen" if r["days"] is not None and r["days"] >= 0 else "–",
        "Klausurformat": exam_format(r["module"])["label"],
    } for r in rows]), hide_index=True, width="stretch",
        column_config={"Sicher": st.column_config.ProgressColumn(min_value=0, max_value=1, format="percent")})


def _lecture_option(lec: dict, n: int) -> str:
    return f"{units.short_label(lec)} – {lec['topic'][:40]} ({n})"


def _manual(cfg: dict, rows: list[dict]) -> None:
    st.subheader(":material/checklist: Selbst auswählen")
    with_cards = [r["id"] for r in rows if r["stats"]["total"]]
    if not with_cards:
        st.caption("Noch keine Karteikarten. Sie entstehen auf den Vorlesungsseiten (Reiter „Lernen“).")
        return
    st.session_state.setdefault("cc_mods", with_cards)
    st.session_state["cc_mods"] = [m for m in st.session_state["cc_mods"] if m in with_cards]
    modules = st.multiselect("Module", with_cards, key="cc_mods", format_func=lambda m: module_label(cfg, m))
    selection = {}
    for mid in modules:
        module = get_module(cfg, mid)
        data = load_module(mid)
        lecs, exs = units.all_units(cfg, module, data)
        counts = {lec["id"]: len(units.scope_cards(data, {lec["id"]}, exs, lecs)) for lec in lecs}
        scoped = {c["id"] for c in units.scope_cards(data, set(counts), exs, lecs)}
        other = sum(1 for c in data["cards"] if c["id"] not in scoped)
        options = [i for i, n in counts.items() if n] + ([OTHER] if other else [])
        labels = {lec["id"]: _lecture_option(lec, counts[lec["id"]]) for lec in lecs}
        labels[OTHER] = f"Weitere Karten ohne Vorlesung ({other})"
        key = f"cc_lecs_{mid}"
        st.session_state.setdefault(key, options)
        st.session_state[key] = [i for i in st.session_state[key] if i in options]
        selection[mid] = st.multiselect(f"{module['short']}: Vorlesungen", options, key=key,
                                        format_func=labels.get, placeholder="Keine Vorlesung gewählt")
    selection = {mid: ids for mid, ids in selection.items() if ids}
    mode = st.selectbox("Welche Karten?", list(FILTERS), key="cc_mode", format_func=FILTERS.get)
    n = sum(len(_queue_for(cfg, mid, ids, mode)) for mid, ids in selection.items())
    st.button(f"Lernsession starten ({n} Karten)", key="cc_start", type="primary", disabled=not n,
              icon=":material/play_arrow:", on_click=_start, args=(cfg, selection, mode))
    if not n and selection and mode == "due":
        st.caption("In dieser Auswahl ist heute nichts fällig – wähle „Alle Karten“.")


PAGE_SIZE = 25


def _start_cards(entries: list[list[str]]) -> None:
    if entries:
        st.session_state[SESSION] = {"queue": entries, "done": [], "view": None, "step": 0}


def start_focus(entries: list[list[str]]) -> None:
    """Callback von anderen Seiten: Lernmodus direkt öffnen, „Beenden“ führt dorthin zurück."""
    if entries:
        st.session_state[SESSION] = {"queue": entries, "done": [], "view": None, "step": 0, "return": True}
        goto("cards")


def learn_due(cfg: dict, module_id: str) -> None:
    """Callback: alle heute fälligen + neuen Karten eines Moduls im Lernmodus lernen."""
    start_focus([[module_id, c["id"]] for c in _queue_for(cfg, module_id, _all_lectures(cfg, module_id), "due")])


def _delete_cards(entries: list[list[str]]) -> None:
    by_module: dict[str, set[str]] = {}
    for mid, cid in entries:
        by_module.setdefault(mid, set()).add(cid)
    for mid, ids in by_module.items():
        data = load_module(mid)
        data["cards"] = [c for c in data["cards"] if c["id"] not in ids]
        save_module(mid)


def _edit_form(module_id: str, card: dict, key: str) -> None:
    with st.form(f"ccedit_{key}"):
        front = st.text_area("Frage", card["front"], height=80)
        back = st.text_area("Antwort", card["back"], height=150)
        explanation = st.text_area("Erklärung", card.get("explanation", ""), height=110)
        c1, c2 = st.columns(2)
        prio = c1.selectbox("Priorität", list(study.PRIORITY_LABELS), format_func=study.PRIORITY_LABELS.get,
                            index=list(study.PRIORITY_LABELS).index(card.get("priority", "normal")))
        review = c2.checkbox("Bitte prüfen", card.get("needs_review", False))
        if st.form_submit_button("Speichern", type="primary") and front.strip() and back.strip():
            card.update({"front": front.strip(), "back": back.strip(), "explanation": explanation.strip(),
                         "priority": prio, "needs_review": review})
            if not review:
                card.pop("review_note", None)
            save_module(module_id)
            st.rerun()


def _browse(cfg: dict, rows: list[dict]) -> None:
    st.subheader(":material/view_list: Alle Karten")
    with_cards = [r["id"] for r in rows if r["stats"]["total"]]
    if not with_cards:
        return
    c1, c2, c3 = st.columns([2, 1, 2])
    modules = c1.multiselect("Module", with_cards, default=with_cards, key="cb_mods",
                             format_func=lambda m: module_label(cfg, m, short=True))
    mode = c2.selectbox("Filter", list(BROWSE_FILTERS), key="cb_filter", format_func=BROWSE_FILTERS.get)
    search = c3.text_input("Suche", key="cb_search", placeholder="Begriff in Frage oder Antwort")
    found = []
    for mid in modules:
        data = load_module(mid)
        for card in data["cards"]:
            if matches(card, mode) and (not search or search.lower() in (card["front"] + card["back"]).lower()):
                found.append((mid, data, card))
    if mode == "weak":
        found.sort(key=lambda x: _weak_order(x[2]))
    entries = [[mid, card["id"]] for mid, _, card in found]
    b1, b2, b3 = st.columns([2, 2, 1], vertical_alignment="center")
    b1.button(f"Diese Karten lernen ({len(found)})", key="cb_learn", type="primary", icon=":material/play_arrow:",
              disabled=not found, on_click=_start_cards, args=(entries,), width="stretch")
    show_back = b3.toggle("Antworten", key="cb_back")
    with b2.popover(f"Alle {len(found)} löschen", icon=":material/delete:", disabled=not found, width="stretch"):
        st.markdown(f"Löscht {len(found)} Karte(n) samt Lernstand.")
        if st.checkbox("Ja, wirklich", key="cb_delall_ok"):
            st.button("Endgültig löschen", key="cb_delall", type="primary", on_click=_delete_cards, args=(entries,))
    if not found:
        st.caption("Keine Karten für diesen Filter.")
        return
    pages = (len(found) - 1) // PAGE_SIZE + 1
    page = st.session_state.get("cb_page", 1)
    page = min(max(1, page), pages)
    for mid, data, card in found[(page - 1) * PAGE_SIZE:page * PAGE_SIZE]:
        with st.container(border=True, key=f"cbrow_{mid}_{card['id']}"):
            c1, c2, c3 = st.columns([10, 1.3, 0.7], vertical_alignment="top")
            with c1:
                _badges(card)
                st.markdown(f"**{card['front']}**")
                if show_back:
                    st.markdown(card["back"])
                info = [module_label(cfg, mid, short=True), chapter_label(data, card.get("chapter_id"))]
                if not sr.is_new(card):
                    info.append(f"fällig {card['due'][8:10]}.{card['due'][5:7]}.")
                st.caption(" · ".join(x for x in info if x))
            with c2.popover("", icon=":material/edit:", help="Bearbeiten"):
                _edit_form(mid, card, f"b_{card['id']}")
            c3.button("", key=f"cbdel_{card['id']}", icon=":material/delete:", type="tertiary", help="Löschen",
                      on_click=_delete_cards, args=([[mid, card["id"]]],))
    if pages > 1:
        st.number_input(f"Seite (von {pages})", 1, pages, page, key="cb_page")


def _overview(cfg: dict) -> None:
    st.title(":material/style: Karteikarten")
    rows = _overview_rows(cfg)
    _recommendation(cfg, rows)
    st.subheader(":material/monitoring: Lernstand")
    _stats_table(rows)
    all_cards = [c for r in rows for c in load_module(r["id"])["cards"]]
    study.forecast(all_cards)
    st.divider()
    _manual(cfg, rows)
    st.divider()
    _browse(cfg, rows)


# ---------------------------------------------------------------------------
# Lernsession (Focus Mode)
# ---------------------------------------------------------------------------

def _find(module_id: str, card_id: str) -> tuple[dict, dict | None]:
    data = load_module(module_id)
    return data, next((c for c in data["cards"] if c["id"] == card_id), None)


def _end() -> None:
    sess = st.session_state.pop(SESSION, None)
    if sess and sess.get("return"):
        go_back()


def _back() -> None:
    sess = st.session_state[SESSION]
    sess["view"] = len(sess["done"]) - 1 if sess["view"] is None else max(0, sess["view"] - 1)


def _forward() -> None:
    sess = st.session_state[SESSION]
    sess["view"] = None if sess["view"] is None or sess["view"] >= len(sess["done"]) - 1 else sess["view"] + 1


def _apply_grade(sess: dict, module_id: str, card: dict, grade: int) -> None:
    """Bewertung speichern; „Gar nicht“-Karten kommen nach ein paar anderen Karten wieder."""
    sr.review(card, grade, days_until_exam(module_id))
    save_module(module_id)
    if card["interval"] == 0:
        sess["queue"].insert(min(3, len(sess["queue"])), [module_id, card["id"]])


def _grade_buttons(card: dict, module_id: str, key: str, suggestion: int | None = None,
                   current: int | None = None, before: dict | None = None) -> int | None:
    nxt = sr.preview({**card, **(before or {})}, days_until_exam(module_id))
    chosen = None
    for col, grade in zip(st.columns(4), sr.GRADES):
        highlight = grade["value"] == (suggestion if current is None else current)
        if col.button(f"{grade['label']}  \n{sr.interval_label(nxt[grade['value']])}", key=f"{key}_{grade['value']}",
                      width="stretch", type="primary" if highlight else "secondary"):
            chosen = grade["value"]
    return chosen


def _badges(card: dict) -> None:
    badges = [study._badge("blue", "neu")] if sr.is_new(card) else []
    if card.get("type") in study.TYPE_LABELS:
        badges.append(study._badge("violet", study.TYPE_LABELS[card["type"]]))
    if card.get("priority") == "high":
        badges.append(study._badge("orange", "wichtig"))
    if card.get("needs_review"):
        badges.append(study._badge("red", "bitte prüfen"))
    if badges:
        st.markdown(" ".join(badges))


def _caption(cfg: dict, module_id: str, data: dict, card: dict) -> None:
    info = [module_label(cfg, module_id, short=True)]
    if card.get("chapter_id"):
        info.append(chapter_label(data, card["chapter_id"]))
    if card.get("section"):
        info.append(" › ".join(card["section"]))
    st.caption(" · ".join(x for x in info if x))


def _solution(data: dict, card: dict, answer: str, key: str) -> list[tuple[str, bool]]:
    hits = study.keyword_hits(answer, card.get("keywords", [])) if answer.strip() else []
    col_user, col_solution = st.columns(2)
    with col_user:
        st.markdown("**Deine Antwort**")
        st.info(answer or "_(keine Eingabe)_")
        if hits:
            st.markdown("Stichwörter: " + " ".join(study._badge("green", f"✓ {kw}") if hit else study._badge("gray", kw)
                                                    for kw, hit in hits))
    with col_solution:
        st.markdown("**Lösung**")
        st.success(card["back"])
    if card.get("review_note"):
        st.warning(f"Hinweis der Prüfung: {card['review_note']}")
    if card.get("explanation"):
        with st.expander("Erklärung – warum ist das so?", icon=":material/lightbulb:"):
            st.markdown(card["explanation"])
    study._sources(data, card, key)
    return hits


def _feedback(module_id: str, card: dict, key: str) -> None:
    """Feedback zur Karte: KI formuliert sie um, selbst bearbeiten oder löschen."""
    with st.popover("Feedback zur Karte", icon=":material/feedback:"):
        text = st.text_area("Was soll anders sein?", key=f"{key}_fbtext", height=90,
                            placeholder="z. B. Frage genauer formulieren, Antwort kürzer, Formel fehlt …")
        if st.button("Karte überarbeiten", key=f"{key}_fbgo", type="primary", icon=":material/auto_fix_high:",
                     disabled=not text.strip() or not ai.is_available()):
            with st.spinner("Überarbeite die Karte …"):
                try:
                    learning.rewrite_card(module_id, card, text.strip())
                except ai.AIError as exc:
                    st.error(str(exc))
                    return
            st.rerun()
        if card.get("previous"):
            st.button("Letzte Überarbeitung rückgängig", key=f"{key}_fbundo", icon=":material/undo:",
                      on_click=learning.undo_rewrite, args=(module_id, card))
        st.divider()
        st.markdown("**Selbst bearbeiten**")
        _edit_form(module_id, card, f"fb_{key}")
        if st.button("Karte löschen", key=f"{key}_fbdel", icon=":material/delete:"):
            _delete_cards([[module_id, card["id"]]])
            sess = st.session_state[SESSION]
            sess["queue"] = [q for q in sess["queue"] if q != [module_id, card["id"]]]
            st.rerun()


def _reveal(key: str) -> None:
    st.session_state[f"{key}_given"] = st.session_state.get(f"{key}_answer", "")
    st.session_state[f"{key}_reveal"] = True


def answer_form(key: str) -> None:
    """Antwortfeld: Enter schickt die Antwort ab und löst auf."""
    with st.form(f"{key}_form", border=False):
        st.text_input("Deine Antwort", key=f"{key}_answer", placeholder="Antwort eintippen und Enter drücken …")
        st.form_submit_button("Auflösen", type="primary", width="stretch", on_click=_reveal, args=(key,))


def _current(cfg: dict, sess: dict, module_id: str, data: dict, card: dict) -> None:
    key = f"cc_{sess['step']}_{card['id']}"
    sr._upgrade(card)
    _caption(cfg, module_id, data, card)
    with st.container(border=True):
        _badges(card)
        st.markdown(f"### {card['front']}")
        if not st.session_state.get(f"{key}_reveal"):
            answer_form(key)
        else:
            answer = st.session_state.get(f"{key}_given", "")
            hits = _solution(data, card, answer, key)
            st.markdown("**Wie gut konntest du die Karte?**")
            grade = _grade_buttons(card, module_id, f"{key}_grade", suggestion=study.suggested_grade(hits))
            if grade is not None:
                before = {f: copy.deepcopy(card[f]) for f in _SCHEDULE_FIELDS if f in card}
                sess["queue"].pop(0)
                _apply_grade(sess, module_id, card, grade)
                sess["done"].append({"mid": module_id, "cid": card["id"], "grade": grade, "answer": answer,
                                     "before": before})
                sess["step"] += 1
                st.rerun()
    c1, c2 = st.columns([1, 1], vertical_alignment="bottom")
    with c1:
        _feedback(module_id, card, key)
    study.priority_picker(c2, module_id, card, key)
    if study._card_chat(card, get_module(cfg, module_id)["name"], key):
        save_module(module_id)


def _past(cfg: dict, sess: dict) -> None:
    """Schon bewertete Karte noch einmal ansehen – Bewertung lässt sich ändern."""
    entry = sess["done"][sess["view"]]
    module_id = entry["mid"]
    data, card = _find(module_id, entry["cid"])
    if card is None:
        st.caption("Diese Karte wurde inzwischen gelöscht.")
        return
    key = f"ccpast_{sess['view']}_{card['id']}"
    labels = {g["value"]: g["label"] for g in sr.GRADES}
    _caption(cfg, module_id, data, card)
    st.caption(f"Karte {sess['view'] + 1} von {len(sess['done'])} bewerteten · deine Bewertung: "
               f"**{labels[entry['grade']]}**")
    with st.container(border=True):
        _badges(card)
        st.markdown(f"### {card['front']}")
        _solution(data, card, entry["answer"], key)
        st.markdown("**Bewertung ändern?**")
        grade = _grade_buttons(card, module_id, f"{key}_grade", current=entry["grade"], before=entry["before"])
        if grade is not None and grade != entry["grade"]:
            for field in _SCHEDULE_FIELDS:
                card.pop(field, None)
            card.update(copy.deepcopy(entry["before"]))
            pending = [module_id, card["id"]]
            sess["queue"] = [q for q in sess["queue"] if q != pending]
            _apply_grade(sess, module_id, card, grade)
            entry["grade"] = grade
            st.rerun()
    c1, c2 = st.columns([1, 1], vertical_alignment="bottom")
    with c1:
        _feedback(module_id, card, key)
    study.priority_picker(c2, module_id, card, key)
    if study._card_chat(card, get_module(cfg, module_id)["name"], key):
        save_module(module_id)
    st.button("Weiter" if sess["view"] < len(sess["done"]) - 1 else "Zur aktuellen Karte", key="cc_forward",
              icon=":material/arrow_forward:", type="primary", on_click=_forward)


def _finished(sess: dict) -> None:
    st.success(f"Geschafft! {len(sess['done'])} Bewertung(en) in dieser Session.")
    counts = {g["label"]: sum(1 for e in sess["done"] if e["grade"] == g["value"]) for g in sr.GRADES}
    st.markdown(" · ".join(f"**{label}**: {n}" for label, n in counts.items()))
    st.button("Fertig" if sess.get("return") else "Zurück zur Übersicht", key="cc_finish", type="primary",
              on_click=_end)


def _session(cfg: dict) -> None:
    sess = st.session_state[SESSION]
    # gelöschte Karten überspringen
    while sess["queue"] and _find(*sess["queue"][0])[1] is None:
        sess["queue"].pop(0)
    nav = st.columns([1, 2, 1], vertical_alignment="center")
    nav[0].button("Zurück", key="cc_back", icon=":material/arrow_back:", on_click=_back,
                  disabled=not sess["done"] or sess["view"] == 0, help="Vorige Karte noch einmal ansehen")
    done, left = len(sess["done"]), len(sess["queue"])
    nav[1].progress(done / (done + left) if done + left else 1.0, text=f"{done} bewertet · noch {left}")
    nav[2].button("Beenden", key="cc_end", icon=":material/close:", on_click=_end, width="stretch")
    if sess["view"] is not None:
        _past(cfg, sess)
    elif not sess["queue"]:
        _finished(sess)
    else:
        module_id, card_id = sess["queue"][0]
        data, card = _find(module_id, card_id)
        _current(cfg, sess, module_id, data, card)


def render(cfg: dict) -> None:
    if session_active():
        _session(cfg)
    else:
        _overview(cfg)

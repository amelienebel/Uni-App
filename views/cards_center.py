"""Karteikarten-Lernzentrum: Lernstand aller Module, Empfehlung, freie Auswahl und ablenkungsfreier Lernmodus."""

from __future__ import annotations

import copy
from datetime import date

import pandas as pd
import streamlit as st

from utils import spaced_repetition as sr
from utils import units
from utils.config import exam_format, get_module, module_label
from utils.storage import chapter_label, days_until_exam, load_module, load_settings, save_module
from views.common import micon
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


def _queue_for(cfg: dict, module_id: str, lecture_ids: list[str], mode: str) -> list[dict]:
    data, cards = _pool(cfg, module_id, lecture_ids)
    if mode == "all":
        return sorted(cards, key=lambda c: c["due"])
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
            st.caption("Unten kannst du trotzdem beliebige Karten üben (Modus „Alle Karten“).")
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
    mode = st.radio("Welche Karten?", ["due", "all"], key="cc_mode", horizontal=True,
                    format_func={"due": "Heute fällige + neue (empfohlen)", "all": "Alle Karten der Auswahl"}.get)
    n = sum(len(_queue_for(cfg, mid, ids, mode)) for mid, ids in selection.items())
    st.button(f"Lernsession starten ({n} Karten)", key="cc_start", type="primary", disabled=not n,
              icon=":material/play_arrow:", on_click=_start, args=(cfg, selection, mode))
    if not n and selection and mode == "due":
        st.caption("In dieser Auswahl ist heute nichts fällig – wähle „Alle Karten der Auswahl“.")


def _overview(cfg: dict) -> None:
    st.title(":material/style: Karteikarten-Lernzentrum")
    rows = _overview_rows(cfg)
    _recommendation(cfg, rows)
    st.subheader(":material/monitoring: Lernstand")
    _stats_table(rows)
    all_cards = [c for r in rows for c in load_module(r["id"])["cards"]]
    study.forecast(all_cards)
    st.divider()
    _manual(cfg, rows)


# ---------------------------------------------------------------------------
# Lernsession (Focus Mode)
# ---------------------------------------------------------------------------

def _find(module_id: str, card_id: str) -> tuple[dict, dict | None]:
    data = load_module(module_id)
    return data, next((c for c in data["cards"] if c["id"] == card_id), None)


def _end() -> None:
    st.session_state.pop(SESSION, None)


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


def _current(cfg: dict, sess: dict, module_id: str, data: dict, card: dict) -> None:
    key = f"cc_{sess['step']}_{card['id']}"
    sr._upgrade(card)
    _caption(cfg, module_id, data, card)
    with st.container(border=True):
        _badges(card)
        st.markdown(f"### {card['front']}")
        answer = st.text_area("Deine Antwort", key=f"{key}_answer", height=110,
                              placeholder="Antwort eintippen (oder im Kopf beantworten) …")
        if not st.session_state.get(f"{key}_reveal"):
            if st.button("Auflösen", key=f"{key}_revealbtn", type="primary", width="stretch"):
                st.session_state[f"{key}_reveal"] = True
                st.rerun()
        else:
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
    if study._card_chat(card, get_module(cfg, module_id)["name"], key):
        save_module(module_id)
    st.button("Weiter" if sess["view"] < len(sess["done"]) - 1 else "Zur aktuellen Karte", key="cc_forward",
              icon=":material/arrow_forward:", type="primary", on_click=_forward)


def _finished(sess: dict) -> None:
    st.success(f"Geschafft! {len(sess['done'])} Bewertung(en) in dieser Session.")
    counts = {g["label"]: sum(1 for e in sess["done"] if e["grade"] == g["value"]) for g in sr.GRADES}
    st.markdown(" · ".join(f"**{label}**: {n}" for label, n in counts.items()))
    st.button("Zurück zum Lernzentrum", key="cc_finish", type="primary", on_click=_end)


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

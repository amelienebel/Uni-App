"""Neues Lernsystem auf der Vorlesungsseite: Reiter „Nacharbeiten“ und „Vorlesungs-Check“.

Nacharbeiten: 1 Folien sichten (Klick aufs Bild = nicht relevant; Wiederholungen und Orga-Folien vorgeschlagen) ·
2 Alles genau lesen · 3 Hinweise zur Quiz-Erstellung (Umfang, Wichtig, Streichen, Sonstiger Hinweis) ·
4 Themen & Minithemen (= Nacharbeiten abschließen).
"""

from __future__ import annotations

import streamlit as st

from utils import ai, mastery, planner, sessions, topics
from utils.config import get_module, load_config
from utils.storage import load_module, load_todos, now_iso, read_data_file, save_module, save_todos
from utils.units import lecture_notes
from views import progress, session_ui
from views.common import LECTURE_TAB, PAGES

THUMB_SCALE = 0.6


@st.cache_data(show_spinner=False, max_entries=400)
def _thumb(path: str, page: int) -> bytes | None:
    from utils.pdf_parser import render_page

    return render_page(read_data_file(path), page, scale=THUMB_SCALE)


def set_done(module_id: str, lec: dict, field: str, value: bool = True) -> None:
    state = load_todos()
    state[planner.lecture_key(module_id, lec["date"], field)] = value
    save_todos()
    if field == "nachbereitet":
        data = load_module(module_id)
        planner.sync_chapter_status(get_module(load_config(), module_id), data, lec.get("chapter_id"), field, state)
        save_module(module_id)


def _msg(module_id: str, kind: str, text: str) -> None:
    st.session_state[f"nmsg_{module_id}"] = (kind, text)


# ---------------------------------------------------------------------------
# 1 · Folien sichten
# ---------------------------------------------------------------------------

def _slide_grid(module_id: str, doc: dict, data: dict, lec: dict) -> None:
    pages = len(topics.get_document_pages(doc)) or int(doc.get("n_pages") or 0)
    skip = topics.excluded(doc)
    notes = lecture_notes(data, lec["id"])
    counting = [p for p in range(1, pages + 1) if p not in skip and topics.in_scope(notes, p, pages)]
    st.caption(f"{doc['filename']} · {len(counting)} von {pages} Folien zählen")
    cols = st.columns(3)
    for p in range(1, pages + 1):
        out = p in skip
        outside = not topics.in_scope(notes, p, pages)
        state = "off" if out else "scope" if outside else "on"
        with cols[(p - 1) % 3]:
            with st.container(key=f"slide_{state}_{doc['id']}_{p}"):
                try:
                    png = _thumb(doc["path"], p)
                except Exception:  # noqa: BLE001
                    png = None
                if png:
                    st.image(png, width="stretch")
                else:
                    st.caption(f"Folie {p}")
                st.button("Ein-/ausblenden", key=f"sltg_{doc['id']}_{p}", on_click=topics.toggle_slide,
                          args=(module_id, doc["id"], p), width="stretch")
            label = f"Folie {p}"
            if out:
                label += f" · nicht relevant ({skip[p]})"
            elif outside:
                label += " · außerhalb des Umfangs"
            st.caption(label)


def _carry_box(module_id: str, data: dict, lec: dict, lecs: list[dict]) -> None:
    offer = topics.offered_carry(data, lec, lecs)
    if not offer:
        return
    with st.container(border=True, key=f"carry_{lec['id'].replace(':', '_')}"):
        for c in offer:
            pages = c["pages"]
            st.markdown(f":material/redo: **Noch offen aus Vorlesung {c['from_nr']}:** Folien {pages[0]}–{pages[-1]}")
        b1, b2 = st.columns(2)
        b1.button("In diese Vorlesung übernehmen", key=f"carry_ok_{lec['id']}", type="primary", width="stretch",
                  on_click=topics.accept_carry, args=(module_id, lec["id"], offer, True))
        b2.button("Nicht übernehmen", key=f"carry_no_{lec['id']}", width="stretch",
                  on_click=topics.accept_carry, args=(module_id, lec["id"], offer, False))


# ---------------------------------------------------------------------------
# 3 · Hinweise zur Quiz-Erstellung
# ---------------------------------------------------------------------------

def _hints_form(module_id: str, data: dict, lec: dict) -> None:
    notes = lecture_notes(data, lec["id"])
    sc = topics.scope(notes)
    n_pages = max([len(topics.get_document_pages(d)) for d in topics.slide_docs(data, lec)] or [0])
    with st.form(f"qhints_{module_id}_{lec['id']}"):
        mode = st.radio("Umfang", ["Ganze Vorlesung", "Nur bestimmte Folien"], horizontal=True,
                        index=1 if sc["mode"] == "range" else 0)
        c1, c2 = st.columns(2)
        first = c1.number_input("Von Folie", min_value=1, value=sc["from"], step=1)
        last = c2.number_input("Bis Folie", min_value=1, value=sc["to"] or max(1, n_pages), step=1)
        with st.container(border=True, key=f"hintbox_{lec['id'].replace(':', '_')}"):
            hint = st.text_area(":material/edit_note: **Sonstiger Hinweis**", notes["card_hint"], height=90,
                                placeholder="z. B. Herleitung auf Folie 12 nicht relevant; Beispiel X lernen")
        c3, c4 = st.columns(2)
        important = c3.text_area("Wichtig", notes["emphasized"], height=110)
        skip = c4.text_area("Streichen", notes["skip"], height=110)
        text = st.text_area("Eigene Notizen", notes["text"], height=110)
        if st.form_submit_button("Speichern", type="primary", width="stretch"):
            notes.update({"scope": {"mode": "range" if mode == "Nur bestimmte Folien" else "all",
                                    "from": int(first), "to": int(last)},
                          "card_hint": hint, "emphasized": important, "skip": skip, "text": text,
                          "updated_at": now_iso()})
            save_module(module_id)
            st.rerun()


# ---------------------------------------------------------------------------
# 4 · Themen & Minithemen
# ---------------------------------------------------------------------------

def _toggle_mt(module_id: str, lec_id: str, mt_id: str, key: str) -> None:
    topics.set_excluded(module_id, lec_id, mt_id, not st.session_state[key])


def topic_tree(module_id: str, data: dict, lec: dict, editable: bool = True) -> None:
    entry = topics.lecture_topics(data, lec["id"]) or {}
    for t in entry.get("topics", []):
        with st.container(border=True, key=f"topic_{'e' if editable else 'v'}_{t['id']}"):
            mts = t["minitopics"]
            active = [m for m in mts if not m.get("excluded")]
            asked, total = mastery.coverage(data, [{**m, "lecture_id": lec["id"]} for m in active])
            st.markdown(f"**{t['title']}** · {asked}/{total} abgefragt")
            for m in mts:
                mt = {**m, "lecture_id": lec["id"], "topic": t["title"]}
                status = mastery.status(data, mt) if not m.get("excluded") else "ausgeschlossen"
                c1, c2 = st.columns([6, 2], vertical_alignment="center")
                color = mastery.STATUS_COLORS.get(status, "#9AA3AF")
                meta = topics.KINDS.get(m.get("kind"), "") + (" · wichtig" if m.get("importance") == "hoch" else "")
                c1.markdown(f"<span class='mt-dot' style='background:{color}'></span>"
                            f"{'<s>' if m.get('excluded') else ''}{m['title']}{'</s>' if m.get('excluded') else ''}"
                            f" <span class='small-muted'>{meta} · {status}</span>", unsafe_allow_html=True)
                if editable:
                    key = f"mtinc_{m['id']}"
                    st.session_state[key] = not m.get("excluded")
                    c2.toggle("zählt", key=key, on_change=_toggle_mt, args=(module_id, lec["id"], m["id"], key))
    if entry.get("no_minitopic") and editable:
        with st.expander("Ohne Minithema"):
            for x in entry["no_minitopic"]:
                st.caption(f"Seite(n) {', '.join(map(str, x['pages']))}: {x['reason']}")


def _create(cfg: dict, module_id: str, lec: dict, lecs: list[dict]) -> None:
    with st.spinner("Claude zerlegt die Vorlesung in Themen und Minithemen …"):
        try:
            n = topics.create_topics(cfg, module_id, lec, lecs)
        except ai.AIError as exc:
            _msg(module_id, "error", str(exc))
            return
    set_done(module_id, lec, "nachbereitet")
    _msg(module_id, "success", f"{n} Minithemen angelegt – Nacharbeiten erledigt. Weiter mit dem Vorlesungs-Check.")


def render(cfg: dict, module_id: str, lec: dict, lecs: list[dict]) -> None:
    data = load_module(module_id)
    if msg := st.session_state.pop(f"nmsg_{module_id}", None):
        getattr(st, msg[0])(msg[1])
    docs = topics.slide_docs(data, lec)
    topics.ensure_suggestions(module_id, data, lec, lecs)
    has_topics = bool(topics.lecture_topics(data, lec["id"]))

    st.markdown("#### 1 · Folien sichten")
    _carry_box(module_id, data, lec, lecs)
    if not docs:
        st.caption("Noch keine Folien hochgeladen (Reiter Dateien).")
    for doc in docs:
        with st.expander(f"Folien – {doc['filename']}", expanded=not has_topics, icon=":material/view_module:"):
            _slide_grid(module_id, doc, data, lec)

    st.markdown("#### 2 · Genau lesen")
    unread = topics.unread_pages(data, lec)
    if unread:
        n = sum(len(p) for p in unread.values())
        cost = topics.read_cost(data, lec) * 100
        if st.button(f"{n} Folien genau lesen (ca. {cost:.1f} Cent)", key=f"readall_{lec['id']}", type="primary",
                     icon=":material/image_search:", disabled=not ai.is_available()):
            with st.spinner(f"Lese {n} Folien genau (auch Grafiken und Tabellen) …"):
                try:
                    _msg(module_id, "success", topics.read_all(cfg, module_id, lec))
                except ai.AIError as exc:
                    _msg(module_id, "error", str(exc))
            st.rerun()
    elif docs:
        st.caption("Alle zählenden Folien sind genau gelesen.")

    st.markdown("#### 3 · Hinweise zur Quiz-Erstellung")
    _hints_form(module_id, data, lec)

    st.markdown("#### 4 · Themen & Minithemen")
    if has_topics:
        topic_tree(module_id, data, lec)
        c1, c2 = st.columns(2)
        c1.button("Zum Vorlesungs-Check", key=f"tocheck_{lec['id']}", type="primary", icon=":material/fact_check:",
                  width="stretch", on_click=_goto_tab, args=(lec["id"], "check"))
        with c2.popover("Minithemen neu erstellen", icon=":material/refresh:", width="stretch"):
            st.caption("Gleichnamige Minithemen behalten ihren Wissensstand.")
            if st.button(f"Neu erstellen (ca. {topics.cost_estimate(data, lec) * 100:.0f} Cent)",
                         key=f"retopics_{lec['id']}", disabled=not ai.is_available()):
                _create(cfg, module_id, lec, lecs)
                st.rerun()
    else:
        cost = topics.cost_estimate(data, lec) * 100 if ai.is_available() else 0
        if st.button(f"Nacharbeiten abschließen – Minithemen erstellen (ca. {cost:.0f} Cent)",
                     key=f"mktopics_{lec['id']}", type="primary", icon=":material/account_tree:", width="stretch",
                     disabled=not ai.is_available()):
            _create(cfg, module_id, lec, lecs)
            st.rerun()

    st.markdown("**Tafelbilder & Screenshots**")
    from views.module_tabs.lecture_page import _board_images

    _board_images(get_module(cfg, module_id), module_id, lec, lecture_notes(data, lec["id"]))


def _goto_tab(lec_id: str, tab: str) -> None:
    st.session_state[f"ltab_next_{lec_id}"] = LECTURE_TAB[tab]


# ---------------------------------------------------------------------------
# Reiter „Vorlesungs-Check“
# ---------------------------------------------------------------------------

def settings_inputs(key: str, with_n: bool = False) -> dict:
    out = {}
    if with_n:
        out["n"] = st.segmented_control("Anzahl Fragen", list(sessions.TRAINING_SIZES), default=10,
                                        key=f"{key}_n", format_func=str) or 10
    c1, c2 = st.columns(2)
    out["calculator"] = c1.toggle("Taschenrechner", key=f"{key}_calc")
    out["notepad"] = c2.toggle("Notizblatt", key=f"{key}_pad")
    return out


def start_check(cfg: dict, module_id: str, lec: dict, settings: dict) -> None:
    with st.spinner("Stelle deinen Vorlesungs-Check zusammen …"):
        try:
            session = sessions.start_check(cfg, module_id, lec, settings)
        except ai.AIError as exc:
            st.error(str(exc))
            return
    session_ui.open_session(module_id, session["id"])
    st.session_state["nav"] = PAGES["cards"]
    st.rerun()


def check_panel(cfg: dict, module_id: str, lec: dict, key: str) -> None:
    """Start / Weitermachen / Ergebnis eines Vorlesungs-Checks (Vorlesungsseite und Check-Übersicht)."""
    data = load_module(module_id)
    if not topics.minitopics(data, lec["id"]):
        st.caption("Erst nacharbeiten – dann ist der Check frei.")
        return
    run = sessions.running(data, "check", lec["id"])
    if run:
        i = sessions.current_index(run)
        c1, c2 = st.columns(2)
        if c1.button(f"Weitermachen (Frage {i + 1} von {len(run['items'])})", key=f"{key}_resume", type="primary",
                     icon=":material/play_arrow:", width="stretch"):
            session_ui.open_session(module_id, run["id"])
            st.session_state["nav"] = PAGES["cards"]
            st.rerun()
        c2.button("Verwerfen", key=f"{key}_discard", width="stretch", on_click=sessions.discard,
                  args=(module_id, run["id"]))
        return
    done = sessions.finished(data, "check", lec["id"])
    with st.container(border=True, key=f"checkstart_{key}"):
        settings = settings_inputs(key)
        slots = sessions.plan_check(data, lec["id"], settings)
        new = sessions.new_questions_needed(data, slots, settings)
        from utils import question_bank as qb

        cost = qb.cost_estimate(new) * 100
        label = ("Check wiederholen" if done else "Check starten") + f" · {len(slots)} Fragen" + \
            (f" (ca. {cost:.0f} Cent)" if cost else "")
        if st.button(label, key=f"{key}_go", type="secondary" if done else "primary", icon=":material/play_arrow:",
                     width="stretch", disabled=not ai.is_available() and new > 0):
            start_check(cfg, module_id, lec, settings)
    for s in done[-3:]:
        res = sessions.summary(s)
        st.caption(f"{s['label']} · {s['finished_at'][:10]} · {res['right']} richtig, {res['partial']} teilweise, "
                   f"{res['wrong']} falsch")


def check_tab(cfg: dict, module_id: str, lec: dict) -> None:
    data = load_module(module_id)
    module = get_module(cfg, module_id)
    st.markdown(f"#### :material/fact_check: {sessions.check_label(module, lec)}")
    if sessions.is_legacy(data, lec["id"]):
        st.caption("Diese Vorlesung lag vor dem neuen System – sie wird im Wochentraining abgefragt.")
    check_panel(cfg, module_id, lec, key=f"ck_{lec['id']}")
    mts = topics.minitopics(data, lec["id"])
    if mts:
        asked, total = mastery.coverage(data, mts)
        st.progress(asked / total if total else 0.0, text=f"Abdeckung: {asked} von {total} Minithemen abgefragt")
        progress.render_status(data, {lec["id"]})
        topic_tree(module_id, data, lec, editable=False)

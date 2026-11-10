"""Neues Lernsystem auf der Vorlesungsseite: Reiter „Upload“, „Nacharbeit“ und „Checks“.

Upload: 1 Umfang & Hinweise (Von/Bis Folie, was genau gelesen wird, Wichtig, Streichen, Sonstiger Hinweis) ·
2 Genau lesen (in kleinen Paketen) · 3 Themen & Minithemen (= Upload abgeschlossen).
Nacharbeit: Tutor-Prompt zum Kopieren, Zusammenfassung aus dem Chat einfügen → Einstufung je Minithema.
Checks: Check 1 (erste Hälfte der Minithemen) und Check 2 (zweite Hälfte, nach dem Übungsblatt).
"""

from __future__ import annotations

import streamlit as st

from utils import ai, mastery, move, planner, sessions, topics
from utils.config import get_module, load_config
from utils.storage import load_module, load_todos, now_iso, save_module, save_todos
from utils.units import lecture_notes
from views import progress, session_ui
from views.common import LECTURE_TAB, PAGES



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

def _auto_skipped(module_id: str, data: dict, lec: dict) -> None:
    """Automatisch ausgelassene Folien (Titel/Orga, schon in früheren Vorlesungen) – einzeln wieder aufnehmbar."""
    notes = lecture_notes(data, lec["id"])
    rows = []
    for doc in topics.slide_docs(data, lec):
        n = topics.n_pages(doc)
        first, last = topics.doc_range(notes, doc, n)
        rows += [(doc, p, reason) for p, reason in sorted(topics.excluded(doc).items())
                 if first <= p <= last and reason != topics.REASON_USER]
    if not rows:
        return
    with st.expander(f"Automatisch ausgelassen: {len(rows)} Folie(n)", icon=":material/filter_alt:"):
        for doc, p, reason in rows:
            c1, c2 = st.columns([4, 1], vertical_alignment="center")
            c1.caption(f"Folie {p} · {reason}")
            c2.button("Doch lesen", key=f"incl_{doc['id']}_{p}", width="stretch", on_click=topics.toggle_slide,
                      args=(module_id, doc["id"], p))


def _carry_box(module_id: str, data: dict, lec: dict, lecs: list[dict]) -> None:
    offer = topics.offered_carry(data, lec, lecs)
    if not offer:
        return
    with st.container(border=True, key=f"carry_{lec['id'].replace(':', '_')}"):
        for c in offer:
            st.markdown(f":material/redo: **Weiter mit {c['filename']} ab Folie {c['pages'][0]}** "
                        f"(Vorlesung {c['from_nr']} kam bis Folie {c['pages'][0] - 1})")
        b1, b2 = st.columns(2)
        b1.button("Für diese Vorlesung übernehmen", key=f"carry_ok_{lec['id']}", type="primary", width="stretch",
                  on_click=topics.accept_carry, args=(module_id, lec["id"], offer, True))
        b2.button("Nicht übernehmen", key=f"carry_no_{lec['id']}", width="stretch",
                  on_click=topics.accept_carry, args=(module_id, lec["id"], offer, False))


# ---------------------------------------------------------------------------
# 3 · Hinweise zur Quiz-Erstellung
# ---------------------------------------------------------------------------

def _hints_form(module_id: str, data: dict, lec: dict) -> None:
    notes = lecture_notes(data, lec["id"])
    docs = topics.slide_docs(data, lec)
    with st.form(f"qhints_{module_id}_{lec['id']}"):
        ranges, reads = {}, {}
        if docs:
            st.markdown("**Umfang** – von welcher bis zu welcher Folie?")
        for doc in docs:
            n = topics.n_pages(doc)
            first, last = topics.doc_range(notes, doc, n)
            c0, c1, c2 = st.columns([3, 1, 1], vertical_alignment="bottom")
            c0.caption(doc["filename"])
            ranges[doc["id"]] = (c1.number_input("Von Folie", 1, max(1, n), min(first, max(1, n)), step=1,
                                                 key=f"rng_from_{lec['id']}_{doc['id']}"),
                                 c2.number_input("Bis Folie", 1, max(1, n), min(last, max(1, n)), step=1,
                                                 key=f"rng_to_{lec['id']}_{doc['id']}"))
            rs = topics.read_settings(notes, doc)
            r1, r2 = st.columns([2, 3], vertical_alignment="bottom")
            modes = list(topics.READ_MODES)
            reads[doc["id"]] = (r1.selectbox("Genau lesen", modes, index=modes.index(rs["mode"]),
                                             format_func=topics.READ_MODES.get, key=f"rdm_{lec['id']}_{doc['id']}"),
                                r2.text_input("Nicht genau lesen (Folien)", topics.format_pages(rs["text_only"]),
                                              placeholder="z. B. 1-40, 120-130",
                                              key=f"rdx_{lec['id']}_{doc['id']}"))
        with st.container(border=True, key=f"hintbox_{lec['id'].replace(':', '_')}"):
            hint = st.text_area(":material/edit_note: **Sonstiger Hinweis**", notes["card_hint"], height=90,
                                placeholder="z. B. Herleitung auf Folie 12 nicht relevant; Beispiel X lernen")
        c3, c4 = st.columns(2)
        important = c3.text_area("Wichtig", notes["emphasized"], height=110)
        skip = c4.text_area("Streichen", notes["skip"], height=110)
        text = st.text_area("Eigene Notizen", notes["text"], height=110)
        if st.form_submit_button("Speichern", type="primary", width="stretch"):
            scopes = notes.setdefault("scopes", {})
            for doc_id, (first, last) in ranges.items():
                mode, skip_text = reads[doc_id]
                doc = next(d for d in docs if d["id"] == doc_id)
                scopes[doc_id] = {**scopes.get(doc_id, {}), "from": int(first), "to": int(max(first, last)),
                                  "read": mode, "text_only": topics.parse_pages(skip_text, topics.n_pages(doc))}
            notes.update({"scope": {"mode": "all"}, "card_hint": hint, "emphasized": important, "skip": skip,
                          "text": text, "updated_at": now_iso()})
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


def _read(cfg: dict, module_id: str, lec: dict) -> bool:
    """Ausgewählte Folien genau lesen (Fortschrittsbalken; jedes Paket wird sofort gespeichert)."""
    unread = sum(len(p) for p in topics.unread_pages(load_module(module_id), lec).values())
    if not unread:
        return True
    bar = st.progress(0.0, text=f"Lese {unread} Folien genau …")
    try:
        topics.read_all(cfg, module_id, lec,
                        progress=lambda done, total: bar.progress(done / total, text=f"Genau gelesen: {done} von "
                                                                                    f"{total} Folien"))
    except ai.AIError as exc:
        _msg(module_id, "error", f"{exc} – bereits gelesene Folien sind gespeichert, „Weiter lesen“ macht dort "
                                 "weiter.")
        return False
    return True


def _create(cfg: dict, module_id: str, lec: dict, lecs: list[dict]) -> None:
    """Upload abschließen: ausgewählte Folien genau lesen, dann Themen und Minithemen erstellen."""
    if not _read(cfg, module_id, lec):
        return
    bar = st.progress(0.0, text="Claude zerlegt die Vorlesung in Themen und Minithemen …")
    try:
        n = topics.create_topics(cfg, module_id, lec, lecs, progress=lambda done, total: bar.progress(
            done / total, text=f"Minithemen: Abschnitt {done} von {total}"))
    except ai.AIError as exc:
        _msg(module_id, "error", str(exc))
        return
    set_done(module_id, lec, "nachbereitet")
    from utils import nacharbeit

    if nacharbeit.needs_mapping(load_module(module_id), lec["id"]):
        try:
            nacharbeit.map_summary(cfg, module_id, lec["id"])
        except ai.AIError:
            pass
    _msg(module_id, "success", f"{n} Minithemen angelegt – Upload erledigt.")


def _read_status(module_id: str, data: dict, lec: dict) -> None:
    """Wie viele Folien genau gelesen werden (Auswahl im Formular) und wie viele davon schon gelesen sind."""
    docs = topics.slide_docs(data, lec)
    if not docs:
        return
    want = sum(len(topics.exact_candidates(data, lec, d)) for d in docs)
    open_ = sum(len(p) for p in topics.unread_pages(data, lec).values())
    st.caption(f"Genau lesen: {want - open_} von {want} Folien erledigt")
    if open_ and want - open_:
        if st.button(f"Weiter lesen ({open_} Folien)", key=f"readon_{lec['id']}", icon=":material/visibility:",
                     disabled=not ai.is_available()):
            _read(load_config(), module_id, lec)
            st.rerun()


def render(cfg: dict, module_id: str, lec: dict, lecs: list[dict]) -> None:
    data = load_module(module_id)
    if msg := st.session_state.pop(f"nmsg_{module_id}", None):
        getattr(st, msg[0])(msg[1])
    docs = topics.slide_docs(data, lec)
    topics.ensure_suggestions(module_id, data, lec, lecs)
    has_topics = bool(topics.lecture_topics(data, lec["id"]))

    st.markdown("#### 1 · Umfang & Hinweise")
    _carry_box(module_id, data, lec, lecs)
    if not docs:
        st.caption("Noch keine Folien hochgeladen (Reiter Dateien).")
    _hints_form(module_id, data, lec)
    _auto_skipped(module_id, data, lec)
    _read_status(module_id, data, lec)

    st.markdown("#### 2 · Themen & Minithemen")
    if has_topics:
        topic_tree(module_id, data, lec)
        c1, c2 = st.columns(2)
        c1.button("Weiter zur Nacharbeit", key=f"tonach_{lec['id']}", type="primary", icon=":material/forum:",
                  width="stretch", on_click=_goto_tab, args=(lec["id"], "nacharbeit"))
        with c2.popover("Minithemen neu erstellen", icon=":material/refresh:", width="stretch"):
            st.caption("Gleichnamige Minithemen behalten ihren Wissensstand.")
            if st.button("Neu erstellen",
                         key=f"retopics_{lec['id']}", disabled=not ai.is_available()):
                _create(cfg, module_id, lec, lecs)
                st.rerun()
    else:
        if st.button("Upload abschließen – Minithemen erstellen",
                     key=f"mktopics_{lec['id']}", type="primary", icon=":material/account_tree:", width="stretch",
                     disabled=not ai.is_available()):
            _create(cfg, module_id, lec, lecs)
            st.rerun()

    st.markdown("**Tafelbilder & Screenshots**")
    from views.module_tabs.lecture_page import _board_images

    _board_images(get_module(cfg, module_id), module_id, lec, lecture_notes(data, lec["id"]))
    if move.movable(data, lec):
        _move_box(cfg, module_id, data, lec)


def _move_box(cfg: dict, module_id: str, data: dict, lec: dict) -> None:
    """Falsch hochgeladene Vorlesung (Dateien + Minithemen) in ein anderes Modul / eine andere VL verschieben."""
    from utils.units import lectures

    with st.popover("In andere Vorlesung verschieben", icon=":material/drive_file_move:"):
        mods = cfg["modules"]
        names = {m["id"]: m["name"] for m in mods}
        target = st.selectbox("Modul", list(names), format_func=names.get, key=f"mvmod_{lec['id']}",
                              index=list(names).index(module_id))
        tlecs = [x for x in lectures(cfg, get_module(cfg, target)) if not x["is_break"]
                 and (target, x["id"]) != (module_id, lec["id"])]
        if not tlecs:
            return
        default = next((i for i, x in enumerate(tlecs) if x["nr"] == lec["nr"]), 0)
        dst = st.selectbox("Vorlesung", tlecs, index=default, key=f"mvlec_{lec['id']}_{target}",
                           format_func=lambda x: f"Vorlesung {x['nr']} · {x['date']:%d.%m.} · {x['topic']}")
        docs = [d for d in data["documents"] if d.get("unit") == lec["id"]]
        chosen = st.multiselect("Dateien", [d["id"] for d in docs], default=[d["id"] for d in docs],
                                format_func=lambda i: next(d["filename"] for d in docs if d["id"] == i),
                                key=f"mvdocs_{lec['id']}")
        st.button("Verschieben", key=f"mvgo_{lec['id']}", type="primary", icon=":material/drive_file_move:",
                  on_click=_do_move, args=(module_id, lec, target, dst, chosen))


def _do_move(module_id: str, lec: dict, target: str, dst: dict, chosen: list[str]) -> None:
    from views.common import open_unit

    res = move.move_lecture(module_id, lec, target, dst, chosen)
    _msg(target, "success", f"Verschoben: {res['docs']} Dateien, {res['minitopics']} Minithemen.")
    open_unit(target, dst["id"])


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


def start_check(cfg: dict, module_id: str, lec: dict, settings: dict, part: int = 1) -> None:
    with st.spinner(f"Stelle deinen Check {part} zusammen …"):
        try:
            session = sessions.start_check(cfg, module_id, lec, settings, part)
        except ai.AIError as exc:
            st.error(str(exc))
            return
    session_ui.open_session(module_id, session["id"])
    st.session_state["nav"] = PAGES["cards"]
    st.rerun()


def check_panel(cfg: dict, module_id: str, lec: dict, key: str, part: int = 1) -> None:
    """Start / Weitermachen / Ergebnis von Check 1 bzw. 2 (Vorlesungsseite und Check-Übersicht)."""
    data = load_module(module_id)
    if not topics.minitopics(data, lec["id"]):
        st.caption("Erst den Upload abschließen – dann sind die Checks frei.")
        return
    run = sessions.running_check(data, lec["id"], part)
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
    done = [s for s in sessions.finished(data, "check", lec["id"]) if (s.get("part") or 1) == part]
    with st.container(border=True, key=f"checkstart_{key}"):
        settings = settings_inputs(key)
        slots = sessions.plan_check(data, lec["id"], settings, part)
        new = sessions.new_questions_needed(data, slots, settings)
        label = (f"Check {part} wiederholen" if done else f"Check {part} starten") + f" · {len(slots)} Fragen"
        if st.button(label, key=f"{key}_go", type="secondary" if done else "primary", icon=":material/play_arrow:",
                     width="stretch", disabled=not slots or (not ai.is_available() and new > 0)):
            start_check(cfg, module_id, lec, settings, part)
    for s in done[-3:]:
        res = sessions.summary(s)
        st.caption(f"{s['label']} · {s['finished_at'][:10]} · {res['right']} richtig, {res['partial']} teilweise, "
                   f"{res['wrong']} falsch")


def _part_header(data: dict, lec: dict, part: int, mts: list[dict]) -> None:
    asked, total = mastery.coverage(data, mts)
    done = sessions.check_done(data, lec["id"], part)
    icon = ":material/check_circle:" if done else ":material/fact_check:"
    st.markdown(f"#### {icon} Check {part} · {'erste' if part == 1 else 'zweite'} Hälfte · {total} Minithemen")
    if total:
        st.progress(asked / total, text=f"{asked} von {total} abgefragt")


def check_tab(cfg: dict, module_id: str, lec: dict) -> None:
    data = load_module(module_id)
    if sessions.is_legacy(data, lec["id"]):
        st.caption("Diese Vorlesung lag vor dem neuen System – sie wird im Wochentraining abgefragt.")
    if sessions.single_check(data, lec["id"]):
        st.markdown("#### :material/check_circle: Check (ganze Vorlesung)")
        check_panel(cfg, module_id, lec, key=f"ck_{lec['id']}", part=1)
    else:
        first, second = sessions.halves(data, lec["id"])
        for part, mts in ((1, first), (2, second)):
            if part == 2 and not mts and first:
                continue
            with st.container(border=True, key=f"ckpart_{part}_{lec['id'].replace(':', '_')}"):
                _part_header(data, lec, part, mts)
                if mts:
                    st.markdown(progress.chips_html(data, mts), unsafe_allow_html=True)
                check_panel(cfg, module_id, lec, key=f"ck{part}_{lec['id']}", part=part)
    mts = topics.minitopics(data, lec["id"])
    if mts:
        progress.render_status(data, {lec["id"]})
        topic_tree(module_id, data, lec, editable=False)


# ---------------------------------------------------------------------------
# Reiter „Nacharbeit“ (externer Tutor-Chat)
# ---------------------------------------------------------------------------

def _save_summary(cfg: dict, module_id: str, lec: dict, text: str) -> None:
    from utils import nacharbeit

    nacharbeit.save(module_id, lec["id"], text)
    if text.strip():
        set_done(module_id, lec, "nacharbeit")
    if text.strip() and ai.is_available() and topics.minitopics(load_module(module_id), lec["id"]):
        with st.spinner("Ordne die Zusammenfassung den Minithemen zu …"):
            try:
                n = nacharbeit.map_summary(cfg, module_id, lec["id"])
            except ai.AIError as exc:
                _msg(module_id, "error", str(exc))
                return
        _msg(module_id, "success", f"Gespeichert – {n} Zuordnungen zu Minithemen.")


def nacharbeit_tab(cfg: dict, module_id: str, lec: dict) -> None:
    from utils import nacharbeit
    from views.common import done_button

    data = load_module(module_id)
    if msg := st.session_state.pop(f"nmsg_{module_id}", None):
        getattr(st, msg[0])(msg[1])
    item = nacharbeit.entry(data, lec["id"])
    done = bool(load_todos().get(planner.lecture_key(module_id, lec["date"], "nacharbeit")))
    c1, c2 = st.columns(2, vertical_alignment="center")
    with c1.popover("Prompt für den Tutor-Chat", icon=":material/content_copy:", width="stretch"):
        st.code(nacharbeit.TUTOR_PROMPT, language=None, wrap_lines=True)
    wkey = f"nach_done_{module_id}_{lec['id']}"
    done_button(c2, "Nacharbeit erledigt", done, None, wkey, callback=set_done,
                args=(module_id, lec, "nacharbeit", not done))
    with st.form(f"nachform_{module_id}_{lec['id']}"):
        text = st.text_area("Zusammenfassung aus dem Chat", item.get("text", ""), height=260,
                            placeholder="SICHER:\n- [Folie 3–5] …\n\nWACKELIG:\n- …")
        if st.form_submit_button("Speichern & auswerten", type="primary", icon=":material/save:", width="stretch"):
            _save_summary(cfg, module_id, lec, text)
            st.rerun()
    if nacharbeit.has_summary(data, lec["id"]) and not topics.minitopics(data, lec["id"]):
        st.caption("Wird den Minithemen zugeordnet, sobald der Upload abgeschlossen ist.")
    groups = nacharbeit.rated(data, lec["id"])
    if any(groups[r] for r in mastery.NACH_RATINGS):
        for rating, label in mastery.NACH_RATINGS.items():
            if not groups[rating]:
                continue
            color = mastery.NACH_COLORS[rating]
            st.markdown(f"**{label}** <span class='small-muted'>{len(groups[rating])}</span>",
                        unsafe_allow_html=True)
            for mt in groups[rating]:
                nach = mastery.peek(data, mt["id"]).get("nacharbeit") or {}
                extra = f" – {nach['text']}" if nach.get("text") and rating != "sicher" else ""
                st.markdown(f"<span class='mt-dot' style='background:{color}'></span>{mt['title']}"
                            f"<span class='small-muted'>{extra}</span>", unsafe_allow_html=True)
    if done or nacharbeit.has_summary(data, lec["id"]):
        st.button("Weiter zu Check 1", key=f"tock1_{lec['id']}", type="primary", icon=":material/fact_check:",
                  width="stretch", on_click=_goto_tab, args=(lec["id"], "check"))

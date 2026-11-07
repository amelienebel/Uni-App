"""Gemeinsame Ansicht für Vorlesungs-Check und Wochentraining: eine Frage nach der anderen (Fokus-Modus).

Bei jeder Frage: Tipp in drei Stufen, „Passende Folien anzeigen“, nach dem Antworten die Begründung (bei
Auswahlfragen für jede Option), Freitext-Bewertung durch Claude, Selbstbewertung schwer/mittel/einfach.
"""

from __future__ import annotations

import streamlit as st

from utils import ai, mastery, question_bank as qb, sessions, topics
from utils.config import get_module
from utils.storage import load_module, read_data_file
from views.common import micon
from views.module_tabs import exams

STATE = "v2_session"
GRADE_STYLE = {"schwer": "Schwer", "mittel": "Mittel", "einfach": "Einfach"}


def active() -> dict | None:
    """Laufende Session im Fokus-Modus (oder None)."""
    ref = st.session_state.get(STATE)
    if not ref:
        return None
    data = load_module(ref["mid"])
    session = sessions.find_session(data, ref["sid"])
    if session is None:
        st.session_state.pop(STATE, None)
    return session


def open_session(module_id: str, session_id: str) -> None:
    st.session_state[STATE] = {"mid": module_id, "sid": session_id}


def close() -> None:
    st.session_state.pop(STATE, None)


@st.cache_data(show_spinner=False, max_entries=60)
def _slide_png(path: str, page: int) -> bytes | None:
    from utils.pdf_parser import render_page

    return render_page(read_data_file(path), page)


def slides(data: dict, refs: list[dict], key: str, limit: int = 4) -> None:
    """Folienbilder zu einem Minithema (wie früher bei den Karteikarten)."""
    shown = 0
    for ref in refs:
        doc = next((d for d in data["documents"] if d["id"] == ref.get("doc_id")), None)
        if not doc or not doc.get("path") or not doc["filename"].lower().endswith(".pdf"):
            continue
        for page in ref.get("pages", []):
            if shown >= limit:
                return
            try:
                png = _slide_png(doc["path"], page)
            except Exception:  # noqa: BLE001 – Vorschau ist nur ein Extra
                png = None
            if png:
                st.image(png, caption=f"{doc['filename']} · Folie {page}", width="stretch")
                shown += 1
    if not shown:
        st.caption("Zu dieser Frage sind keine Folien hinterlegt.")


def _answer_input(q: dict, key: str, item: dict):
    done = "answer" in item
    stored = item.get("answer")
    if q["type"] == "sc":
        idx = stored[0] if done and stored else None
        choice = st.radio("Antwort", list(range(len(q["options"]))), index=idx, key=f"{key}_sc", disabled=done,
                          format_func=lambda j: f"{chr(65 + j)})  {q['options'][j]}", label_visibility="collapsed")
        return [] if choice is None else [choice]
    if q["type"] == "mc":
        st.caption("Eine oder mehrere Antworten sind richtig.")
        return [j for j, opt in enumerate(q["options"])
                if st.checkbox(f"{chr(65 + j)})  {opt}", key=f"{key}_mc_{j}", disabled=done,
                               value=bool(done and j in (stored or [])))]
    if q["type"] == "zahl":
        return st.text_input("Ergebnis", value=stored or "" if done else None, key=f"{key}_num", disabled=done,
                             placeholder="Zahl eintippen, z. B. 120 oder 0,25")
    return st.text_area("Deine Antwort", value=stored or "" if done else None, key=f"{key}_txt", disabled=done,
                        height=160, placeholder="In eigenen Worten …")


def _result(q: dict, item: dict) -> None:
    correct = item.get("correct")
    if correct is True:
        st.success("Richtig", icon=":material/check_circle:")
    elif correct == "partial":
        st.warning("Teilweise richtig", icon=":material/rule:")
    else:
        st.error("Leider falsch", icon=":material/cancel:")
    if q["type"] in ("sc", "mc"):
        from views.quiz_center import option_breakdown

        option_breakdown(q, item.get("answer") or [], key=item["question_id"])
    elif q["type"] == "zahl":
        st.markdown(f"Richtiges Ergebnis: **{q['number_answer']}**"
                    + (f" · deine Eingabe: {item.get('answer')}" if item.get("answer") else ""))
    else:
        if item.get("grading"):
            exams.show_grading(item["grading"])
        with st.expander("Musterlösung", icon=":material/task_alt:"):
            st.markdown(q.get("sample_answer") or "–")
    if q.get("explanation"):
        with st.container(border=True, key=f"explain_{item['question_id']}"):
            st.markdown(":material/lightbulb: **Warum?**")
            from views.quiz_center import paragraphs

            st.markdown(paragraphs(q["explanation"]))


def _hints(module_id: str, session: dict, idx: int, q: dict, key: str, answered: bool) -> None:
    item = session["items"][idx]
    hints = q.get("hints") or []
    used = item.get("hints_used", 0)
    for i, hint in enumerate(hints[:used], start=1):
        st.info(f"**Tipp {i}:** {hint}", icon=":material/tips_and_updates:")
    if not answered and used < len(hints):
        st.button(f"Tipp {used + 1} von {len(hints)}", key=f"{key}_hint", icon=":material/tips_and_updates:",
                  on_click=sessions.use_hint, args=(module_id, session, idx), width="stretch")


def _self_grade(cfg: dict, module_id: str, session: dict, idx: int, key: str) -> None:
    st.markdown("**Wie schwer war das für dich?**")
    cols = st.columns(3)
    for col, grade in zip(cols, mastery.SELF_GRADES):
        if col.button(GRADE_STYLE[grade], key=f"sg_{grade}_{key}", width="stretch"):
            sessions.rate(cfg, module_id, session, idx, grade)
            st.rerun()


def _summary(cfg: dict, module_id: str, session: dict) -> None:
    data = load_module(module_id)
    res = sessions.summary(session)
    st.markdown(f"## :material/celebration: {session['label']} geschafft")
    c1, c2, c3 = st.columns(3)
    c1.metric("Richtig", res["right"])
    c2.metric("Teilweise", res["partial"])
    c3.metric("Falsch", res["wrong"])
    better = [it for it in session["items"] if it.get("status_before") and it.get("status_after")
              and mastery.STATUS_ORDER.index(it["status_after"]) > mastery.STATUS_ORDER.index(it["status_before"])]
    if better:
        st.markdown("**Sicherer geworden:**")
        for it in better:
            mt = topics.find_minitopic(data, it["minitopic_id"])
            if mt:
                st.markdown(f"- {mt['topic']} · {mt['title']} → {it['status_after']}")
    if session["kind"] == "check" and session.get("lecture_id"):
        mts = topics.minitopics(data, session["lecture_id"])
        asked, total = mastery.coverage(data, mts)
        st.progress(asked / total if total else 0.0, text=f"Abdeckung der Vorlesung: {asked} von {total} Minithemen")
        rest = [m for m in mts if not mastery.covered(data, m)]
        if rest:
            st.caption("Kommen im nächsten Wochentraining dran: " + ", ".join(m["title"] for m in rest))
    st.button("Fertig", key="v2_done", type="primary", icon=":material/check:", on_click=close, width="stretch")


def render(cfg: dict) -> None:
    session = active()
    if session is None:
        return
    module_id = st.session_state[STATE]["mid"]
    module = get_module(cfg, module_id)
    data = load_module(module_id)
    n = len(session["items"])
    idx = sessions.current_index(session)
    with st.container(key=f"sesshead_{module_id}"):
        st.markdown(f"#### {micon(module)} {session['label']}")
    top = st.columns([1, 3, 1], vertical_alignment="center")
    top[0].button("Pause", key="v2_pause", icon=":material/pause:", on_click=close, help="Später weitermachen")
    top[1].progress(min(idx, n) / n, text=f"Frage {min(idx + 1, n)} von {n} · "
                                          f"ca. {sessions.remaining_minutes(data, session):.0f} Min übrig")
    if idx >= n:
        _summary(cfg, module_id, session)
        return
    item = session["items"][idx]
    q = sessions.question(data, item["question_id"])
    mt = topics.find_minitopic(data, item["minitopic_id"]) or {"title": "", "topic": ""}
    key = f"v2_{session['id']}_{idx}"
    lec = next((x for x in sessions.lectures(cfg, module_id, data) if x["id"] == item["lecture_id"]), None)
    with st.container(border=True, key=f"qcard_{module_id}"):
        st.caption(" · ".join(x for x in (f"{module['short']} VL {lec['nr']}" if lec else module["short"],
                                          f"{mt['topic']} › {mt['title']}", qb.TYPE_LABELS.get(q["type"], ""))
                              if x))
        st.markdown(f"#### {q['question']}")
        answered = "answer" in item
        answer = _answer_input(q, key, item)
        _hints(module_id, session, idx, q, key, answered)
        if not answered:
            ready = bool(answer) if q["type"] in ("sc", "mc") else bool((answer or "").strip())
            if st.button("Antwort prüfen", key=f"{key}_check", type="primary", width="stretch"):
                if not ready:
                    st.warning("Bitte erst eine Antwort geben – oder unten „Weiß ich nicht“.")
                    return
                with st.spinner("Claude bewertet deine Antwort …" if q["type"] == "freitext" else "Prüfe …"):
                    try:
                        sessions.submit(cfg, module_id, session, idx, answer)
                    except ai.AIError as exc:
                        st.error(str(exc))
                        return
                st.rerun()
    if st.toggle("Passende Folien anzeigen", key=f"{key}_slides"):
        slides(data, q.get("slides") or mt.get("slides") or [], key)
    _feedback(cfg, module_id, session, idx, key)
    if "answer" in item:
        _result(q, item)
        _self_grade(cfg, module_id, session, idx, key)
    else:
        st.button("Weiß ich nicht – auflösen", key=f"{key}_skip", type="tertiary", icon=":material/help:",
                  on_click=_give_up, args=(cfg, module_id, session, idx))


def _feedback(cfg: dict, module_id: str, session: dict, idx: int, key: str) -> None:
    """Fehler oder Anmerkung zur Frage melden – bei Fehlern prüft Claude die Frage gegen die Folien."""
    item = session["items"][idx]
    for f in item.get("feedback", []):
        if f.get("confirmed"):
            st.success(f"**Fehler bestätigt und korrigiert.** {f.get('reply', '')}", icon=":material/verified:")
        elif f.get("reply"):
            st.info(f"**Antwort auf dein Feedback:** {f['reply']}", icon=":material/forum:")
        else:
            st.caption(f"Feedback gespeichert: {f['kind']}" + (f" – {f['text']}" if f.get("text") else ""))
    with st.popover("Feedback zur Frage", icon=":material/flag:"):
        kind = st.radio("Was möchtest du melden?", sessions.FEEDBACK_KINDS, key=f"{key}_fbk")
        text = st.text_area("Kommentar", key=f"{key}_fbt", height=100,
                            placeholder="z. B. Antwort C ist auch richtig, weil …")
        if st.button("Senden", key=f"{key}_fbs", type="primary", width="stretch"):
            check = kind == sessions.FEEDBACK_KINDS[0] and ai.is_available()
            with st.spinner("Claude prüft die Frage anhand der Folien …" if check else "Speichere …"):
                try:
                    sessions.question_feedback(cfg, module_id, session, idx, kind, text)
                except ai.AIError as exc:
                    st.error(str(exc))
                    return
            st.rerun()


def _give_up(cfg: dict, module_id: str, session: dict, idx: int) -> None:
    item = session["items"][idx]
    item.update({"answer": [] if item["type"] in ("sc", "mc") else "", "correct": False, "gave_up": True})
    from utils.storage import save_module

    save_module(module_id)

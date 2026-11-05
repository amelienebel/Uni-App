"""Quiz: Fragen zu ausgewählten Vorlesungen erstellen und ablenkungsfrei Frage für Frage beantworten."""

from __future__ import annotations

import streamlit as st

from utils import ai, learning, units
from utils.config import exam_format, get_module, module_label
from utils.storage import load_module, save_module
from views.module_tabs import exams

SESSION = "qz_session"
TYPE_LABELS = {"mc": "Single Choice", "mc_multi": "Multiple Choice", "freitext": "Freitext"}

TUTOR_SYSTEM = (
    ai.BASE_SYSTEM + "\n\nDer Studierende übt gerade mit einer Quizfrage und hat eine Rückfrage dazu. Erkläre "
    "verständlich, warum die richtigen Antworten richtig und die falschen falsch sind, nutze bei Bedarf ein kleines "
    "Beispiel und weise auf typische Klausurfallen hin. Halte dich kurz (max. ~200 Wörter), sofern nicht "
    "ausdrücklich mehr gewünscht ist."
)


def session_active() -> bool:
    return bool(st.session_state.get(SESSION))


# ---------------------------------------------------------------------------
# Einzelne Frage (auch für die Vorbereitung auf der Vorlesungsseite)
# ---------------------------------------------------------------------------

def is_choice(q: dict) -> bool:
    return q.get("type") in ("mc", "mc_multi") and bool(q.get("options"))


def answer_input(q: dict, key: str, stored: dict | None = None) -> list[int] | str:
    """Antwortfeld; mit `stored` (schon ausgewertet) nur noch zur Ansicht."""
    done = stored is not None
    if is_choice(q):
        options = list(range(len(q["options"])))
        if q["type"] == "mc_multi":
            st.caption("Eine oder mehrere Antworten sind richtig.")
            return [j for j in options if st.checkbox(q["options"][j], key=f"{key}_{j}{'_done' if done else ''}",
                                                      value=j in (stored or {}).get("picked", []), disabled=done)]
        picked = (stored or {}).get("picked") or []
        choice = st.radio("Antwort", options, key=f"{key}{'_done' if done else ''}", disabled=done,
                          index=picked[0] if picked else None, format_func=lambda j: q["options"][j],
                          label_visibility="collapsed")
        return [] if choice is None else [choice]
    return st.text_area("Deine Lösung", key=f"{key}{'_done' if done else ''}", height=130, disabled=done,
                        value=(stored or {}).get("text", ""), label_visibility="collapsed",
                        placeholder="Lösung mit Rechenweg …")


def evaluate(q: dict, answer: list[int] | str) -> dict:
    if is_choice(q):
        return {"picked": answer, "correct": sorted(answer) == exams.correct_indices(q)}
    return {"text": answer, "correct": None}


HINT_PROMPT = """Gib einen Tipp zu dieser Klausuraufgabe (BWL, 1. Semester), der die Lösung NICHT verrät:
erkläre die Zeichen, Symbole und Notation der Aufgabe (was bedeutet jedes Formelzeichen, jeder Index), nötige
Fachbegriffe und den Lösungsansatz bzw. die passende Formel – ohne Ergebnis und ohne zu sagen, welche Option richtig
ist. 1–4 kurze Stichpunkte, Formeln in LaTeX mit $...$.

Aufgabe: {question}
{options}
(Nur für dich, nicht verraten – Lösung: {solution})"""


def hint_box(q: dict, key: str, on_save=None) -> None:
    """Aufklappbarer Tipp (Zeichen/Notation, Ansatz) – ohne die Lösung zu verraten."""
    if not q.get("hint") and not (on_save and ai.is_available()):
        return
    with st.expander("Tipp", icon=":material/tips_and_updates:"):
        if q.get("hint"):
            st.markdown(q["hint"])
        elif st.button("Tipp anzeigen", key=f"{key}_hint", icon=":material/tips_and_updates:"):
            options = "\n".join(f"{chr(65 + j)}) {o}" for j, o in enumerate(q.get("options", [])))
            solution = (", ".join(chr(65 + j) for j in exams.correct_indices(q)) if is_choice(q)
                        else q.get("sample_answer", ""))
            with st.spinner("Hole einen Tipp …"):
                try:
                    q["hint"] = ai.complete(HINT_PROMPT.format(question=q["question"], options=options,
                                                               solution=solution), max_tokens=2000, effort="low",
                                            task="check").strip()
                    on_save()
                except ai.AIError as exc:
                    st.error(str(exc))
                    return
            st.rerun()


def option_breakdown(q: dict, picked: list[int]) -> None:
    """Jede Option einzeln: deine Wahl, richtig/falsch und warum."""
    right = set(exams.correct_indices(q))
    notes = q.get("option_notes") or []
    lines = []
    for j, opt in enumerate(q["options"]):
        chosen, ok = j in picked, j in right
        if chosen and ok:
            mark = ":green[:material/check_circle:] **Deine Wahl – richtig**"
        elif chosen:
            mark = ":red[:material/cancel:] **Deine Wahl – falsch**"
        elif ok:
            mark = ":orange[:material/error:] **Richtig – nicht gewählt**"
        else:
            mark = ":gray[:material/remove:] nicht gewählt, falsch"
        note = notes[j].strip() if j < len(notes) and notes[j] else ""
        lines.append(f"{mark} · {chr(65 + j)}) {opt}" + (f"  \n  _{note}_" if note else ""))
    st.markdown("\n\n".join(lines))


def show_result(q: dict, result: dict) -> None:
    if is_choice(q):
        if result["correct"]:
            st.success("Richtig!", icon=":material/check_circle:")
        else:
            wrong = [j for j in result.get("picked", []) if j not in exams.correct_indices(q)]
            missed = [j for j in exams.correct_indices(q) if j not in result.get("picked", [])]
            parts = []
            if wrong:
                parts.append("falsch gewählt: " + ", ".join(chr(65 + j) for j in wrong))
            if missed:
                parts.append("fehlt: " + ", ".join(chr(65 + j) for j in missed))
            st.error("Leider nicht ganz – " + " · ".join(parts), icon=":material/cancel:")
        with st.container(border=True):
            option_breakdown(q, result.get("picked", []))
    else:
        with st.container(border=True):
            st.markdown("**Musterlösung**")
            st.markdown(q.get("sample_answer") or "–")
        if result.get("grading"):
            exams.show_grading(result["grading"])
    if q.get("explanation"):
        with st.expander("Mehr Infos – Lösungsweg", icon=":material/lightbulb:", expanded=not result.get("correct")
                         and is_choice(q)):
            st.markdown(q["explanation"] + (f"\n\n_Folie {q['slides']}_" if q.get("slides") else ""))


def grade_button(q: dict, result: dict, key: str, weak: str = "", on_save=None) -> bool:
    """Freitext: „Korrigieren lassen“ – KI sagt genau, was falsch war und warum. True = neu korrigiert."""
    if is_choice(q) or result.get("grading") or not ai.is_available() or not (result.get("text") or "").strip():
        return False
    if not st.button("Korrigieren lassen", key=f"{key}_grade", icon=":material/rate_review:"):
        return False
    with st.spinner("Korrigiere …"):
        try:
            result["grading"] = exams.grade_answer(q, result["text"], weak)
        except ai.AIError as exc:
            st.error(str(exc))
            return False
    if on_save:
        on_save()
    return True


def tutor_chat(q: dict, module_name: str, key: str) -> bool:
    """Rückfragen zur Quizfrage; gibt True zurück, wenn eine neue Antwort gespeichert werden muss."""
    with st.expander(f"Beim Tutor nachfragen ({len(q.get('chat', [])) // 2})", icon=":material/forum:"):
        for msg in q.get("chat", []):
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])
        if not ai.is_available():
            st.caption("Für den Tutor wird ein API-Key benötigt.")
            return False
        with st.form(f"qz_chat_{key}", clear_on_submit=True):
            question = st.text_input("Deine Frage", placeholder="Warum ist B falsch? Kannst du ein Beispiel geben?")
            submitted = st.form_submit_button("Fragen")
        if not (submitted and question.strip()):
            return False
        options = "\n".join(f"{chr(65 + j)}) {opt}" for j, opt in enumerate(q.get("options", [])))
        right = ", ".join(chr(65 + j) for j in exams.correct_indices(q))
        system = (TUTOR_SYSTEM + f"\n\nModul: {module_name}\n<quizfrage>\n{q['question']}\n{options}\n"
                  + (f"Richtig: {right}\n" if right else f"Musterlösung: {q.get('sample_answer', '')}\n")
                  + f"Erklärung: {q.get('explanation', '')}\n</quizfrage>")
        history = q.setdefault("chat", [])
        history.append({"role": "user", "content": question.strip()})
        with st.chat_message("user"):
            st.markdown(question)
        with st.chat_message("assistant"):
            answer = st.write_stream(ai.stream_chat(history, system=system, task="tutor"))
        history.append({"role": "assistant", "content": answer if isinstance(answer, str) else "".join(answer)})
        return True


def question_card(q: dict, key: str, store: dict, title: str = "", on_save=None, weak: str = "") -> bool:
    """Frage mit Antwortfeld, Tipp und „Auswerten“; Ergebnis landet in `store`. True = gerade ausgewertet."""
    with st.container(border=True):
        badge = TYPE_LABELS.get(q.get("type") if is_choice(q) or q.get("type") == "freitext" else "freitext")
        meta = [m for m in (title, badge, q.get("operator"), f"Folie {q['slides']}" if q.get("slides") else "") if m]
        st.caption(" · ".join(meta))
        st.markdown(f"#### {q['question']}")
        stored = store.get(key)
        answer = answer_input(q, key, stored)
        hint_box(q, key, on_save)
        if stored is None:
            if st.button("Auswerten", key=f"{key}_check", type="primary", width="stretch"):
                store[key] = evaluate(q, answer)
                return True
            return False
        if grade_button(q, stored, key, weak, on_save):
            return True
        show_result(q, stored)
    return False


# ---------------------------------------------------------------------------
# Übersicht: Quiz erstellen, frühere Quizze
# ---------------------------------------------------------------------------

def _start(module_id: str, quiz_id: str) -> None:
    st.session_state[SESSION] = {"mid": module_id, "qid": quiz_id, "i": 0, "answers": {}}


def _lectures_with_material(cfg: dict, module_id: str) -> tuple[dict, list[dict]]:
    data = load_module(module_id)
    lecs, _ = units.all_units(cfg, get_module(cfg, module_id), data)
    return data, [lec for lec in lecs if units.unit_docs(data, lec) or units.has_notes(data, lec["id"])]


def _create(cfg: dict) -> None:
    st.subheader(":material/add_circle: Neues Quiz")
    ids = [m["id"] for m in cfg["modules"]]
    module_id = st.selectbox("Modul", ids, key="qz_mod", format_func=lambda m: module_label(cfg, m))
    module = get_module(cfg, module_id)
    data, lecs = _lectures_with_material(cfg, module_id)
    st.caption(f":material/assignment: Klausurformat: **{exam_format(module)['label']}**")
    if not lecs:
        st.caption("Für dieses Modul gibt es noch keine Folien oder Notizen.")
        return
    key = f"qz_lecs_{module_id}"
    options = [lec["id"] for lec in lecs]
    st.session_state.setdefault(key, options[-1:])
    st.session_state[key] = [i for i in st.session_state[key] if i in options]
    labels = {lec["id"]: f"{units.short_label(lec)} – {lec['topic'][:50]}" for lec in lecs}
    chosen = st.multiselect("Vorlesungen", options, key=key, format_func=labels.get,
                            placeholder="Keine Vorlesung gewählt")
    c1, c2, c3 = st.columns(3)
    types = c1.selectbox("Fragetyp", exams.QUIZ_TYPES, key="qz_types")
    n = c2.slider("Anzahl", 3, 20, 10, key="qz_n")
    difficulty = c3.select_slider("Schwierigkeit", ["leicht", "mittel", "klausurnah", "schwer"], value="klausurnah",
                                  key="qz_diff")
    use_exams = st.checkbox("Stil der Altklausuren und Übungsblätter", value=True, key="qz_exams",
                            disabled=not ai.is_available())
    if not st.button("Quiz erstellen & starten", key="qz_go", type="primary", icon=":material/play_arrow:",
                     disabled=not chosen):
        return
    selected = [lec for lec in lecs if lec["id"] in chosen]
    context = "\n\n".join(learning.unit_material(data, lec, summaries_only=len(selected) > 3) for lec in selected)
    label = ", ".join(f"VL {lec['nr']}" for lec in selected)
    chapter_ids = sorted({lec["chapter_id"] for lec in selected if lec.get("chapter_id")})
    with st.spinner("Erstelle Quiz …"):
        try:
            questions = exams.build_quiz(cfg, module_id, data, n, types, difficulty, use_exams, context,
                                         f"{module['name']} – {label}", chapter_ids)
        except ai.AIError as exc:
            st.error(str(exc))
            return
    if not questions:
        st.warning("Offline konnten keine Fragen erzeugt werden – lege zuerst Formeln oder Lernkarten an.")
        return
    quiz = exams.save_quiz(module_id, data, questions, chapter_ids, "center", label)
    _start(module_id, quiz["id"])
    st.rerun()


def _history(cfg: dict) -> None:
    quizzes = [(m, q) for m in cfg["modules"] for q in load_module(m["id"])["quizzes"] if q.get("questions")]
    if not quizzes:
        return
    st.subheader(":material/history: Frühere Quizze")
    for module, quiz in sorted(quizzes, key=lambda x: x[1]["created_at"], reverse=True)[:10]:
        last = quiz.get("last_score")
        with st.container(key=f"row_{module['id']}_qz_{quiz['id']}"):
            c1, c2 = st.columns([5, 1], vertical_alignment="center")
            c1.markdown(f"**{module['short']}** · {quiz.get('label') or 'Quiz'} · {len(quiz['questions'])} Fragen  \n"
                        f"<span class='small-muted'>{quiz['created_at'][:10]}"
                        + (f" · zuletzt {last[0]}/{last[1]} richtig" if last else "") + "</span>",
                        unsafe_allow_html=True)
            c2.button("Starten", key=f"qz_again_{quiz['id']}", width="stretch", on_click=_start,
                      args=(module["id"], quiz["id"]))


# ---------------------------------------------------------------------------
# Session (Focus Mode)
# ---------------------------------------------------------------------------

def _end() -> None:
    st.session_state.pop(SESSION, None)


def _move(step: int) -> None:
    st.session_state[SESSION]["i"] += step


def _finished(sess: dict, module_id: str, quiz: dict) -> None:
    results = [sess["answers"].get(f"qz_{quiz['id']}_{i}") for i in range(len(quiz["questions"]))]
    graded = [r for r in results if r and r["correct"] is not None]
    right = sum(1 for r in graded if r["correct"])
    st.success(f"Geschafft! {right} von {len(graded)} Auswahlfragen richtig." if graded else "Geschafft!")
    wrong = [i for i, r in enumerate(results) if r and r["correct"] is False]
    if wrong:
        st.markdown("**Nochmal ansehen:** " + " · ".join(f"Frage {i + 1}" for i in wrong))
    if graded:
        quiz["last_score"] = [right, len(graded)]
        save_module(module_id)
    c1, c2 = st.columns(2)
    c1.button("Nochmal von vorn", key="qz_restart", width="stretch", on_click=_start, args=(module_id, quiz["id"]))
    c2.button("Zurück zur Übersicht", key="qz_finish", type="primary", width="stretch", on_click=_end)


def _session(cfg: dict) -> None:
    sess = st.session_state[SESSION]
    module_id = sess["mid"]
    data = load_module(module_id)
    quiz = next((q for q in data["quizzes"] if q["id"] == sess["qid"]), None)
    if quiz is None:
        _end()
        st.rerun()
    n = len(quiz["questions"])
    nav = st.columns([1, 2, 1], vertical_alignment="center")
    nav[0].button("Zurück", key="qz_back", icon=":material/arrow_back:", on_click=_move, args=(-1,),
                  disabled=sess["i"] == 0)
    nav[1].progress(min(sess["i"], n) / n, text=f"Frage {min(sess['i'] + 1, n)} von {n}")
    nav[2].button("Beenden", key="qz_end", icon=":material/close:", on_click=_end, width="stretch")
    if sess["i"] >= n:
        _finished(sess, module_id, quiz)
        return
    module = get_module(cfg, module_id)
    q = quiz["questions"][sess["i"]]
    key = f"qz_{quiz['id']}_{sess['i']}"
    st.caption(f"{module['short']} · {quiz.get('label') or 'Quiz'}")
    weak = sess.setdefault("weak", exams.weak_points(cfg, module_id, data, quiz.get("chapters")))
    if question_card(q, key, sess["answers"], on_save=lambda: save_module(module_id), weak=weak):
        st.rerun()
    if key in sess["answers"]:
        if tutor_chat(q, module["name"], key):
            save_module(module_id)
        st.button("Weiter" if sess["i"] < n - 1 else "Ergebnis ansehen", key="qz_next", type="primary",
                  icon=":material/arrow_forward:", on_click=_move, args=(1,), width="stretch")
    else:
        st.button("Überspringen", key="qz_skip", type="tertiary", on_click=_move, args=(1,))


def render(cfg: dict) -> None:
    if session_active():
        _session(cfg)
        return
    st.title(":material/quiz: Quiz")
    _create(cfg)
    st.divider()
    _history(cfg)

"""Reiter: Klausuren, Quiz & Signalwort-Analyse."""

from __future__ import annotations

import random

import pandas as pd
import streamlit as st

from utils import ai
from utils.config import exam_format, get_module
from utils.exam_analysis import OPERATORS, analyze_operators, analyze_structure
from utils.storage import (add_document, chapter_label, delete_document, documents_of, get_document_text, load_module,
                           new_id, now_iso, save_module)
from views.common import ai_hint, module_context

QUIZ_PROMPT = """Erstelle ein Übungsquiz für das Modul „{module}“ zu folgenden Kapiteln: {chapters}.
Anzahl Fragen: {n}. Fragetypen: {types}. Schwierigkeit: {difficulty}.
KLAUSURFORMAT des Moduls: {exam_format}

Anforderungen:
- Orientiere dich am Stil deutscher Universitätsklausuren (LMU, 1. Semester BWL) und verwende typische
  Operatoren („Nennen Sie“, „Erläutern Sie“, „Berechnen Sie“, „Zeigen Sie rechnerisch“ …) – Feld operator.
- Single Choice (type "mc"): genau 4 Antwortoptionen, genau eine richtig (correct_indices = [Index 0–3]),
  plausible Distraktoren (typische Denkfehler). sample_answer leer lassen.
- Multiple Choice (type "mc_multi"): genau 5 Antwortoptionen, eine oder mehrere richtig (correct_indices = alle
  richtigen Indizes 0–4; die Anzahl richtiger Antworten variiert zwischen den Fragen). Aussagen präzise formulieren,
  Distraktoren mit typischen Denkfehlern (falsches Vorzeichen, vertauschte Bedingung, Ausnahme übersehen).
  explanation begründet jede Option kurz. sample_answer leer lassen.
- Freitext (type "freitext"): Rechen- oder Erklärungsaufgabe mit konkreten Zahlen, wo sinnvoll; sample_answer
  enthält eine vollständige Detaillösung mit allen Rechenschritten. options und correct_indices leer.
- explanation: warum die Lösung richtig ist. points: realistische Punktzahl.
- Formeln in LaTeX mit $...$.
{exam_hint}
<kontext>
{context}
</kontext>"""

# Fragetypen je Klausurformat (utils.config.EXAM_FORMATS)
EXAM_TYPE_TEXT = {
    "mc_multi": "nur mc_multi (wie in der Klausur: 5 Optionen, eine oder mehrere richtig)",
    "sc4": "nur mc (wie in der Klausur: 4 Optionen, genau eine richtig)",
    "open": "nur freitext (wie in der Klausur: offene Fragen und Rechenaufgaben mit Detaillösung)",
    "mixed": "gemischt: etwa ein Drittel freitext, ein Drittel mc, ein Drittel mc_multi",
}
QUIZ_TYPES = ["Wie in der Klausur", "Gemischt", "Multiple/Single Choice", "Freitext"]


def correct_indices(q: dict) -> list[int]:
    """Richtige Optionen (ältere Quizze speichern nur correct_index)."""
    if q.get("correct_indices"):
        return sorted(q["correct_indices"])
    return [q["correct_index"]] if q.get("correct_index", -1) >= 0 else []


GRADING_PROMPT = """Bewerte die Antwort eines Studierenden wie ein Klausurkorrektor.
Aufgabe ({points} Punkte, Operator: {operator}): {question}
Musterlösung: {sample}
Antwort des Studierenden: {answer}
Vergib Punkte (score, max_score = {points}), gib kurzes, konstruktives Feedback und liste fehlende Punkte auf.
Achte darauf, ob der Operator erfüllt wurde (z. B. Rechenweg bei „Berechnen Sie“, Begründung bei „Erläutern Sie“)."""

EXAM_PROMPT = """Analysiere die folgenden Altklausuren des Moduls „{module}“ für meine Klausurvorbereitung.
- overview: Aufbau der Klausuren (Dauer, Punkte, Aufgabentypen) in Markdown.
- topics: welche Themen wie häufig vorkommen und typische Aufgabenmuster.
- operator_strategies: für jeden vorkommenden Operator, wie konkret darauf zu antworten ist, mit Beispiel
  aus den Klausuren.
- recommendations: konkrete, priorisierte Lernempfehlungen.
Die automatische Operatorenzählung ergab: {operator_counts}

<altklausuren>
{text}
</altklausuren>"""


def _offline_quiz(data: dict, chapter_ids: list[str], n: int) -> list[dict]:
    """Ohne KI: MC-Fragen aus der Formelsammlung, Freitextfragen aus Karten und Kapiteln."""
    rng = random.Random()
    formulas = [f for f in data["formulas"] if not chapter_ids or f.get("chapter_id") in chapter_ids]
    questions = []
    all_names = [f["name"] for f in data["formulas"]]
    for f in rng.sample(formulas, min(len(formulas), max(1, n // 2))):
        distractors = rng.sample([x for x in all_names if x != f["name"]], min(3, len(all_names) - 1))
        if len(distractors) < 3:
            continue
        options = distractors + [f["name"]]
        rng.shuffle(options)
        questions.append({"type": "mc", "operator": "Ordnen Sie zu", "question": f"Welche Formel ist das? $${f['latex']}$$",
                          "options": options, "correct_indices": [options.index(f["name"])],
                          "explanation": f.get("explanation", ""), "sample_answer": "", "points": 1})
    cards = [c for c in data["cards"] if not chapter_ids or c.get("chapter_id") in chapter_ids]
    for c in rng.sample(cards, min(len(cards), n - len(questions))):
        questions.append({"type": "freitext", "operator": "Erläutern Sie", "question": c["front"], "options": [],
                          "correct_indices": [], "explanation": "", "sample_answer": c["back"], "points": 4})
    for ch in data["chapters"]:
        if len(questions) >= n:
            break
        if chapter_ids and ch["id"] not in chapter_ids:
            continue
        questions.append({"type": "freitext", "operator": "Erläutern Sie",
                          "question": f"Erläutern Sie die zentralen Inhalte von „{ch['title']}“ und geben Sie ein Beispiel.",
                          "options": [], "correct_indices": [], "explanation": "",
                          "sample_answer": "Mit eigenen Notizen und Folien abgleichen.", "points": 6})
    return questions[:n]


def quiz_section(cfg: dict, module_id: str, data: dict, scope_key: str = "main", scope_label: str | None = None,
                 context: str | None = None, chapter_ids: list[str] | None = None) -> None:
    """Quiz zum ganzen Modul, zu ausgewählten Vorlesungen (scope_label + context) oder zu einer Vorlesung."""
    module = get_module(cfg, module_id)
    fmt = exam_format(module)
    has_ai = ai_hint("Der Quiz-Generator")
    st.caption(f":material/assignment: Klausurformat: **{fmt['label']}**")
    with st.form(f"quiz_cfg_{module_id}_{scope_key}"):
        if chapter_ids is None:
            chapter_ids = st.multiselect("Kapitel", [ch["id"] for ch in data["chapters"]],
                                         format_func=lambda cid: chapter_label(data, cid))
        c1, c2, c3 = st.columns(3)
        types = c1.selectbox("Fragetyp", QUIZ_TYPES)
        n = c2.slider("Anzahl", 3, 20, 6)
        difficulty = c3.select_slider("Schwierigkeit", ["leicht", "mittel", "klausurnah", "schwer"], value="klausurnah")
        use_exams = st.checkbox("Stil der hochgeladenen Altklausuren berücksichtigen", value=True, disabled=not has_ai)
        submitted = st.form_submit_button("Quiz erstellen", type="primary")
    if submitted:
        with st.spinner("Erstelle Quiz …"):
            try:
                if has_ai:
                    if context is None:
                        context, _ = module_context(module_id)
                    exam_hint = ""
                    exams = documents_of(data, ("altklausur",))
                    if use_exams and exams:
                        exam_hint = ("\nOrientiere dich an Aufbau und Stil dieser Altklausuren:\n<altklausuren>\n"
                                     + "\n\n".join(get_document_text(d) for d in exams) + "\n</altklausuren>\n")
                    titles = scope_label or ", ".join(chapter_label(data, c) for c in chapter_ids) or "alle Kapitel"
                    choice_type = {"mc_multi": "nur mc_multi", "sc4": "nur mc"}.get(fmt["type"],
                                                                                     "mc und mc_multi gemischt")
                    type_text = {QUIZ_TYPES[0]: EXAM_TYPE_TEXT[fmt["type"]],
                                 QUIZ_TYPES[1]: "gemischt (ca. halb Auswahlfragen, halb freitext)",
                                 QUIZ_TYPES[2]: choice_type, QUIZ_TYPES[3]: "nur freitext"}[types]
                    result = ai.complete_json(QUIZ_PROMPT.format(module=module["name"], chapters=titles, n=n,
                                                                 types=type_text, difficulty=difficulty,
                                                                 exam_format=fmt["label"],
                                                                 exam_hint=exam_hint, context=context),
                                              ai.QUIZ_SCHEMA)
                    questions = result.get("questions", [])
                else:
                    questions = _offline_quiz(data, chapter_ids, n)
                    if types == QUIZ_TYPES[2]:
                        questions = [q for q in questions if q["type"] == "mc"]
                    elif types == QUIZ_TYPES[3]:
                        questions = [q for q in questions if q["type"] == "freitext"]
                if not questions:
                    st.warning("Offline konnten keine Fragen erzeugt werden – lege zuerst Formeln oder Lernkarten an.")
                else:
                    data["quizzes"].append({"id": new_id(), "created_at": now_iso(), "questions": questions,
                                            "chapters": chapter_ids, "results": {}, "scope": scope_key})
                    data["quizzes"] = data["quizzes"][-30:]
                    save_module(module_id)
            except ai.AIError as exc:
                st.error(str(exc))

    quizzes = [q for q in data["quizzes"] if q.get("scope", "main") == scope_key]
    if not quizzes:
        return
    quiz = quizzes[-1]
    st.markdown(f"#### Aktuelles Quiz ({len(quiz['questions'])} Fragen, erstellt {quiz['created_at'][:16].replace('T', ' ')})")
    total, reached = 0, 0
    for i, q in enumerate(quiz["questions"]):
        qkey = f"quiz_{quiz['id']}_{i}"
        with st.container(border=True):
            st.markdown(f"**Aufgabe {i + 1}** · _{q.get('operator', '')}_ · {q.get('points', 1)} P.")
            st.markdown(q["question"])
            if q["type"] in ("mc", "mc_multi") and q.get("options"):
                right = correct_indices(q)
                if q["type"] == "mc_multi":
                    st.caption("Mehrere Antworten können richtig sein.")
                    picked = [j for j, opt in enumerate(q["options"]) if st.checkbox(opt, key=f"{qkey}_{j}")]
                else:
                    choice = st.radio("Antwort", list(range(len(q["options"]))), key=qkey, index=None,
                                      format_func=lambda j, q=q: q["options"][j], label_visibility="collapsed")
                    picked = [] if choice is None else [choice]
                if st.session_state.get(f"{qkey}_checked"):
                    total += q.get("points", 1)
                    if picked == right:
                        reached += q.get("points", 1)
                        st.success("✓ Richtig!")
                    else:
                        st.error("Richtig wäre: " + " · ".join(q["options"][j] for j in right
                                                                 if 0 <= j < len(q["options"])))
                    if q.get("explanation"):
                        st.caption(q["explanation"])
            else:
                answer = st.text_area("Deine Lösung", key=qkey, height=120, label_visibility="collapsed",
                                      placeholder="Lösung mit Rechenweg …")
                if st.session_state.get(f"{qkey}_checked"):
                    with st.expander("Musterlösung", expanded=True):
                        st.markdown(q.get("sample_answer") or "–")
                        if q.get("explanation"):
                            st.caption(q["explanation"])
                    grading = quiz["results"].get(str(i))
                    if grading:
                        total += grading["max_score"]
                        reached += grading["score"]
                        st.info(f"**{grading['score']}/{grading['max_score']} Punkte** – {grading['feedback']}")
                        for miss in grading.get("missing_points", []):
                            st.markdown(f"- {miss}")
                    elif ai.is_available() and answer.strip():
                        if st.button("Korrigieren lassen", key=f"{qkey}_grade"):
                            with st.spinner("Korrigiere …"):
                                try:
                                    quiz["results"][str(i)] = ai.complete_json(GRADING_PROMPT.format(
                                        points=q.get("points", 5), operator=q.get("operator", ""),
                                        question=q["question"], sample=q.get("sample_answer", ""), answer=answer),
                                        ai.GRADING_SCHEMA, max_tokens=4000, effort="low")
                                    save_module(module_id)
                                    st.rerun()
                                except ai.AIError as exc:
                                    st.error(str(exc))
            if not st.session_state.get(f"{qkey}_checked"):
                if st.button("Auswerten", key=f"{qkey}_btn"):
                    st.session_state[f"{qkey}_checked"] = True
                    st.rerun()
    if total:
        st.metric("Ergebnis (ausgewertete Aufgaben)", f"{reached}/{total} Punkte", f"{reached / total * 100:.0f} %")


def _altklausuren_section(cfg: dict, module_id: str, data: dict) -> None:
    with st.form(f"exam_upload_{module_id}", clear_on_submit=True):
        files = st.file_uploader("Altklausuren (PDF)", type=["pdf"], accept_multiple_files=True)
        if st.form_submit_button("Hochladen", type="primary") and files:
            for f in files:
                add_document(module_id, f.name, f.getvalue(), "altklausur", None)
            st.success(f"{len(files)} Altklausur(en) gespeichert.")
    exams = documents_of(data, ("altklausur",))
    if not exams:
        st.caption("Noch keine Altklausuren hochgeladen.")
    for doc in exams:
        with st.expander(f"{doc['filename']} ({doc['n_pages']} Seiten)"):
            st.text(get_document_text(doc)[:6000] + ("\n…" if doc["n_chars"] > 6000 else ""))
            if st.button("Löschen", key=f"del_exam_{doc['id']}"):
                delete_document(module_id, doc["id"])
                st.rerun()


def _signal_section(cfg: dict, module_id: str, data: dict) -> None:
    module = get_module(cfg, module_id)
    exams = documents_of(data, ("altklausur", "uebung"))
    selected = st.multiselect("Altklausuren/Übungsblätter analysieren", exams,
                              default=[d for d in exams if d["doc_type"] == "altklausur"],
                              format_func=lambda d: d["filename"], key=f"sig_docs_{module_id}")
    pasted = st.text_area("…oder Aufgabentext einfügen", key=f"sig_text_{module_id}", height=100)
    text = "\n\n".join(get_document_text(d, with_page_markers=False) for d in selected) + "\n\n" + pasted
    if not text.strip():
        st.caption("Wähle Dokumente oder füge Text ein.")
        with st.expander("Operatoren-Glossar"):
            st.dataframe(pd.DataFrame([{"Operator": o["name"], "AFB": o["afb"], "So antworten": o["how"],
                                        "Beispiel": o["example"]} for o in OPERATORS]),
                         hide_index=True, width="stretch")
        return

    results = analyze_operators(text)
    structure = analyze_structure(text)
    c1, c2, c3 = st.columns(3)
    c1.metric("Erkannte Aufgaben", structure["n_tasks"])
    c2.metric("Operatoren gesamt", sum(r["Anzahl"] for r in results))
    c3.metric("Punkte (erkannt)", structure["total_points"] or "–")
    if not results:
        st.warning("Keine Operatoren gefunden.")
        return
    st.bar_chart(pd.DataFrame(results).set_index("Operator")["Anzahl"], horizontal=True)
    if structure["afb"]:
        st.caption("Verteilung nach Anforderungsbereich: " +
                   ", ".join(f"AFB {k}: {v}" for k, v in sorted(structure["afb"].items())))
    for r in results:
        with st.expander(f"**{r['Operator']}** – {r['Anzahl']}× · AFB {r['AFB']}"):
            st.markdown(f"**So musst du antworten:** {r['So antworten']}")
            st.markdown(f"**Beispiel:** {r['Beispiel']}")
            st.markdown("**Fundstellen:**")
            for s in r["snippets"]:
                st.caption(s)

    st.markdown("#### Tiefenanalyse")
    if not ai_hint("Die Tiefenanalyse"):
        return
    if st.button("Altklausuren mit KI analysieren", key=f"sig_ai_{module_id}", type="primary"):
        with st.spinner("Analysiere Altklausuren …"):
            try:
                counts = ", ".join(f"{r['Operator']}: {r['Anzahl']}" for r in results)
                result = ai.complete_json(EXAM_PROMPT.format(module=module["name"], operator_counts=counts, text=text),
                                          ai.EXAM_ANALYSIS_SCHEMA)
                result.update({"created_at": now_iso(), "documents": [d["filename"] for d in selected]})
                data["exam_analyses"].append(result)
                save_module(module_id)
            except ai.AIError as exc:
                st.error(str(exc))
    if data["exam_analyses"]:
        a = data["exam_analyses"][-1]
        st.caption(f"Analyse vom {a['created_at'][:10]} · {', '.join(a.get('documents', []))}")
        st.markdown(a["overview"])
        st.dataframe(pd.DataFrame(a["topics"]).rename(columns={"topic": "Thema", "frequency": "Häufigkeit",
                                                               "typical_tasks": "Typische Aufgaben"}),
                     hide_index=True, width="stretch")
        for op in a["operator_strategies"]:
            st.markdown(f"- **{op['operator']}**: {op['how_to_answer']}  \n  _Beispiel: {op['example']}_")
        st.markdown("**Empfehlungen:**")
        for rec in a["recommendations"]:
            st.markdown(f"1. {rec}")


def altklausuren(cfg: dict, module_id: str) -> None:
    data = load_module(module_id)
    t1, t2 = st.tabs(["Altklausuren", "Signalwort-Analyse"])
    with t1:
        _altklausuren_section(cfg, module_id, data)
    with t2:
        _signal_section(cfg, module_id, data)

"""Reiter „Klausuraufgaben“: echte Aufgaben aus den Altklausuren – nur zu den gewählten Vorlesungen."""

from __future__ import annotations

import streamlit as st

from utils import ai, exam_tasks
from utils.storage import save_module
from views import quiz_center
from views.module_tabs import exams


def _extract(cfg: dict, module_id: str, docs: list[dict]) -> None:
    for doc in docs:
        with st.spinner(f"Lese Aufgaben aus {doc['filename']} …"):
            try:
                exam_tasks.extract_tasks(cfg, module_id, doc)
            except ai.AIError as exc:
                st.error(f"{doc['filename']}: {exc}")
                return


def _grade(module_id: str, data: dict, task: dict, answer: str) -> None:
    with st.spinner("Korrigiere …"):
        try:
            task["grading"] = ai.complete_json(exams.GRADING_PROMPT.format(
                points=task.get("points", 5), operator=task.get("operator", ""), question=task["question"],
                sample=task.get("sample_answer", ""), answer=answer), ai.GRADING_SCHEMA, max_tokens=4000,
                effort="low")
            save_module(module_id)
        except ai.AIError as exc:
            st.error(str(exc))


def _reset(module_id: str, task: dict) -> None:
    task.pop("result", None)
    task.pop("grading", None)
    save_module(module_id)


def _task_card(module_id: str, module_name: str, data: dict, filename: str, doc_id: str, i: int, task: dict) -> None:
    key = f"xt_{doc_id}_{i}"
    with st.container(border=True):
        meta = [filename, f"Aufgabe {task.get('nr') or i + 1}", f"{task.get('points', 0)} P.",
                task.get("operator", ""), "VL " + ", ".join(str(n) for n in sorted(task.get("lectures", [])))]
        st.caption(" · ".join(m for m in meta if m))
        st.markdown(task["question"])
        stored = task.get("result")
        answer = quiz_center.answer_input(task, key, stored)
        if stored is None:
            if st.button("Auswerten", key=f"{key}_check", type="primary"):
                task["result"] = quiz_center.evaluate(task, answer)
                save_module(module_id)
                st.rerun()
            return
        quiz_center.show_result(task, stored)
        if not quiz_center.is_choice(task):
            grading = task.get("grading")
            if grading:
                st.info(f"**{grading['score']}/{grading['max_score']} Punkte** – {grading['feedback']}")
                for miss in grading.get("missing_points", []):
                    st.markdown(f"- {miss}")
            elif ai.is_available() and stored.get("text", "").strip():
                if st.button("Korrigieren lassen", key=f"{key}_grade"):
                    _grade(module_id, data, task, stored["text"])
                    st.rerun()
        if quiz_center.tutor_chat(task, module_name, key):
            save_module(module_id)
        st.button("Nochmal versuchen", key=f"{key}_reset", type="tertiary", icon=":material/replay:",
                  on_click=_reset, args=(module_id, task))


def render(cfg: dict, module: dict, data: dict, chosen: list[dict]) -> None:
    module_id = module["id"]
    docs = exam_tasks.exam_docs(data)
    if not docs:
        st.caption("Noch keine Altklausuren hochgeladen (Reiter Altklausuren).")
        return
    done = exam_tasks.extracted(data)
    missing = [d for d in docs if d["id"] not in done]
    if missing and ai.is_available():
        if st.button(f"Aufgaben aus {len(missing)} Altklausur(en) auslesen", key=f"xt_go_{module_id}",
                     type="primary", icon=":material/assignment:"):
            _extract(cfg, module_id, missing)
            st.rerun()
    if not chosen:
        st.info("Wähle oben mindestens eine Vorlesung aus.")
        return
    tasks = exam_tasks.tasks_for(data, {lec["nr"] for lec in chosen})
    total = sum(len(e.get("tasks", [])) for e in done.values())
    st.caption(f"{len(tasks)} von {total} Klausuraufgaben passen zu den gewählten Vorlesungen.")
    names = {d["id"]: d["filename"] for d in docs}
    for doc_id, i, task in tasks:
        _task_card(module_id, module["name"], data, names[doc_id], doc_id, i, task)
    if done and ai.is_available():
        with st.expander("Neu auslesen", icon=":material/refresh:"):
            for doc in (d for d in docs if d["id"] in done):
                if st.button(doc["filename"], key=f"xt_redo_{doc['id']}"):
                    _extract(cfg, module_id, [doc])
                    st.rerun()

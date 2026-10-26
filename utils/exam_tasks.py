"""Klausuraufgaben: Aufgaben aus den Altklausuren auslesen und den Vorlesungen zuordnen.

Gespeichert in data["exam_tasks"] = {doc_id: {"created_at", "filename", "tasks": [...]}}; jede Aufgabe hat
`lectures` (Nummern der Vorlesungen, deren Stoff sie braucht) – so zeigt der Reiter nur, was schon dran war.
"""

from __future__ import annotations

from utils import ai
from utils.config import exam_format, get_module
from utils.storage import documents_of, get_document_text, load_module, now_iso, save_module
from utils.units import all_units

_STR = {"type": "string"}
_INT = {"type": "integer"}
EXAM_TASKS_SCHEMA = ai._obj({"tasks": {"type": "array", "items": ai._obj({
    "nr": _STR,
    "question": _STR,
    "points": _INT,
    "operator": _STR,
    "type": {"type": "string", "enum": ["mc", "mc_multi", "freitext"]},
    "options": {"type": "array", "items": _STR},
    "correct_indices": {"type": "array", "items": _INT},
    "lectures": {"type": "array", "items": _INT},
    "sample_answer": _STR,
    "explanation": _STR,
})}})

EXTRACT_PROMPT = """Unten steht eine Altklausur des Moduls „{module}“ (KLAUSURFORMAT: {exam_format}).
Lies ALLE Aufgaben heraus – vollständig und wortgetreu, mit allen Angaben, Zahlen, Tabellen (als Markdown) und
Teilaufgaben a), b), c) … Eine Aufgabe mit Teilaufgaben bleibt EINE Aufgabe (nr wie in der Klausur, z. B. "2"),
außer die Teilaufgaben behandeln ganz verschiedene Themen – dann einzeln (nr "2a", "2b"). Formeln in LaTeX mit $...$.
- type: "mc" (genau eine Option richtig), "mc_multi" (eine oder mehrere richtig) oder "freitext" (offene Aufgabe,
  Rechnung, Erläuterung). Bei mc/mc_multi: options wortgetreu, correct_indices = richtige Optionen (0-basiert).
- lectures: Nummern ALLER Vorlesungen aus der Liste unten, deren Stoff man für die Aufgabe braucht. Passt keine
  Vorlesung, leere Liste.
- sample_answer: vollständige Musterlösung mit allen Rechenschritten, so wie sie in der Klausur volle Punkte bekäme
  (bei mc/mc_multi leer). Liegt der Klausur eine Lösung bei, übernimm sie.
- explanation: kurz, warum die Lösung stimmt und worauf es ankommt (typische Fehler).
- points: Punkte laut Klausur, sonst realistische Schätzung.

<vorlesungen>
{lectures}
</vorlesungen>

<altklausur name="{filename}">
{text}
</altklausur>"""

MAX_EXAM_CHARS = 60000


def exam_docs(data: dict) -> list[dict]:
    return documents_of(data, ("altklausur",))


def extracted(data: dict) -> dict:
    return data.get("exam_tasks") or {}


def extract_tasks(cfg: dict, module_id: str, doc: dict) -> int:
    """Liest die Aufgaben einer Altklausur aus (KI) und speichert sie. Wirft ai.AIError."""
    module = get_module(cfg, module_id)
    data = load_module(module_id)
    lecs, _ = all_units(cfg, module, data)
    lectures = "\n".join(f"{lec['nr']}: {lec['topic']}" for lec in lecs)
    text = get_document_text(doc, with_page_markers=False)[:MAX_EXAM_CHARS]
    result = ai.complete_json(EXTRACT_PROMPT.format(module=module["name"], exam_format=exam_format(module)["label"],
                                                    lectures=lectures, filename=doc["filename"], text=text),
                              EXAM_TASKS_SCHEMA)
    tasks = result.get("tasks", [])
    data.setdefault("exam_tasks", {})[doc["id"]] = {"created_at": now_iso(), "filename": doc["filename"],
                                                     "tasks": tasks}
    save_module(module_id)
    return len(tasks)


def tasks_for(data: dict, lecture_nrs: set[int]) -> list[tuple[str, int, dict]]:
    """(doc_id, Index, Aufgabe) aller Aufgaben, deren Stoff komplett in den gewählten Vorlesungen liegt."""
    docs = {d["id"] for d in exam_docs(data)}
    out = []
    for doc_id, entry in extracted(data).items():
        if doc_id not in docs:
            continue
        for i, task in enumerate(entry.get("tasks", [])):
            nrs = set(task.get("lectures") or [])
            if nrs and nrs <= lecture_nrs:
                out.append((doc_id, i, task))
    return out

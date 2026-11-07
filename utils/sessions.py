"""Vorlesungs-Check und Wochentraining: Fragen auswählen, Session anlegen, Antworten auswerten, Wissensstand buchen.

Vorlesungs-Check (pro Vorlesung, nach dem Nacharbeiten): genau CHECK_SIZE Fragen, höchstens ~CHECK_MINUTES Minuten,
so viele verschiedene Minithemen wie möglich; nicht abgefragte bleiben offen und haben im nächsten Wochentraining
Vorrang.
Wochentraining (pro Modul, fortlaufend nummeriert): 5/10/15 Fragen über alle bisherigen Vorlesungen.
Reihenfolge der Auswahl: offene Minithemen aus Checks → „lief schlecht“ in Übungen → fällig (Spaced Repetition) →
noch nie gefragt aus Vorlesungen vor dem neuen System (alte Karten nur als Hinweis: schwach zuerst) → Rest
(wichtig und unsicher zuerst).
"""

from __future__ import annotations

from datetime import date

from utils import ai, mastery, planner, question_bank as qb, topics, units
from utils.config import get_module
from utils.storage import (days_until_exam, get_schedule, lecture_breaks, load_module, load_todos, new_id, now_iso,
                           save_module, save_todos, today)

CHECK_SIZE = 15
CHECK_MINUTES = 30
TRAINING_SIZES = (5, 10, 15)
MAX_FREITEXT_FIRST_CHECK = 3
_IMPORTANCE_RANK = {"hoch": 0, "normal": 1, "niedrig": 2}
_HINT_RANK = {"schwach": 0, "nie gelernt": 1, None: 1, "mittel": 2, "sicher": 3}


# ---------------------------------------------------------------------------
# Grundlagen
# ---------------------------------------------------------------------------

def lectures(cfg: dict, module_id: str, data: dict | None = None) -> list[dict]:
    data = data or load_module(module_id)
    return units.all_units(cfg, get_module(cfg, module_id), data)[0]


def held_lectures(cfg: dict, module_id: str, data: dict | None = None) -> list[dict]:
    return [lec for lec in lectures(cfg, module_id, data) if lec["date"] <= today() and not lec["is_break"]]


def lec_names(lecs: list[dict]) -> dict[str, str]:
    return {lec["id"]: f"Vorlesung {lec['nr']}: {lec['topic']}" for lec in lecs}


def check_label(module: dict, lec: dict) -> str:
    return f"Vorlesung {lec['nr']} {module['short']} Check"


def is_legacy(data: dict, lec_id: str) -> bool:
    """Vorlesung war schon vor der Umstellung nachbereitet → kein Vorlesungs-Check, nur Wochentraining."""
    return lec_id in set(data.get("legacy_lectures", []))


def sessions_of(data: dict, kind: str | None = None, lec_id: str | None = None) -> list[dict]:
    return [s for s in data.get("sessions", []) if (kind is None or s["kind"] == kind)
            and (lec_id is None or s.get("lecture_id") == lec_id)]


def finished(data: dict, kind: str, lec_id: str | None = None) -> list[dict]:
    return [s for s in sessions_of(data, kind, lec_id) if s.get("finished_at")]


def running(data: dict, kind: str | None = None, lec_id: str | None = None) -> dict | None:
    return next((s for s in reversed(sessions_of(data, kind, lec_id)) if not s.get("finished_at")), None)


def check_done(data: dict, lec_id: str) -> bool:
    return bool(finished(data, "check", lec_id))


def next_training_number(data: dict) -> int:
    return len(sessions_of(data, "training")) + 1


def find_session(data: dict, session_id: str) -> dict | None:
    return next((s for s in data.get("sessions", []) if s["id"] == session_id), None)


def question(data: dict, qid: str) -> dict | None:
    return next((q for q in data.get("questions", []) if q["id"] == qid), None)


# ---------------------------------------------------------------------------
# Auswahl
# ---------------------------------------------------------------------------

def _ordered(mts: list[dict]) -> list[dict]:
    return sorted(mts, key=lambda m: _IMPORTANCE_RANK.get(m.get("importance"), 1))


def _next_level(level: str, mt: dict) -> str:
    top = mastery.LEVELS.index(mastery.top_level(mt))
    return mastery.LEVELS[min(top, mastery.LEVELS.index(level) + 1)]


def plan_check(data: dict, lec_id: str, settings: dict) -> list[dict]:
    """Genau 15 Plätze (weniger nur, wenn es kaum Stoff gibt), höchstens ~30 Minuten."""
    mts = _ordered(topics.minitopics(data, lec_id))
    if not mts:
        return []
    slots = [{"mt": m, "level": mastery.current_level(data, m)} for m in mts[:CHECK_SIZE]]
    # Schon im ersten Check ein paar Freitext-Fragen zu wichtigen Erklär-Themen
    free = 0
    for slot in slots:
        mt = slot["mt"]
        if free >= MAX_FREITEXT_FIRST_CHECK:
            break
        if mt.get("importance") == "hoch" and mastery.top_level(mt) == "freitext" and mt.get("kind") != "definition":
            slot["level"] = "freitext"
            free += 1
    # Wenig Minithemen: zweite (dritte) Frage auf der nächsten Stufe, wichtige und Anwendungen zuerst
    rounds = 0
    while len(slots) < CHECK_SIZE and rounds < CHECK_SIZE:
        rounds += 1
        extra = sorted(mts, key=lambda m: (_IMPORTANCE_RANK.get(m.get("importance"), 1),
                                           m.get("kind") != "anwendung"))
        for mt in extra:
            if len(slots) >= CHECK_SIZE:
                break
            used = [s["level"] for s in slots if s["mt"]["id"] == mt["id"]]
            if len(used) > rounds:
                continue
            level = _next_level(max(used, key=mastery.LEVELS.index), mt) if used else mastery.current_level(data, mt)
            slots.append({"mt": mt, "level": level})
    for slot in slots:
        slot["type"] = qb.question_type(slot["mt"], slot["level"], settings)
    # Zeitrahmen: Freitext zur Not auf Multiple Choice zurückstufen
    for slot in reversed(slots):
        if sum(qb.MINUTES[s["type"]] for s in slots) <= CHECK_MINUTES:
            break
        if slot["type"] == "freitext":
            slot["level"], slot["type"] = "mc", qb.question_type(slot["mt"], "mc", settings)
    return slots[:CHECK_SIZE]


def open_from_checks(data: dict) -> list[dict]:
    """Minithemen aus Vorlesungen mit abgeschlossenem Check, die noch nie abgefragt wurden (Pflicht im Training)."""
    checked = {s["lecture_id"] for s in finished(data, "check")}
    return [m for m in topics.minitopics(data) if m["lecture_id"] in checked and not mastery.covered(data, m)]


def plan_training(data: dict, held: list[dict], n: int, settings: dict, day: date | None = None) -> list[dict]:
    day = day or today()
    order = {lec["id"]: i for i, lec in enumerate(held)}
    mts = [m for m in topics.minitopics(data) if m["lecture_id"] in order]
    checked = {s["lecture_id"] for s in finished(data, "check")}
    chosen: list[dict] = []
    ids: set[str] = set()

    def take(items: list[dict]) -> None:
        for m in items:
            if len(chosen) >= n:
                return
            if m["id"] not in ids:
                ids.add(m["id"])
                chosen.append(m)

    by_lecture = lambda m: (order[m["lecture_id"]], _IMPORTANCE_RANK.get(m.get("importance"), 1))  # noqa: E731
    take(sorted([m for m in mts if m["lecture_id"] in checked and not mastery.covered(data, m)], key=by_lecture))
    take(sorted([m for m in mts if mastery.has_open_flag(data, m)], key=by_lecture))
    take(sorted(mastery.next_due(data, mts, day),
                key=lambda m: (mastery.retrievability(mastery.peek(data, m["id"]), day) or 0.0)))
    legacy_new = [m for m in mts if m["lecture_id"] not in checked and not mastery.covered(data, m)]
    take(sorted(legacy_new, key=lambda m: (_HINT_RANK.get((mastery.archive_hint(data, m["id"]) or {}).get("label")),
                                           order[m["lecture_id"]], _IMPORTANCE_RANK.get(m.get("importance"), 1))))
    take(sorted(mts, key=lambda m: (_IMPORTANCE_RANK.get(m.get("importance"), 1), mastery.score(data, m, day))))
    # nicht mehr als zwei Fragen derselben Vorlesung hintereinander
    result: list[dict] = []
    pool = list(chosen)
    while pool:
        pick = next((m for m in pool if len(result) < 2 or not (result[-1]["lecture_id"] == result[-2]["lecture_id"]
                                                                  == m["lecture_id"])), pool[0])
        pool.remove(pick)
        result.append(pick)
    slots = []
    for mt in result:
        level = mastery.current_level(data, mt)
        slots.append({"mt": mt, "level": level, "type": qb.question_type(mt, level, settings)})
    return slots


# ---------------------------------------------------------------------------
# Session anlegen
# ---------------------------------------------------------------------------

def new_questions_needed(data: dict, slots: list[dict], settings: dict) -> int:
    session_no = qb.session_counter(data) + 1
    taken: set[str] = set()
    missing = 0
    for slot in slots:
        q = qb.reusable(data, slot["mt"]["id"], slot["type"], session_no, settings, taken)
        if q:
            taken.add(q["id"])
        else:
            missing += 1
    return missing


def build(cfg: dict, module_id: str, kind: str, slots: list[dict], settings: dict, label: str,
          lecture_id: str | None = None) -> dict:
    """Legt eine Session an (Fragen aus dem Speicher oder neu erzeugt). Wirft ai.AIError."""
    data = load_module(module_id)
    lecs = lectures(cfg, module_id, data)
    names = lec_names(lecs)
    session_no = qb.session_counter(data) + 1
    picked: list[dict | None] = []
    taken: set[str] = set()
    requests = []
    for slot in slots:
        q = qb.reusable(data, slot["mt"]["id"], slot["type"], session_no, settings, taken)
        if q:
            taken.add(q["id"])
        else:
            requests.append({"slot": len(picked), "mt": slot["mt"], "type": slot["type"]})
        picked.append(q)
    for attempt in range(2):
        if not requests:
            break
        fresh = qb.generate(cfg, module_id, requests, settings, names)
        data = load_module(module_id)
        still = []
        for r, q in zip(requests, fresh):
            if q:
                picked[r["slot"]] = q
            else:
                still.append(r)
        requests = still
    items = []
    for slot, q in zip(slots, picked):
        if not q:
            continue
        stored = question(data, q["id"]) or q
        qb.mark_used(stored, session_no)
        items.append({"question_id": stored["id"], "minitopic_id": slot["mt"]["id"], "lecture_id":
                      slot["mt"]["lecture_id"], "level": slot["level"], "type": stored["type"], "hints_used": 0})
    if not items:
        raise ai.AIError("Es konnten keine Fragen erstellt werden – bitte noch einmal versuchen.")
    session = {"id": new_id(), "kind": kind, "lecture_id": lecture_id, "label": label, "no": session_no,
               "number": next_training_number(data) if kind == "training" else None,
               "settings": settings, "started_at": now_iso(), "finished_at": None, "items": items}
    data.setdefault("sessions", []).append(session)
    data["session_counter"] = session_no
    save_module(module_id)
    return session


def start_check(cfg: dict, module_id: str, lec: dict, settings: dict) -> dict:
    data = load_module(module_id)
    if not topics.minitopics(data, lec["id"]):
        raise ai.AIError("Für diese Vorlesung gibt es noch keine Minithemen – erst nacharbeiten.")
    module = get_module(cfg, module_id)
    return build(cfg, module_id, "check", plan_check(data, lec["id"], settings), settings,
                 check_label(module, lec), lec["id"])


def start_training(cfg: dict, module_id: str, n: int, settings: dict) -> dict:
    data = load_module(module_id)
    held = held_lectures(cfg, module_id, data)
    ensure_feedback_mapped(cfg, module_id)
    data = load_module(module_id)
    slots = plan_training(data, held, n, settings)
    if not slots:
        raise ai.AIError("Noch keine Minithemen für die bisherigen Vorlesungen – erst nacharbeiten oder die "
                         "Minithemen der früheren Vorlesungen anlegen.")
    module = get_module(cfg, module_id)
    return build(cfg, module_id, "training", slots, {**settings, "n": n},
                 f"Wochentraining {next_training_number(data)} {module['short']}")


def discard(module_id: str, session_id: str) -> None:
    """Angefangene Session verwerfen (bereits gebuchte Antworten bleiben im Wissensstand)."""
    data = load_module(module_id)
    data["sessions"] = [s for s in data.get("sessions", []) if s["id"] != session_id]
    save_module(module_id)


# ---------------------------------------------------------------------------
# Antworten
# ---------------------------------------------------------------------------

def current_index(session: dict) -> int:
    return next((i for i, it in enumerate(session["items"]) if not it.get("self")), len(session["items"]))


def remaining_minutes(data: dict, session: dict) -> float:
    return sum(qb.MINUTES.get(it["type"], 1.5) for it in session["items"] if not it.get("self"))


def use_hint(module_id: str, session: dict, idx: int) -> None:
    session["items"][idx]["hints_used"] = session["items"][idx].get("hints_used", 0) + 1
    save_module(module_id)


def submit(cfg: dict, module_id: str, session: dict, idx: int, answer) -> dict:
    """Antwort prüfen (Auswahl/Zahl selbst, Freitext per Haiku). Wirft ai.AIError bei Freitext."""
    data = load_module(module_id)
    item = session["items"][idx]
    q = question(data, item["question_id"])
    if q["type"] in ("sc", "mc"):
        item.update({"answer": answer, "correct": qb.check_choice(q, answer)})
    elif q["type"] == "zahl":
        item.update({"answer": answer, "correct": qb.check_number(q, answer)})
    else:
        weak = "; ".join(f["text"] for f in mastery.peek(data, item["minitopic_id"]).get("exercise_flags", [])
                         if f["kind"] == "schlecht")
        correct, grading = qb.grade_text(q, answer, weak)
        item.update({"answer": answer, "correct": correct, "grading": grading})
    item["answered_at"] = now_iso()
    save_module(module_id)
    return item


def rate(cfg: dict, module_id: str, session: dict, idx: int, self_grade: str) -> bool:
    """Selbstbewertung speichern und Wissensstand buchen. True = Session damit abgeschlossen."""
    data = load_module(module_id)
    item = session["items"][idx]
    item["self"] = self_grade
    mt = topics.find_minitopic(data, item["minitopic_id"])
    if mt and not item.get("void"):  # wegen eines bestätigten Fehlers nicht gewertet
        item["status_before"] = mastery.status(data, mt)
        mastery.record(data, mt, item.get("correct"), self_grade, source=session["kind"],
                       question_id=item["question_id"], level_asked=item["level"],
                       hints_used=item.get("hints_used", 0), days_to_exam=days_until_exam(module_id))
        item["status_after"] = mastery.status(data, mt)
    done = current_index(session) >= len(session["items"])
    if done:
        session["finished_at"] = now_iso()
        _mark_todos(cfg, module_id, session)
    save_module(module_id)
    return done


def summary(session: dict) -> dict:
    items = session["items"]
    right = sum(1 for it in items if it.get("correct") is True)
    partial = sum(1 for it in items if it.get("correct") == "partial")
    return {"total": len(items), "right": right, "partial": partial,
            "wrong": sum(1 for it in items if it.get("correct") is False),
            "self": {g: sum(1 for it in items if it.get("self") == g) for g in mastery.SELF_GRADES}}


def _mark_todos(cfg: dict, module_id: str, session: dict) -> None:
    state = load_todos()
    module = get_module(cfg, module_id)
    if session["kind"] == "check" and session.get("lecture_id"):
        lec = next((x for x in lectures(cfg, module_id) if x["id"] == session["lecture_id"]), None)
        if lec:
            state[planner.lecture_key(module_id, lec["date"], "check")] = True
    else:
        windows = planner.training_windows(cfg, module, get_schedule(cfg), lecture_breaks(cfg))
        now = today()
        for w in windows:  # ein Training erledigt alle bis heute offenen Trainings-To-dos des Moduls
            if w["start"] <= now and not state.get(w["key"]):
                state[w["key"]] = True
    save_todos()


# ---------------------------------------------------------------------------
# Übungs-Rückmeldung → Minithemen
# ---------------------------------------------------------------------------

FEEDBACK_PROMPT = """Ordne die Rückmeldung der Studentin zu einem Übungsblatt den Minithemen unten zu.
Jede Zeile der Rückmeldung (getrennt nach „gut“ und „schlecht“) bekommt die Nummern ALLER Minithemen, um die es
geht (meist 1–3). Passt keine, minitopics leer lassen.

<rueckmeldung>
LIEF GUT:
{good}

LIEF SCHLECHT:
{bad}
</rueckmeldung>

<minithemen>
{mts}
</minithemen>"""

FEEDBACK_SCHEMA = ai._obj({"links": {"type": "array", "items": ai._obj({
    "kind": {"type": "string", "enum": ["gut", "schlecht"]}, "text": ai._STR,
    "minitopics": {"type": "array", "items": ai._INT}})}})


def map_feedback(cfg: dict, module_id: str, ex: dict) -> int:
    """Rückmeldung einer Übung den Minithemen der zugehörigen (sonst aller bisherigen) Vorlesungen zuordnen."""
    data = load_module(module_id)
    fb = units.exercise_feedback(data, ex["id"])
    if not (fb.get("good") or fb.get("bad") or "").strip():
        return 0
    lecs = lectures(cfg, module_id, data)
    related = {lec["id"] for lec in units.related_lectures(ex, lecs)}
    mts = [m for m in topics.minitopics(data) if m["lecture_id"] in related] or topics.minitopics(data)
    if not mts:
        return 0
    result = ai.complete_json(FEEDBACK_PROMPT.format(
        good=fb.get("good") or "–", bad=fb.get("bad") or "–",
        mts="\n".join(f"[{i}] {m['topic']}: {m['title']}" for i, m in enumerate(mts, start=1))),
        FEEDBACK_SCHEMA, max_tokens=4000, effort="low", task="check")
    linked = 0
    for link in result.get("links", []):
        for nr in link["minitopics"]:
            if 1 <= nr <= len(mts):
                mastery.apply_exercise_flag(data, mts[nr - 1], ex["id"], link["kind"], link["text"].strip())
                linked += 1
    fb["mapped_at"] = now_iso()
    save_module(module_id)
    return linked


def ensure_feedback_mapped(cfg: dict, module_id: str) -> None:
    if not ai.is_available():
        return
    data = load_module(module_id)
    _, exs = units.all_units(cfg, get_module(cfg, module_id), data)
    for ex in exs:
        fb = (data.get("exercise_feedback") or {}).get(ex["id"])
        if not fb or not units.has_feedback(data, ex["id"]) or not topics.minitopics(data):
            continue
        if fb.get("mapped_at") and fb.get("updated_at", "") <= fb["mapped_at"]:
            continue
        try:
            map_feedback(cfg, module_id, ex)
        except ai.AIError:
            continue


# ---------------------------------------------------------------------------
# Feedback der Nutzerin zu einer Frage
# ---------------------------------------------------------------------------

FEEDBACK_KINDS = ("Fehler in Frage oder Lösung", "Unklar formuliert", "Sonstiges")

QUESTION_CHECK_PROMPT = """Die Studentin meldet zu dieser Übungsfrage: „{kind}“ – {text}
Prüfe die Frage sorgfältig gegen die Folien. Ist Frage, Lösung oder Begründung wirklich falsch (oder mehrdeutig),
setze error_confirmed = true und liefere die korrigierte Fassung (correct_indices bei Auswahlfragen mit 0-basierten
Indizes, number_answer bei Zahl-Aufgaben, sample_answer bei Freitext, explanation und option_notes neu – sonst
unverändert übernehmen). reply: kurze, freundliche Antwort an die Studentin (2–4 Sätze), was stimmt und warum.

<frage typ="{qtype}">
{question}
{options}
Bisher als richtig gewertet: {solution}
Begründung: {explanation}
</frage>

<folien>
{slides}
</folien>"""

QUESTION_CHECK_SCHEMA = ai._obj({
    "error_confirmed": {"type": "boolean"}, "reply": ai._STR,
    "correct_indices": {"type": "array", "items": ai._INT}, "number_answer": ai._STR, "sample_answer": ai._STR,
    "explanation": ai._STR, "option_notes": {"type": "array", "items": ai._STR}})


def question_feedback(cfg: dict, module_id: str, session: dict, idx: int, kind: str, text: str) -> dict:
    """Feedback speichern; bei gemeldetem Fehler prüft Claude die Frage und korrigiert sie ggf. (Antwort wird neu
    gewertet). Gemeldete Fragen werden nicht wiederverwendet; der Hinweis fließt in neue Fragen zum Minithema ein."""
    data = load_module(module_id)
    item = session["items"][idx]
    q = question(data, item["question_id"])
    entry = {"kind": kind, "text": text.strip(), "at": now_iso(), "session": session["id"]}
    q.setdefault("feedback", []).append(entry)
    if kind != "Sonstiges":
        q["retired"] = True
    if kind == FEEDBACK_KINDS[0] and ai.is_available():
        options = "\n".join(f"{j}) {o}" for j, o in enumerate(q.get("options", [])))
        solution = (q.get("correct_indices") if q["type"] in ("sc", "mc") else
                    q.get("number_answer") if q["type"] == "zahl" else q.get("sample_answer"))
        slides = qb._material(data, [{"slides": q.get("slides", [])}])
        result = ai.complete_json(QUESTION_CHECK_PROMPT.format(
            kind=kind, text=text or "(kein Kommentar)", qtype=q["type"], question=q["question"], options=options,
            solution=solution, explanation=q.get("explanation", ""), slides=slides),
            QUESTION_CHECK_SCHEMA, max_tokens=6000, effort="low", task="cards")
        entry["reply"] = result["reply"].strip()
        entry["confirmed"] = bool(result["error_confirmed"])
        if result["error_confirmed"]:
            q["original"] = {k: q.get(k) for k in ("correct_indices", "number_answer", "sample_answer", "explanation",
                                                    "option_notes")}
            if q["type"] in ("sc", "mc") and result["correct_indices"]:
                q["correct_indices"] = sorted(set(i for i in result["correct_indices"]
                                                  if 0 <= i < len(q.get("options", []))))
            if q["type"] == "zahl" and qb.parse_number(result["number_answer"]) is not None:
                q["number_answer"] = result["number_answer"].strip()
            if q["type"] == "freitext" and result["sample_answer"].strip():
                q["sample_answer"] = result["sample_answer"].strip()
            if result["explanation"].strip():
                q["explanation"] = result["explanation"].strip()
            if len(result["option_notes"]) == len(q.get("options", [])):
                q["option_notes"] = result["option_notes"]
            q["corrected"] = True
            if "answer" in item:  # Antwort mit der korrigierten Lösung neu werten
                if q["type"] in ("sc", "mc"):
                    item["correct"] = qb.check_choice(q, item["answer"] or [])
                elif q["type"] == "zahl":
                    item["correct"] = qb.check_number(q, item["answer"] or "")
                else:
                    item.update({"void": True, "correct": None})
    item.setdefault("feedback", []).append(entry)
    save_module(module_id)
    return entry


def feedback_notes(data: dict, mt_id: str) -> list[str]:
    """Hinweise der Nutzerin zu früheren Fragen dieses Minithemas (fließen in neue Fragen ein)."""
    return [f"{f['kind']}: {f['text']}" + (f" (bestätigt: {f.get('reply', '')})" if f.get("confirmed") else "")
            for q in data.get("questions", []) if q["minitopic_id"] == mt_id for f in q.get("feedback", [])
            if f.get("text") or f.get("confirmed")][-4:]

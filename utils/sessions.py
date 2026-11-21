"""Checks und Wochentraining: Fragen auswählen, Session anlegen, Antworten auswerten, Wissensstand buchen.

Ablauf je Vorlesung: 1 Upload · 2 Nacharbeit (Tutor-Chat) · 3 Check 1 · 4 Übungsblatt · 5 Check 2 · 6 Wochentraining.
Check 1 fragt die erste Hälfte der Minithemen ab, Check 2 die zweite (Hälfte an einer Themengrenze) – zusammen jedes
Minithema der Vorlesung. Ein Check dauert etwa 30 Minuten: reicht die Zeit nicht, werden Fragetypen vereinfacht;
bleibt Zeit, bekommt zuerst eine zweite Frage, was beim Nacharbeiten, in der Übung oder in Check 1 gehakt hat.
Wochentraining (pro Modul, fortlaufend nummeriert): 5/10/15 Fragen, Schwerpunkt auf Problemen aus den Checks, dann
Übung und Nacharbeit; gut die Hälfte (60 %) bleibt für die Wiederholung älterer Themen (fällig laut Spaced Repetition).
Taschenrechner und Notizblatt stehen immer zur Verfügung.
"""

from __future__ import annotations

import copy
from datetime import date

from utils import ai, mastery, planner, question_bank as qb, topics, units
from utils.config import get_module
from utils.storage import (days_until_exam, get_schedule, lecture_breaks, load_module, load_todos, new_id, now_iso,
                           save_module, save_todos, today)

CHECK_SIZE = 15  # Zusatzfragen höchstens bis hierhin (für die Abdeckung dürfen es mehr Minithemen sein)
CHECK_MINUTES = 30  # ein Check dauert etwa so lange
REVIEW_SHARE = 0.6  # Anteil im Wochentraining, der für die Wiederholung älterer Minithemen reserviert ist
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


def check_label(module: dict, lec: dict, part: int = 1) -> str:
    return f"Vorlesung {lec['nr']} {module['short']} Check {part}"


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


def _part(session: dict) -> int | None:
    """1 / 2; None = Check aus der Zeit vor der Aufteilung (fragte die ganze Vorlesung ab)."""
    return session.get("part")


def single_check(data: dict, lec_id: str) -> bool:
    """Vorlesung hatte schon einen Check über alle Minithemen (vor der Aufteilung) → kein Check 2."""
    return any(_part(s) is None for s in finished(data, "check", lec_id))


def check_done(data: dict, lec_id: str, part: int = 1) -> bool:
    return any(_part(s) in (part, None) for s in finished(data, "check", lec_id))


def running_check(data: dict, lec_id: str, part: int | None = None) -> dict | None:
    return next((s for s in reversed(sessions_of(data, "check", lec_id)) if not s.get("finished_at")
                 and (part is None or (_part(s) or 1) == part)), None)


def halves(data: dict, lec_id: str) -> tuple[list[dict], list[dict]]:
    """Minithemen einer Vorlesung in zwei Hälften (Folienreihenfolge, Schnitt an einer Themengrenze nahe der Mitte).
    Ist Check 1 schon gelaufen, bleibt seine Hälfte fest; alles andere (auch neue Minithemen) gehört zu Check 2."""
    mts = topics.minitopics(data, lec_id)
    fixed = next((s.get("part_ids") for s in finished(data, "check", lec_id) if _part(s) == 1 and s.get("part_ids")),
                 None)
    if fixed:
        ids = set(fixed)
        return [m for m in mts if m["id"] in ids], [m for m in mts if m["id"] not in ids]
    n = len(mts)
    if n <= 1:
        return mts, []
    bounds, prev = [], None
    for i, m in enumerate(mts):
        if prev is not None and m["topic_id"] != prev:
            bounds.append(i)
        prev = m["topic_id"]
    cut = (n + 1) // 2
    near = [b for b in bounds if abs(b - n / 2) <= max(1, n * 0.15)]
    if near:
        cut = min(near, key=lambda b: (abs(b - n / 2), b))
    return mts[:cut], mts[cut:]


def part_minitopics(data: dict, lec_id: str, part: int) -> list[dict]:
    first, second = halves(data, lec_id)
    return first if part == 1 else second


def checked_ids(data: dict) -> set[str]:
    """Minithemen, deren Check schon gelaufen ist."""
    out: set[str] = set()
    for s in finished(data, "check"):
        lec_id = s.get("lecture_id")
        if _part(s) is None:
            out |= {m["id"] for m in topics.minitopics(data, lec_id)}
        else:
            out |= {m["id"] for m in part_minitopics(data, lec_id, _part(s))}
    return out


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


def _fit_minutes(slots: list[dict], settings: dict, limit: float) -> None:
    """Fragetypen so weit vereinfachen, bis die Fragen in die Zeit passen: erst Freitext → Multiple Choice, dann
    Multiple Choice → Single Choice (von hinten, wichtige Minithemen zuletzt)."""
    def total() -> float:
        return sum(qb.MINUTES[s["type"]] for s in slots)

    order = sorted(range(len(slots)), key=lambda i: (-_IMPORTANCE_RANK.get(slots[i]["mt"].get("importance"), 1), -i))
    for src, dst in (("freitext", "mc"), ("mc", "sc"), ("zahl", "sc")):
        for i in order:
            if total() <= limit:
                return
            slot = slots[i]
            if slot["type"] == src:
                slot["level"], slot["type"] = dst, qb.question_type(slot["mt"], dst, settings)


def plan_check(data: dict, lec_id: str, settings: dict, part: int = 1) -> list[dict]:
    """Jedes Minithema der Hälfte genau einmal (Check 1 + Check 2 decken so die ganze Vorlesung ab), alles in etwa
    CHECK_MINUTES Minuten: passt es nicht, werden Fragetypen vereinfacht. Bleibt Zeit, bekommen zuerst Minithemen
    eine zweite Frage, die beim Nacharbeiten, in der Übung oder im vorigen Check gehakt haben, dann Übungsstoff,
    dann wichtige (höchstens 3 Fragen je Minithema; aufgefüllt wird nur bis CHECK_SIZE Fragen)."""
    mts = part_minitopics(data, lec_id, part)
    if not mts:
        return []
    weak = [m for m in mts if mastery.has_open_nacharbeit(data, m) or mastery.has_open_flag(data, m)]
    weak_ids = {m["id"] for m in weak}
    slots = [{"mt": m, "level": mastery.current_level(data, m)} for m in mts]
    # ein paar Freitext-Fragen zu wichtigen Erklär-Themen (nicht, wo es gehakt hat) – fallen weg, wenn die Zeit knapp ist
    free = 0
    for slot in slots:
        mt = slot["mt"]
        if free >= MAX_FREITEXT_FIRST_CHECK:
            break
        if mt.get("importance") == "hoch" and mastery.top_level(mt) == "freitext" and mt.get("kind") != "definition" \
                and mt["id"] not in weak_ids:
            slot["level"] = "freitext"
            free += 1
    for slot in slots:
        slot["type"] = qb.question_type(slot["mt"], slot["level"], settings)
    _fit_minutes(slots, settings, CHECK_MINUTES)

    # Zusatzfragen nur, solange die Zeit reicht
    def used_minutes() -> float:
        return sum(qb.MINUTES[s["type"]] for s in slots)

    def add(mt: dict, fill: bool = False) -> bool:
        if (fill and len(slots) >= CHECK_SIZE) or sum(1 for s in slots if s["mt"]["id"] == mt["id"]) >= 3:
            return False
        used = [s["level"] for s in slots if s["mt"]["id"] == mt["id"]]
        level = _next_level(max(used, key=mastery.LEVELS.index), mt) if used else mastery.current_level(data, mt)
        qtype = qb.question_type(mt, level, settings)
        if used_minutes() + qb.MINUTES[qtype] > CHECK_MINUTES:
            if level == "sc" or used_minutes() + qb.MINUTES["sc"] > CHECK_MINUTES:
                return False
            level, qtype = "sc", qb.question_type(mt, "sc", settings)
        slots.append({"mt": mt, "level": level, "type": qtype})
        return True

    earlier = [m for m in topics.minitopics(data, lec_id) if m["id"] not in {x["id"] for x in mts}
               and mastery.is_problem(data, m, "check")] if part == 2 else []
    for mt in weak + [m for m in mts if mastery.in_exercise(data, m) and m["id"] not in weak_ids]:
        add(mt)
    for mt in earlier:  # Check 2: was in Check 1 falsch oder schwer war, noch einmal
        add(mt)
    target = min(CHECK_SIZE, 3 * len(mts))
    for _ in range(3):
        if len(slots) >= target:
            break
        for mt in sorted(mts, key=lambda m: (not mastery.in_exercise(data, m),
                                             _IMPORTANCE_RANK.get(m.get("importance"), 1),
                                             m.get("kind") != "anwendung")):
            if len(slots) >= target:
                break
            add(mt, fill=True)
    return slots


def open_from_checks(data: dict) -> list[dict]:
    """Minithemen, deren Check schon gelaufen ist, die aber noch nie abgefragt wurden (Pflicht im Training)."""
    done = checked_ids(data)
    return [m for m in topics.minitopics(data) if m["id"] in done and not mastery.covered(data, m)]


def training_focus(data: dict, mts: list[dict]) -> dict[str, list[dict]]:
    """Schwerpunkte fürs Wochentraining: Probleme aus Checks, Übung, Nacharbeit, Übungsstoff (noch nicht sicher),
    offen aus Checks."""
    done = checked_ids(data)
    return {"checks": [m for m in mts if mastery.is_problem(data, m, "check")],
            "training": [m for m in mts if mastery.is_problem(data, m)],
            "uebung": [m for m in mts if mastery.has_open_flag(data, m)],
            "nacharbeit": [m for m in mts if mastery.has_open_nacharbeit(data, m) and m["id"] in done],
            "blatt": [m for m in mts if mastery.in_exercise(data, m) and mastery.status(data, m) != "sicher"],
            "offen": [m for m in mts if m["id"] in done and not mastery.covered(data, m)]}


def plan_training(data: dict, held: list[dict], n: int, settings: dict, day: date | None = None) -> list[dict]:
    day = day or today()
    order = {lec["id"]: i for i, lec in enumerate(held)}
    mts = [m for m in topics.minitopics(data) if m["lecture_id"] in order]
    done = checked_ids(data)
    focus = training_focus(data, mts)
    reserve = max(1, round(n * REVIEW_SHARE)) if n >= 5 else 0  # Wiederholung älterer Themen (Spaced Repetition)
    chosen: list[dict] = []
    ids: set[str] = set()

    def take(items: list[dict], limit: int) -> None:
        for m in items:
            if len(chosen) >= limit:
                return
            if m["id"] not in ids:
                ids.add(m["id"])
                chosen.append(m)

    def newest(m: dict) -> tuple:
        return (not mastery.in_exercise(data, m), -order[m["lecture_id"]], _IMPORTANCE_RANK.get(m.get("importance"), 1))

    keys = ("checks", "uebung", "nacharbeit", "blatt", "offen", "training")
    for key in keys:
        take(sorted(focus[key], key=newest), n - reserve)
    # Wiederholung: zuerst Minithemen aus älteren Vorlesungen (vor mehr als einer Woche), dann die der letzten Woche
    recent = {lec["id"] for lec in held if (day - lec["date"]).days <= 7}
    take(sorted(mastery.next_due(data, mts, day),
                key=lambda m: (m["lecture_id"] in recent, not mastery.in_exercise(data, m),
                               mastery.retrievability(mastery.peek(data, m["id"]), day) or 0.0)), n)
    legacy_new = [m for m in mts if m["id"] not in done and not mastery.covered(data, m)
                  and is_legacy(data, m["lecture_id"])]
    take(sorted(legacy_new, key=lambda m: (_HINT_RANK.get((mastery.archive_hint(data, m["id"]) or {}).get("label")),
                                           order[m["lecture_id"]], _IMPORTANCE_RANK.get(m.get("importance"), 1))), n)
    asked = [m for m in mts if mastery.covered(data, m)]
    take(sorted(asked, key=lambda m: (m["lecture_id"] in recent, mastery.score(data, m, day) + (-0.15 if mastery.in_exercise(data, m) else 0),
                                      order[m["lecture_id"]])), n)
    for key in keys:
        take(sorted(focus[key], key=newest), n)
    take(sorted(mts, key=lambda m: (not mastery.in_exercise(data, m), _IMPORTANCE_RANK.get(m.get("importance"), 1),
                                    mastery.score(data, m, day))), n)
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


GENERATE_BATCH = 6  # neue Fragen je KI-Anfrage – große Checks (z. B. 30 Minithemen) laufen in Paketen


def generate_batched(cfg: dict, module_id: str, requests: list[dict], settings: dict, names: dict[str, str],
                     progress=None) -> dict[int, dict | None]:
    """Neue Fragen in kleinen Paketen erzeugen: jedes Paket wird sofort im Fragenspeicher gesichert (ein Neustart nach
    einem Fehler nimmt die schon erstellten Fragen wieder), bei abgeschnittener Antwort wird das Paket halbiert.
    Gibt {slot: Frage oder None} zurück."""
    queue = [requests[i:i + GENERATE_BATCH] for i in range(0, len(requests), GENERATE_BATCH)]
    out: dict[int, dict | None] = {}
    total = len(requests)
    while queue:
        chunk = queue.pop(0)
        try:
            fresh = qb.generate(cfg, module_id, chunk, settings, names)
        except ai.TruncatedError:
            if len(chunk) == 1:
                raise
            half = len(chunk) // 2
            queue[:0] = [chunk[:half], chunk[half:]]
            continue
        for r, q in zip(chunk, fresh):
            out[r["slot"]] = q
        if progress:
            progress(len(out), total)
    return out


def build(cfg: dict, module_id: str, kind: str, slots: list[dict], settings: dict, label: str,
          lecture_id: str | None = None, part: int | None = None, progress=None) -> dict:
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
    # gleiche und benachbarte Minithemen ins selbe Paket → dieselben Folien gehen nur einmal mit
    order = {m["id"]: i for i, m in enumerate(topics.minitopics(data))}
    requests.sort(key=lambda r: (order.get(r["mt"]["id"], len(order)), r["slot"]))
    for attempt in range(2):
        if not requests:
            break
        fresh = generate_batched(cfg, module_id, requests, settings, names, progress)
        data = load_module(module_id)
        still = []
        for r in requests:
            q = fresh.get(r["slot"])
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
    if part:
        session["part"] = part
        session["part_ids"] = sorted({slot["mt"]["id"] for slot in slots})
    for old in data.get("sessions", []):  # gemerkte Stände für „Einschätzung ändern“ nur in der laufenden Session
        if old.get("finished_at"):
            for it in old["items"]:
                it.pop("mastery_before", None)
    data.setdefault("sessions", []).append(session)
    data["session_counter"] = session_no
    save_module(module_id)
    return session


def start_check(cfg: dict, module_id: str, lec: dict, settings: dict, part: int = 1, progress=None) -> dict:
    data = load_module(module_id)
    if not topics.minitopics(data, lec["id"]):
        raise ai.AIError("Für diese Vorlesung gibt es noch keine Minithemen – erst den Upload abschließen.")
    ensure_feedback_mapped(cfg, module_id)
    ensure_nacharbeit_mapped(cfg, module_id)
    data = load_module(module_id)
    slots = plan_check(data, lec["id"], settings, part)
    if not slots:
        raise ai.AIError("Für diese Hälfte gibt es keine Minithemen.")
    module = get_module(cfg, module_id)
    return build(cfg, module_id, "check", slots, settings, check_label(module, lec, part), lec["id"], part,
                 progress=progress)


def start_training(cfg: dict, module_id: str, n: int, settings: dict, progress=None) -> dict:
    data = load_module(module_id)
    held = held_lectures(cfg, module_id, data)
    ensure_feedback_mapped(cfg, module_id)
    ensure_nacharbeit_mapped(cfg, module_id)
    data = load_module(module_id)
    slots = plan_training(data, held, n, settings)
    if not slots:
        raise ai.AIError("Noch keine Minithemen für die bisherigen Vorlesungen – erst den Upload abschließen oder die "
                         "Minithemen der früheren Vorlesungen anlegen.")
    module = get_module(cfg, module_id)
    return build(cfg, module_id, "training", slots, {**settings, "n": n},
                 f"Wochentraining {next_training_number(data)} {module['short']}", progress=progress)


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
        weak = "; ".join(mastery.weak_notes(data, {"id": item["minitopic_id"]}))
        correct, grading = qb.grade_text(q, answer, weak)
        item.update({"answer": answer, "correct": correct, "grading": grading})
    item["answered_at"] = now_iso()
    save_module(module_id)
    return item


def _book(data: dict, module_id: str, session: dict, item: dict, mt: dict) -> None:
    """Antwort + Selbstbewertung im Wissensstand buchen; vorher den Stand merken (für eine spätere Änderung)."""
    before = (data.get("mastery") or {}).get(mt["id"])
    item["mastery_before"] = copy.deepcopy(before) if before is not None else None
    item["status_before"] = mastery.status(data, mt)
    mastery.record(data, mt, item.get("correct"), item["self"], source=session["kind"],
                   question_id=item["question_id"], level_asked=item["level"],
                   hints_used=item.get("hints_used", 0), days_to_exam=days_until_exam(module_id))
    item["status_after"] = mastery.status(data, mt)


def rate(cfg: dict, module_id: str, session: dict, idx: int, self_grade: str) -> bool:
    """Selbstbewertung speichern und Wissensstand buchen. True = Session damit abgeschlossen.
    War die Frage schon bewertet (Zurück → andere Einschätzung), wird die alte Buchung ersetzt."""
    data = load_module(module_id)
    item = session["items"][idx]
    if item.get("self"):
        rerate(module_id, session, idx, self_grade)
        return current_index(session) >= len(session["items"])
    item["self"] = self_grade
    mt = topics.find_minitopic(data, item["minitopic_id"])
    if mt and not item.get("void"):  # wegen eines bestätigten Fehlers nicht gewertet
        _book(data, module_id, session, item, mt)
    done = current_index(session) >= len(session["items"])
    if done:
        session["finished_at"] = now_iso()
        _mark_todos(cfg, module_id, session)
    save_module(module_id)
    return done


def rerate(module_id: str, session: dict, idx: int, self_grade: str) -> None:
    """Einschätzung einer schon bewerteten Frage ändern: Wissensstand des Minithemas auf den Stand vor dieser Frage
    zurücksetzen und diese sowie spätere Antworten zum selben Minithema in dieser Session neu buchen."""
    data = load_module(module_id)
    item = session["items"][idx]
    if item.get("self") == self_grade:
        return
    item["self"] = self_grade
    mt = topics.find_minitopic(data, item["minitopic_id"])
    if mt and not item.get("void") and "mastery_before" in item:
        later = [it for it in session["items"][idx + 1:] if it["minitopic_id"] == mt["id"] and it.get("self")
                 and not it.get("void")]
        store = data.setdefault("mastery", {})
        if item["mastery_before"] is None:
            store.pop(mt["id"], None)
        else:
            store[mt["id"]] = copy.deepcopy(item["mastery_before"])
        for it in [item] + later:
            _book(data, module_id, session, it, mt)
    elif mt:  # ältere Session ohne gemerkten Stand: nur die Einschätzung im Verlauf anpassen
        for h in reversed(mastery.peek(data, mt["id"]).get("history", [])):
            if h.get("question_id") == item["question_id"]:
                h["self"] = self_grade
                break
    save_module(module_id)


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
            state[planner.lecture_key(module_id, lec["date"], "check2" if session.get("part") == 2 else "check")] = True
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

FEEDBACK_PROMPT = """Ordne ein Übungsblatt und die Rückmeldung der Studentin dazu den Minithemen unten zu.

1. tasks: Jede Aufgabe bzw. Teilaufgabe des Blatts (kurz benannt, z. B. „A2b: Kapitalwert berechnen“) bekommt die
   Nummern ALLER Minithemen, deren Stoff man dafür braucht – meist 1–3, auch aus verschiedenen Vorlesungen.
   Übungsblätter greifen oft auf Stoff der Vorwoche oder noch früherer Vorlesungen zurück: Gehört der Inhalt zu einem
   Minithema einer früheren Vorlesung, ordne ihn DIESEM zu (nicht dem ähnlichsten Thema der Blatt-Vorlesung).
   Entscheidend ist der Inhalt, nicht die Nummer der Vorlesung. Ohne Blatttext: tasks leer.
2. links: Jede Aussage der Rückmeldung bekommt kind (gut / mittel / schlecht – wie die Studentin sie eingeordnet hat;
   steht unter „lief gut“ etwas Einschränkendes wie „mit Hilfe“ oder „Flüchtigkeitsfehler“, nimm mittel) und die
   Nummern aller Minithemen, um die es geht. Nennt sie eine Aufgabe („A3 lief schlecht“), nimm die Minithemen dieser
   Aufgabe (laut tasks). text: kurz, was genau gut lief bzw. was falsch war und warum (aus ihren Worten).
Minithemen mit * gehören zur Vorlesung des Blatts. Passt keine, minitopics leer lassen.

<uebungsblatt>
{sheet}
</uebungsblatt>

<rueckmeldung>
LIEF GUT:
{good}

GING SO:
{mid}

LIEF SCHLECHT:
{bad}
</rueckmeldung>

<minithemen>
{mts}
</minithemen>"""

# 2: auch Minithemen früherer Vorlesungen · 3: Inhalt des Blatts (Aufgaben → Minithemen) · 4: gut/mittel/schlecht
FEEDBACK_MAP_VERSION = 4
SHEET_CHARS = 18000

FEEDBACK_SCHEMA = ai._obj({
    "tasks": {"type": "array", "items": ai._obj({"task": ai._STR, "minitopics": {"type": "array", "items": ai._INT}})},
    "links": {"type": "array", "items": ai._obj({
        "kind": {"type": "string", "enum": ["gut", "mittel", "schlecht"]}, "text": ai._STR,
        "minitopics": {"type": "array", "items": ai._INT}})}})


def sheet_docs(data: dict, ex: dict) -> list[dict]:
    """Übungsblatt und Musterlösung des Termins (mit gelesenem Text)."""
    return [d for d in units.unit_docs(data, ex) if d["doc_type"] in ("uebung", "loesung")]


def _sheet_text(data: dict, ex: dict) -> str:
    from utils.storage import get_document_text

    parts = []
    for doc in sheet_docs(data, ex):
        try:
            text = get_document_text(doc).strip()
        except Exception:  # noqa: BLE001 – Text fehlt (z. B. Foto ohne Texterkennung)
            text = ""
        if text:
            parts.append(f"[{'Übungsblatt' if doc['doc_type'] == 'uebung' else 'Musterlösung'}: {doc['filename']}]"
                         f"\n{text}")
    return "\n\n".join(parts)[:SHEET_CHARS]


def exercise_scope(cfg: dict, module_id: str, data: dict, ex: dict) -> tuple[list[dict], set[str], dict[str, str]]:
    """Minithemen bis zur Vorlesung des Blatts (Blätter beziehen sich oft auf frühere Vorlesungen), die Vorlesungen
    des Blatts und Kurznamen „VL n“."""
    lecs = lectures(cfg, module_id, data)
    related = {lec["id"] for lec in units.related_lectures(ex, lecs)}
    pair = planner.sheet_lectures(get_module(cfg, module_id), get_schedule(cfg), lecture_breaks(cfg)).get(
        ex.get("index"))
    if pair:
        related.add(units.lecture_unit_id(pair["date"]))
    last = max([lec["date"] for lec in lecs if lec["id"] in related] or [ex.get("session") or today()])
    held = {lec["id"]: lec for lec in lecs if lec["date"] <= last}
    mts = [m for m in topics.minitopics(data) if m["lecture_id"] in held] or topics.minitopics(data)
    return mts, related, {lid: f"VL {lec['nr']}" for lid, lec in held.items()}


def map_feedback(cfg: dict, module_id: str, ex: dict) -> int:
    """Übungsblatt (Aufgaben) und Rückmeldung den Minithemen der zugehörigen und aller früheren Vorlesungen
    zuordnen: Aufgaben → mastery „exercise_hits“ (zählt als klausurrelevant), Rückmeldung → „exercise_flags“."""
    data = load_module(module_id)
    fb = units.exercise_feedback(data, ex["id"])
    sheet = _sheet_text(data, ex)
    has_fb = units.has_feedback(data, ex["id"])
    if not has_fb and not sheet:
        return 0
    mts, related, names = exercise_scope(cfg, module_id, data, ex)
    if not mts:
        return 0
    result = ai.complete_json(FEEDBACK_PROMPT.format(
        sheet=sheet or "–", good=fb.get("good") or "–", mid=fb.get("mid") or "–", bad=fb.get("bad") or "–",
        mts="\n".join(f"[{i}]{'*' if m['lecture_id'] in related else ''} {names.get(m['lecture_id'], '')} · "
                      f"{m['topic']}: {m['title']} – {m.get('summary', '')[:140]}" for i, m in enumerate(mts, start=1))),
        FEEDBACK_SCHEMA, max_tokens=8000, effort="low", task="check")
    hits: dict[str, list[str]] = {}
    for task in result.get("tasks", []) if sheet else []:
        for nr in sorted(set(task["minitopics"])):
            if 1 <= nr <= len(mts):
                hits.setdefault(mts[nr - 1]["id"], []).append(task["task"].strip())
    mastery.set_exercise_hits(data, ex["id"], hits)
    linked, keep = 0, set()
    for link in result.get("links", []) if has_fb else []:
        for nr in link["minitopics"]:
            if 1 <= nr <= len(mts):
                mastery.apply_exercise_flag(data, mts[nr - 1], ex["id"], link["kind"], link["text"].strip())
                keep.add((mts[nr - 1]["id"], link["kind"], link["text"].strip()))
                linked += 1
    for mt_id, e in (data.get("mastery") or {}).items():  # alte Zuordnungen dieses Blatts, die nicht mehr passen
        flags = e.get("exercise_flags") or []
        e["exercise_flags"] = [f for f in flags if f.get("exercise_id") != ex["id"]
                               or (mt_id, f.get("kind"), f.get("text")) in keep]
    fb["mapped_at"] = now_iso()
    fb["map_version"] = FEEDBACK_MAP_VERSION
    fb["sheet_read"] = bool(sheet)
    fb["mapped_docs"] = sorted(d["id"] for d in sheet_docs(data, ex))
    save_module(module_id)
    return linked + sum(len(v) for v in hits.values())


def needs_exercise_mapping(data: dict, ex: dict) -> bool:
    """Rückmeldung geändert, Blatt/Lösung neu hochgeladen oder ältere Zuordnung → neu zuordnen."""
    if not topics.minitopics(data):
        return False
    fb = (data.get("exercise_feedback") or {}).get(ex["id"]) or {}
    docs = sorted(d["id"] for d in sheet_docs(data, ex))
    if not docs and not units.has_feedback(data, ex["id"]):
        return False
    if not fb.get("mapped_at") or fb.get("map_version", 1) < FEEDBACK_MAP_VERSION:
        return True
    return fb.get("updated_at", "") > fb["mapped_at"] or docs != fb.get("mapped_docs", [])


def ensure_feedback_mapped(cfg: dict, module_id: str) -> None:
    if not ai.is_available():
        return
    data = load_module(module_id)
    _, exs = units.all_units(cfg, get_module(cfg, module_id), data)
    for ex in exs:
        if not needs_exercise_mapping(data, ex):
            continue
        try:
            map_feedback(cfg, module_id, ex)
        except ai.AIError:
            continue
        data = load_module(module_id)


def exercise_minitopics(cfg: dict, module_id: str, data: dict, ex: dict) -> list[tuple[dict, list[str]]]:
    """[(Minithema, Aufgaben)] – was in diesem Übungsblatt dran kam (Folienreihenfolge)."""
    return [(m, tasks) for m in topics.minitopics(data) if (tasks := mastery.exercise_tasks(data, m, ex["id"]))]


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


def ensure_nacharbeit_mapped(cfg: dict, module_id: str) -> None:
    """Zusammenfassungen aus der Nacharbeit, die noch keinen Minithemen zugeordnet sind, jetzt zuordnen."""
    from utils import nacharbeit

    nacharbeit.ensure_mapped(cfg, module_id)

"""Themen und Minithemen einer Vorlesung – Grundlage für Vorlesungs-Check, Wochentraining und Wissensstand.

Beim Nacharbeiten:
1. Folien sichten: Folien, die (fast) wortgleich schon in einer früheren Vorlesung des Moduls vorkamen, sowie
   Titel-/Gliederungs-/Orga-Folien werden als „nicht relevant“ vorgeschlagen (Textvergleich, ohne KI).
   Ein Klick aufs Folienbild schaltet um. Gespeichert am Dokument: excluded_slides = {"Seite": Grund}.
2. Alle übrigen Folien im Umfang werden genau gelesen (Haiku, auch Grafiken/Tabellen).
3. Hinweise zur Quiz-Erstellung (Umfang „ganze Vorlesung“ oder „Folie x bis y“, Wichtig, Streichen,
   Sonstiger Hinweis) – liegen in lecture_notes (scope, emphasized, skip, card_hint).
4. Claude zerlegt die Vorlesung in Themen und feingranulare Minithemen (data["topics"][Vorlesung]).
   Ausgelassen wird NUR, was die Nutzerin ausgeschlossen hat (Folien, Umfang, Streichen, Minithemen).
"""

from __future__ import annotations

import re

from utils import ai
from utils import definitions as defs
from utils.config import exam_format, get_module
from utils.storage import get_document_pages, load_module, new_id, now_iso, save_module
from utils.units import lecture_notes, unit_cards, unit_docs

KINDS = {"definition": "Definition", "wissen": "Wissen", "anwendung": "Anwendung", "rechenweg": "Rechenweg",
         "kopfrechnen": "Kopfrechnen"}
IMPORTANCE = {"hoch": "wichtig", "normal": "normal", "niedrig": "seltener"}
REASON_USER = "von dir ausgeblendet"
REASON_ORGA = "Titel/Gliederung/Organisatorisches"
DUP_THRESHOLD = 0.8
READ_BATCH = 12
TOPIC_CHUNK_PAGES = 60  # so viele Seiten höchstens je Anfrage beim Erstellen der Minithemen

_ORGA_WORDS = re.compile(r"\b(agenda|gliederung|inhaltsverzeichnis|inhalt|überblick|übersicht|organisatorisch\w*|"
                         r"termin\w*|literatur\w*|kontakt|sprechstunde\w*|klausur\w*|anmeldung|moodle|"
                         r"vielen dank|fragen\?|tutorium|übungsbetrieb|outline|contents)\b", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Folien sichten
# ---------------------------------------------------------------------------

def slide_docs(data: dict, lec: dict) -> list[dict]:
    """Folien-PDFs einer Vorlesung (ohne Skript und Bilder)."""
    return [d for d in unit_docs(data, lec) if d["doc_type"] == "folien" and d.get("kind") != "image"
            and d.get("path") and d["filename"].lower().endswith(".pdf")]


def material_docs(data: dict, lec: dict) -> list[dict]:
    """Alle Unterlagen, aus denen Minithemen entstehen: Folien und Skript-Teil der Vorlesung."""
    return [d for d in unit_docs(data, lec) if d["doc_type"] in ("folien", "skript", "sonstiges")
            and d.get("kind") != "image"]


def excluded(doc: dict) -> dict[int, str]:
    return {int(k): v for k, v in (doc.get("excluded_slides") or {}).items()}


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"\w{3,}", (text or "").lower()) if not w.isdigit()}


def _similar(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def suggest_exclusions(data: dict, lec: dict, lecs: list[dict], doc: dict) -> dict[int, str]:
    """Vorschläge „nicht relevant“: Titel/Orga-Folien und Folien, die schon in früheren Vorlesungen vorkamen."""
    earlier = []
    for other in lecs:
        if other["date"] >= lec["date"] or other["id"] == lec["id"]:
            continue
        for d in slide_docs(data, other):
            if d["id"] == doc["id"]:  # gemeinsame Foliendatei mehrerer Termine: nicht mit sich selbst vergleichen
                continue
            for nr, text in enumerate(get_document_pages(d), start=1):
                words = _words(text)
                if len(words) >= 8:
                    earlier.append((other, nr, words))
    result = {}
    for nr, text in enumerate(get_document_pages(doc), start=1):
        words = _words(text)
        n_words = len(re.findall(r"\w+", text or ""))
        if n_words <= 2 or (nr == 1 and n_words <= 25) or (n_words <= 45 and _ORGA_WORDS.search(text or "")):
            result[nr] = REASON_ORGA
            continue
        if len(words) < 8:
            continue
        best = max(((_similar(words, w), o, p) for o, p, w in earlier), default=(0.0, None, None), key=lambda x: x[0])
        if best[0] >= DUP_THRESHOLD:
            result[nr] = f"schon in VL {best[1]['nr']} (Folie {best[2]})"
    return result


def ensure_suggestions(module_id: str, data: dict, lec: dict, lecs: list[dict]) -> None:
    """Einmal pro Dokument: Vorschläge als ausgeschlossene Folien eintragen (mit Grund, per Klick umkehrbar)."""
    changed = False
    for doc in slide_docs(data, lec):
        if doc.get("slides_checked"):
            continue
        current = doc.setdefault("excluded_slides", {})
        for nr, reason in suggest_exclusions(data, lec, lecs, doc).items():
            current.setdefault(str(nr), reason)
        doc["slides_checked"] = now_iso()
        changed = True
    if changed:
        save_module(module_id)


def toggle_slide(module_id: str, doc_id: str, page: int) -> None:
    data = load_module(module_id)
    doc = next((d for d in data["documents"] if d["id"] == doc_id), None)
    if doc is None:
        return
    slides = doc.setdefault("excluded_slides", {})
    if str(page) in slides:
        slides.pop(str(page))
    else:
        slides[str(page)] = REASON_USER
    save_module(module_id)


# ---------------------------------------------------------------------------
# Umfang („ganze Vorlesung“ oder „Folie x bis y“) und Übertrag in die nächste Vorlesung
# ---------------------------------------------------------------------------

def scope(notes: dict) -> dict:
    sc = notes.get("scope") or {}
    return {"mode": sc.get("mode", "all"), "from": int(sc.get("from") or 1), "to": int(sc.get("to") or 0)}


def is_shared(doc: dict, lec_id: str) -> bool:
    """Foliendatei, die diese Vorlesung von einer früheren übernommen hat (eine Datei für mehrere Termine)."""
    return lec_id in (doc.get("shared_units") or []) and doc.get("unit") != lec_id


def doc_range(notes: dict, doc: dict, n_pages: int) -> tuple[int, int]:
    """Umfang (von, bis) einer Foliendatei für eine Vorlesung: eigener Bereich je Datei, sonst „Folie x bis y“
    der Vorlesung, sonst die ganze Datei. bis = 0 heißt „bis zum Ende“."""
    own = (notes.get("scopes") or {}).get(doc["id"])
    if own:
        return int(own.get("from") or 1), int(own.get("to") or 0) or n_pages
    sc = scope(notes)
    if sc["mode"] == "range":
        return sc["from"], sc["to"] or n_pages
    return 1, n_pages


def in_scope(notes: dict, page: int, n_pages: int, doc: dict | None = None) -> bool:
    if doc is not None:
        first, last = doc_range(notes, doc, n_pages)
        return first <= page <= last
    sc = scope(notes)
    if sc["mode"] != "range":
        return True
    return sc["from"] <= page <= (sc["to"] or n_pages)


def n_pages(doc: dict) -> int:
    return len(get_document_pages(doc)) or int(doc.get("n_pages") or 0)


def active_pages(data: dict, lec: dict, doc: dict) -> list[int]:
    """Seiten eines Dokuments, die für Minithemen zählen: im Umfang (nur Folien) und nicht ausgeblendet."""
    n = n_pages(doc)
    if doc["doc_type"] != "folien":
        return list(range(1, n + 1))
    notes = lecture_notes(data, lec["id"])
    skip = excluded(doc)
    return [p for p in range(1, n + 1) if p not in skip and in_scope(notes, p, n, doc)]


def carry_over(data: dict, lec: dict) -> list[dict]:
    """Folien nach dem Ende des Umfangs („nur bis Folie x“) – werden der nächsten Vorlesung angeboten."""
    notes = lecture_notes(data, lec["id"])
    result = []
    for doc in slide_docs(data, lec):
        n = n_pages(doc)
        first, last = doc_range(notes, doc, n)
        if last >= n:
            continue
        rest = [p for p in range(last + 1, n + 1) if p not in excluded(doc)]
        if rest:
            result.append({"doc_id": doc["id"], "pages": rest, "from": lec["id"], "from_nr": lec["nr"],
                           "filename": doc["filename"]})
    return result


def offered_carry(data: dict, lec: dict, lecs: list[dict]) -> list[dict]:
    """Übertrag der vorigen Vorlesung, der dieser Vorlesung angeboten wird (noch nicht bestätigt/abgelehnt)."""
    earlier = [x for x in lecs if x["date"] < lec["date"] and not x.get("is_break")]
    if not earlier:
        return []
    prev = earlier[-1]
    notes = lecture_notes(data, lec["id"])
    decided = {c["doc_id"] for c in notes.get("carry_in", [])} | set(notes.get("carry_declined", []))
    own = {d["id"] for d in slide_docs(data, lec)}
    return [c for c in carry_over(data, prev) if c["doc_id"] not in decided and c["doc_id"] not in own]


def accept_carry(module_id: str, lec_id: str, items: list[dict], accept: bool) -> None:
    """Übernehmen: dieselbe Foliendatei gilt auch für diese Vorlesung, ab der ersten noch offenen Folie."""
    data = load_module(module_id)
    notes = lecture_notes(data, lec_id)
    if accept:
        for c in items:
            doc = next((d for d in data["documents"] if d["id"] == c["doc_id"]), None)
            if doc is None:
                continue
            shared = doc.setdefault("shared_units", [])
            if lec_id not in shared:
                shared.append(lec_id)
            notes.setdefault("scopes", {})[doc["id"]] = {"from": c["pages"][0], "to": 0}
            notes.setdefault("carry_in", []).append({"doc_id": doc["id"], "pages": [], "from": c["from"]})
    else:
        notes.setdefault("carry_declined", []).extend(c["doc_id"] for c in items)
    save_module(module_id)


def set_range(module_id: str, lec_id: str, doc_id: str, first: int, last: int) -> None:
    data = load_module(module_id)
    lecture_notes(data, lec_id).setdefault("scopes", {})[doc_id] = {"from": int(first), "to": int(last)}
    save_module(module_id)


# ---------------------------------------------------------------------------
# Genau lesen (Auswahl: alle Folien / nur mit Abbildungen / keine, dazu einzelne Folien „nur Text“)
# ---------------------------------------------------------------------------

READ_MODES = {"all": "Alle Folien", "figures": "Nur Folien mit Abbildungen", "none": "Keine (nur Text)"}


def parse_pages(text: str, n: int | None = None) -> list[int]:
    """„1-50, 120, 130–135“ → [1, …, 50, 120, 130, …, 135] (ungültige Teile werden ignoriert)."""
    pages: set[int] = set()
    for part in re.split(r"[,;\s]+", (text or "").replace("–", "-").replace("—", "-")):
        m = re.fullmatch(r"(\d+)(?:-(\d+))?", part.strip())
        if not m:
            continue
        a, b = int(m.group(1)), int(m.group(2) or m.group(1))
        pages.update(range(min(a, b), max(a, b) + 1))
    return sorted(p for p in pages if p >= 1 and (n is None or p <= n))


def format_pages(pages: list[int]) -> str:
    """[1, 2, 3, 7] → „1-3, 7“."""
    out, run = [], []
    for p in sorted(set(pages)):
        if run and p == run[-1] + 1:
            run.append(p)
            continue
        if run:
            out.append(f"{run[0]}-{run[-1]}" if len(run) > 1 else str(run[0]))
        run = [p]
    if run:
        out.append(f"{run[0]}-{run[-1]}" if len(run) > 1 else str(run[0]))
    return ", ".join(out)


def read_settings(notes: dict, doc: dict) -> dict:
    own = (notes.get("scopes") or {}).get(doc["id"]) or {}
    return {"mode": own.get("read", "all") if own.get("read") in READ_MODES else "all",
            "text_only": [int(p) for p in own.get("text_only", [])]}


def set_read(module_id: str, lec_id: str, doc_id: str, mode: str, text_only: list[int]) -> None:
    data = load_module(module_id)
    entry = lecture_notes(data, lec_id).setdefault("scopes", {}).setdefault(doc_id, {})
    entry.update({"read": mode, "text_only": sorted(set(text_only))})
    save_module(module_id)


def exact_candidates(data: dict, lec: dict, doc: dict) -> list[int]:
    """Folien im Umfang, die genau gelesen werden sollen (Auswahl der Nutzerin beachtet)."""
    rs = read_settings(lecture_notes(data, lec["id"]), doc)
    if rs["mode"] == "none":
        return []
    pages = active_pages(data, lec, doc)
    if rs["mode"] == "figures":
        figs = set(doc.get("figure_pages") or [])
        pages = [p for p in pages if p in figs]
    skip = set(rs["text_only"])
    return [p for p in pages if p not in skip]


def unread_pages(data: dict, lec: dict) -> dict[str, list[int]]:
    result = {}
    for doc in slide_docs(data, lec):
        done = set(doc.get("visual_pages", []))
        pages = [p for p in exact_candidates(data, lec, doc) if p not in done]
        if pages:
            result[doc["id"]] = pages
    return result


def read_cost(data: dict, lec: dict) -> float:
    from utils.learning import page_cost_estimate

    return page_cost_estimate(sum(len(p) for p in unread_pages(data, lec).values()))


def _read_batch(cfg: dict, module_id: str, doc: dict, pages: list[int]) -> None:
    """Ein Paket genau lesen; ist die Antwort zu lang, das Paket halbieren (bis zur einzelnen Folie)."""
    from utils.learning import read_pages_visual

    try:
        read_pages_visual(cfg, module_id, doc, pages, update_prep=False)
    except ai.TruncatedError:
        if len(pages) == 1:
            return  # eine einzelne Folie zu lang → Textfassung behalten
        half = len(pages) // 2
        _read_batch(cfg, module_id, doc, pages[:half])
        _read_batch(cfg, module_id, doc, pages[half:])


def read_all(cfg: dict, module_id: str, lec: dict, progress=None) -> str:
    """Liest alle ausgewählten Folien im Umfang genau – in kleinen Paketen; jedes Paket wird sofort gespeichert,
    ein Abbruch verliert also nichts. progress(erledigt, gesamt) meldet den Stand."""
    data = load_module(module_id)
    todo = unread_pages(data, lec)
    whole = sum(len(p) for p in todo.values())
    total = 0
    for doc_id, pages in todo.items():
        for i in range(0, len(pages), READ_BATCH):
            doc = next(d for d in load_module(module_id)["documents"] if d["id"] == doc_id)
            _read_batch(cfg, module_id, doc, pages[i:i + READ_BATCH])
            total += len(pages[i:i + READ_BATCH])
            if progress:
                progress(total, whole)
    return f"{total} Folie(n) genau gelesen." if total else "Alles schon genau gelesen."


# ---------------------------------------------------------------------------
# Minithemen erzeugen
# ---------------------------------------------------------------------------

TOPICS_SYSTEM = ai.BASE_SYSTEM + """

Du zerlegst eine Vorlesung in THEMEN und darunter feingranulare MINITHEMEN. Jedes Minithema ist genau EIN
abfragbarer Aspekt, zu dem man eine eigene Klausurfrage stellen kann. Beispiel: Thema „Preiselastizität“ →
Minithemen „Definition“, „Berechnung“, „Interpretation elastisch/unelastisch“, „Einflussfaktoren“.

Regeln:
- ABDECKUNG: Jeder Inhalt der Unterlagen wird zu mindestens einem Minithema. Jede Seite steht in "pages" mindestens
  eines Minithemas – nur Titel-, Gliederungs-, Organisations- und leere Seiten kommen stattdessen in "no_minitopic".
- Ausgelassen wird NUR, was die Nutzerin ausgeschlossen hat: alles unter [STREICHEN] und Vermerke wie
  „nicht relevant“ in ihren Hinweisen. Sonst nichts weglassen – auch Theorie und Herleitungen nur dann nicht, wenn
  sie gestrichen sind.
- Beispiele aus der Vorlesung sind NIE ein eigenes Minithema (nichts zum Auswendiglernen) – außer die Hinweise
  verlangen es ausdrücklich. Die Beispielseiten gehören in "pages" des Konzepts, das sie illustrieren.
- [WICHTIG] ⇒ importance "hoch"; [NICHT SO WICHTIG] ⇒ "niedrig"; sonst "normal".
- [SONSTIGER HINWEIS] hat Vorrang vor diesen Regeln (außer: nichts erfinden).
- kind: "definition" (Begriff definieren; dann definition_term + definition im Wortlaut der Quelle, sonst beide
  leer), "wissen" (Fakten, Zusammenhänge, Eigenschaften), "anwendung" (Konzept auf einen Fall anwenden, erkennen,
  beurteilen), "rechenweg" (Vorgehen/Ansatz beim Rechnen), "kopfrechnen" (einfache Rechnung mit glattem Ergebnis).
- summary: Kerninhalt des Minithemas in 1–3 Sätzen (so, dass daraus später Fragen entstehen können; Formeln in
  LaTeX $...$).
- Keine Doppelungen, auch nicht zu den Minithemen früherer Vorlesungen (Liste FRÜHERE MINITHEMEN).
- Titel kurz und eindeutig (max. ~8 Wörter); Thema-Titel in der Sprache der Vorlesung.
- card_links: Ordne jede alte Karteikarte (Liste ALTE KARTEN) dem passendsten Minithema zu (card = Nummer,
  minitopic = nr). Passt keine, weglassen."""

TOPICS_USER = """{hint}<meta>
MODUL: {module}
VORLESUNG: {lecture}
KLAUSURFORMAT: {exam_format}
</meta>

<hinweise_der_nutzerin>
{notes}
</hinweise_der_nutzerin>

<fruehere_minithemen>
{earlier}
</fruehere_minithemen>

<alte_karten>
{cards}
</alte_karten>

<dokumente>
{documents}
</dokumente>{hint_reminder}"""

_MT = ai._obj({"nr": ai._INT, "title": ai._STR, "kind": {"type": "string", "enum": list(KINDS)},
               "importance": {"type": "string", "enum": list(IMPORTANCE)}, "summary": ai._STR,
               "definition_term": ai._STR, "definition": ai._STR, "doc": ai._INT,
               "pages": {"type": "array", "items": ai._INT}})
TOPICS_SCHEMA = ai._obj({
    "topics": {"type": "array", "items": ai._obj({"title": ai._STR, "minitopics": {"type": "array", "items": _MT}})},
    "no_minitopic": {"type": "array", "items": ai._obj({"doc": ai._INT, "pages": {"type": "array", "items": ai._INT},
                                                        "reason": ai._STR})},
    "card_links": {"type": "array", "items": ai._obj({"card": ai._INT, "minitopic": ai._INT})},
})

_NOTE_BLOCKS = (("emphasized", "WICHTIG"), ("skip", "STREICHEN"), ("briefly", "NICHT SO WICHTIG"),
                ("text", "NOTIZEN"))


def _notes_block(notes: dict) -> str:
    parts = [f"[{label}]\n{notes[field].strip()}" for field, label in _NOTE_BLOCKS if (notes.get(field) or "").strip()]
    return "\n\n".join(parts) or "keine"


def _lecture_hint(notes: dict) -> str:
    return (notes.get("card_hint") or "").strip()


def page_units(data: dict, lec: dict) -> list[tuple[dict, int]]:
    """Alle zählenden Seiten (Dokument, Seite) mit Text: Folien im Umfang ohne ausgeblendete, Skript-Teil,
    Übertrag."""
    docs = material_docs(data, lec)
    notes = lecture_notes(data, lec["id"])
    extra = []
    for c in notes.get("carry_in", []):
        doc = next((d for d in data["documents"] if d["id"] == c["doc_id"]), None)
        if doc and doc not in docs and c.get("pages"):
            extra.append((doc, c["pages"]))
    out = []
    for doc, pages in [(d, active_pages(data, lec, d)) for d in docs] + extra:
        texts = get_document_pages(doc)
        out += [(doc, p) for p in pages if 1 <= p <= len(texts) and texts[p - 1].strip()]
    return out


def _documents(data: dict, lec: dict, units: list[tuple[dict, int]] | None = None) -> tuple[str, list[dict]]:
    """Text der zählenden Seiten (oder nur der übergebenen) als <dokument>-Blöcke; order = Nummerierung."""
    units = page_units(data, lec) if units is None else units
    blocks, order, pages_of = [], [], {}
    for doc, p in units:
        if doc["id"] not in pages_of:
            pages_of[doc["id"]] = []
            order.append(doc)
        pages_of[doc["id"]].append(p)
    for nr, doc in enumerate(order, start=1):
        texts = get_document_pages(doc)
        body = [f"--- Seite {p} ---\n{texts[p - 1]}" for p in pages_of[doc["id"]]]
        blocks.append(f"<dokument nr=\"{nr}\" name=\"{doc['filename']}\" typ=\"{doc['doc_type']}\">\n"
                      + "\n\n".join(body) + "\n</dokument>")
    return "\n\n".join(blocks), order


def lecture_topics(data: dict, lec_id: str) -> dict | None:
    return (data.get("topics") or {}).get(lec_id)


def minitopics(data: dict, lec_id: str | None = None, include_excluded: bool = False) -> list[dict]:
    """Flache Liste der Minithemen (mit lecture_id und topic), optional nur einer Vorlesung."""
    result = []
    for lid, entry in (data.get("topics") or {}).items():
        if lec_id is not None and lid != lec_id:
            continue
        for topic in entry.get("topics", []):
            for mt in topic.get("minitopics", []):
                if include_excluded or not mt.get("excluded"):
                    result.append({**mt, "lecture_id": lid, "topic": topic["title"], "topic_id": topic["id"]})
    return result


def find_minitopic(data: dict, mt_id: str) -> dict | None:
    return next((m for m in minitopics(data, include_excluded=True) if m["id"] == mt_id), None)


def cost_estimate(data: dict, lec: dict) -> float:
    documents, _ = _documents(data, lec)
    size = len(documents) + len(_notes_block(lecture_notes(data, lec["id"]))) + 60 * len(unit_cards(data, lec))
    return ai.estimate_cost("cards", int(size / 3.5) + 3000, 6000)


def _chunks(units: list[tuple[dict, int]], size: int) -> list[list[tuple[dict, int]]]:
    return [units[i:i + size] for i in range(0, len(units), size)] or [[]]


def create_topics(cfg: dict, module_id: str, lec: dict, lecs: list[dict], progress=None) -> int:
    """Erzeugt (bzw. erneuert) Themen und Minithemen einer Vorlesung. Gibt die Zahl der Minithemen zurück.

    Lange Unterlagen (z. B. ein Skript mit Hunderten Seiten) werden in Abschnitten verarbeitet; ist eine Antwort
    trotzdem zu lang, wird der Abschnitt halbiert. Beim Erneuern behalten gleichnamige Minithemen ihre ID – der
    Wissensstand bleibt erhalten."""
    module = get_module(cfg, module_id)
    data = load_module(module_id)
    units = page_units(data, lec)
    notes = lecture_notes(data, lec["id"])
    if not units and _notes_block(notes) == "keine":
        raise ai.AIError("Es gibt noch keine Folien oder Notizen zu dieser Vorlesung.")
    cards = unit_cards(data, lec)[:200]
    earlier_ids = {x["id"] for x in lecs if x["date"] < lec["date"]}
    earlier = [f"- {m['topic']}: {m['title']}" for m in minitopics(data) if m["lecture_id"] in earlier_ids]
    hint = _lecture_hint(notes)
    pending = _chunks(units, TOPIC_CHUNK_PAGES)
    results: list[tuple[dict, list[dict]]] = []
    done_parts = 0
    while pending:
        chunk = pending.pop(0)
        documents, order = _documents(data, lec, chunk)
        so_far = [f"- {t['title']}: {m['title']}" for r, _ in results for t in r.get("topics", [])
                  for m in t.get("minitopics", [])]
        part = (f"\n\nTEIL: Die Unterlagen sind lang und kommen in Abschnitten. Dies ist Abschnitt "
                f"{done_parts + 1} von {done_parts + 1 + len(pending)}. Bilde Minithemen NUR für diese Seiten; "
                f"die unter <fruehere_minithemen> mit „(dieser Vorlesung)“ markierten gibt es schon."
                if len(pending) or done_parts else "")
        prompt = TOPICS_USER.format(
            hint=f"<sonstiger_hinweis>\n{hint}\n</sonstiger_hinweis>\n\n" if hint else "",
            hint_reminder=(f"\n\nERINNERUNG – sonstiger Hinweis der Nutzerin (unbedingt umsetzen):\n{hint}"
                           if hint else "") + part,
            module=module["name"], lecture=f"Vorlesung {lec['nr']} vom {lec['date']:%d.%m.%Y} – {lec['topic']}",
            exam_format=exam_format(module)["label"], notes=_notes_block(notes),
            earlier="\n".join(earlier[-150:] + [x + " (dieser Vorlesung)" for x in so_far[-150:]]) or "keine",
            cards="\n".join(f"[{i}] {c['front']}" for i, c in enumerate(cards, start=1)) or "keine",
            documents=documents or "keine")
        try:
            result = ai.complete_json(prompt, TOPICS_SCHEMA, system=TOPICS_SYSTEM, max_tokens=32000, task="cards")
        except ai.TruncatedError:
            if len(chunk) <= 4:
                raise
            half = len(chunk) // 2
            pending[:0] = [chunk[:half], chunk[half:]]
            continue
        results.append((result, order))
        done_parts += 1
        if progress:
            progress(done_parts, done_parts + len(pending))

    old = lecture_topics(data, lec["id"]) or {}
    old_ids = {(t["title"].lower(), m["title"].lower()): (t["id"], m["id"], m.get("excluded", False))
               for t in old.get("topics", []) for m in t.get("minitopics", [])}
    old_topic_ids = {t["title"].lower(): t["id"] for t in old.get("topics", [])}
    topics_by_title: dict[str, dict] = {}
    topics, no_mt = [], []
    amap = data.setdefault("archive_map", {})
    seen_mts: set[tuple[str, str]] = set()
    for result, order in results:
        by_nr = {}
        for t in result.get("topics", []):
            title = t["title"].strip()
            if not title:
                continue
            topic = topics_by_title.get(title.lower())
            if topic is None:
                topic = {"id": old_topic_ids.get(title.lower()) or new_id(), "title": title, "minitopics": []}
                topics_by_title[title.lower()] = topic
                topics.append(topic)
            for m in t.get("minitopics", []):
                mtitle = m["title"].strip()
                if not mtitle or (title.lower(), mtitle.lower()) in seen_mts:
                    continue
                seen_mts.add((title.lower(), mtitle.lower()))
                prev = old_ids.get((title.lower(), mtitle.lower()))
                doc = order[m["doc"] - 1] if 1 <= m["doc"] <= len(order) else None
                mt = {"id": prev[1] if prev else new_id(), "title": mtitle, "kind": m["kind"],
                      "importance": m["importance"], "summary": m["summary"].strip(),
                      "slides": [{"doc_id": doc["id"], "pages": sorted(set(m["pages"]))}] if doc and m["pages"] else [],
                      "excluded": bool(prev and prev[2])}
                if m["kind"] == "definition" and m["definition_term"].strip():
                    mt["term"] = m["definition_term"].strip()
                    defs.add_definition(data, m["definition_term"], m["definition"], lec["id"], lec.get("chapter_id"),
                                        with_card=False)
                topic["minitopics"].append(mt)
                by_nr[m["nr"]] = mt
        no_mt += [{"doc_id": order[x["doc"] - 1]["id"], "pages": x["pages"], "reason": x["reason"]}
                  for x in result.get("no_minitopic", []) if 1 <= x["doc"] <= len(order)]
        for link in result.get("card_links", []):
            if 1 <= link["card"] <= len(cards) and link["minitopic"] in by_nr:
                amap[cards[link["card"] - 1]["id"]] = by_nr[link["minitopic"]]["id"]
    topics = [t for t in topics if t["minitopics"]]
    if not topics:
        raise ai.AIError("Claude hat keine Minithemen geliefert – bitte noch einmal versuchen.")
    data.setdefault("topics", {})[lec["id"]] = {"created_at": now_iso(), "topics": topics, "no_minitopic": no_mt}
    save_module(module_id)
    return sum(len(t["minitopics"]) for t in topics)


def set_excluded(module_id: str, lec_id: str, mt_id: str, value: bool) -> None:
    data = load_module(module_id)
    for topic in (lecture_topics(data, lec_id) or {}).get("topics", []):
        for mt in topic["minitopics"]:
            if mt["id"] == mt_id:
                mt["excluded"] = value
    save_module(module_id)

"""Folienanalyse (Zusammenfassung) und Lernkarten-Erstellung für einzelne Vorlesungen und Übungen."""

from __future__ import annotations

import re

from utils import ai
from utils import spaced_repetition as sr
from utils.config import get_module
from utils.pdf_parser import heuristic_analysis
from utils.storage import (chapter_label, get_document_pages, get_document_text, load_module, now_iso, read_data_file,
                           save_module, set_document_pages, suggest_formulas)
from utils.units import lecture_notes, unit_docs

ANALYSIS_PROMPT = """Bereite mich auf die Vorlesung vor. Unten stehen die Folien für das Modul „{module}“,
{chapter}. Jede Folie ist mit „--- Folie N ---“ markiert.

Erstelle:
1. summary: eine Zusammenfassung in Markdown (Überschriften und Stichpunkte, Formeln in $...$), die ALLE
   Themen der Folien in der Reihenfolge der Vorlesung abdeckt – so, dass ich danach weiß, worum es geht
   und wie die Themen zusammenhängen.
2. key_concepts: alle wichtigen Fachbegriffe mit prägnanter Erklärung.
3. important_slides: Folien, die ich mir unbedingt genau ansehen muss (wichtige Abbildungen, Diagramme,
   Herleitungen, Beispiele) – mit Foliennummer (page) und Begründung.
4. check_questions: genau 3 schnelle Verständnisfragen zum ersten Check, jeweils mit kurzer Musterantwort.
5. formulas: alle mathematischen und betriebswirtschaftlichen Formeln als sauberes LaTeX (ohne $-Zeichen)
   mit Name, kurzer Erklärung der Variablen und Foliennummer. Übernimm sie exakt wie auf den Folien.

<folien>
{text}
</folien>"""

CARDS_PROMPT = """Erstelle Lernkarten (Karteikarten) für {scope} im Modul „{module}“.

Ziel: Wer alle Karten beherrscht, kann den KOMPLETTEN Stoff – nicht nur die groben Hauptpunkte.
- Gehe die Unterlagen vollständig und der Reihe nach durch (Folie für Folie bzw. Aufgabe für Aufgabe).
- Decke wirklich alles ab: jede Definition, jedes Konzept, jede Annahme, jede Formel (wie lautet sie,
  was bedeuten die Variablen, wann wendet man sie an), jeden Zusammenhang, jede Abgrenzung, Vor- und
  Nachteile, Beispiele, Rechenschemata und typische Fehler.
- Meine Nachbereitungs-Notizen sind besonders wichtig: Was der Dozent betont hat, bekommt zusätzliche
  Karten (auch Anwendungs- und Transferfragen). Inhalte aus Notizen oder Tafelbildern, die nicht auf den
  Folien stehen, unbedingt aufnehmen. „Nur kurz Angerissenes“ trotzdem abdecken, aber knapper.
- Bei Übungen: Lösungswege als Karten (Ansatz, Rechenschritte, Ergebnisinterpretation), ohne nur
  Zahlen auswendig lernen zu lassen.
- Eine Karte = ein abfragbarer Gedanke. Vorderseite als konkrete Frage, Rückseite als präzise,
  klausurtaugliche Antwort. Formeln in LaTeX mit $...$.
- Die Anzahl ergibt sich aus dem Stoffumfang – lieber vollständig als knapp.
- Diese Karten gibt es schon (keine Duplikate, nur Fehlendes ergänzen): {existing}
- chapter_hint: Titel des passenden Kapitels aus dieser Liste: {chapters}

<unterlagen>
{material}
</unterlagen>"""


VISUAL_PROMPT = """Bereite mich auf die Vorlesung vor. Das angehängte PDF sind die Folien für das Modul „{module}“,
{chapter}. Lies jede Folie vollständig – auch Formeln, Tabellen, Diagramme und Abbildungen.

Erstelle:
1. slides: für JEDE Folie (page = Foliennummer) eine vollständige Textfassung: aller Text, Formeln exakt als
   LaTeX in $...$, Tabellen als Markdown, Diagramme/Abbildungen in [eckigen Klammern] kurz, aber mit allen
   Achsen, Werten und Aussagen beschrieben. Nichts zusammenfassen, nichts weglassen.
2. summary: eine Zusammenfassung in Markdown (Überschriften, Stichpunkte, Formeln in $...$), die ALLE Themen der
   Folien in der Reihenfolge der Vorlesung abdeckt.
3. key_concepts: alle wichtigen Fachbegriffe mit prägnanter Erklärung.
4. important_slides: Folien, die ich mir unbedingt genau ansehen muss (wichtige Abbildungen, Diagramme,
   Herleitungen, Beispiele) – mit Foliennummer (page) und Begründung.
5. check_questions: genau 3 schnelle Verständnisfragen zum ersten Check, jeweils mit kurzer Musterantwort.
6. formulas: alle Formeln als sauberes LaTeX (ohne $-Zeichen) mit Name, Erklärung der Variablen und Foliennummer.
   Übernimm sie exakt wie auf den Folien."""

MAX_VISUAL_BYTES = 30 * 1024 * 1024


def visual_enabled() -> bool:
    from utils.storage import load_settings

    return bool(load_settings().get("ai", {}).get("visual_pdf"))


def run_analysis(cfg: dict, module_id: str, doc: dict, visual: bool | None = None) -> str:
    """Analysiert einen Foliensatz und legt Formel-Vorschläge zur Prüfung ab. Gibt eine Statusmeldung zurück.

    visual=True: Claude liest das PDF selbst (inkl. Formeln und Grafiken) und ersetzt den gespeicherten Text
    durch diese genauere Fassung – davon profitieren auch Karteikarten, Tutor und Podcast. Kostet mehr.
    """
    module = get_module(cfg, module_id)
    data = load_module(module_id)
    visual = visual_enabled() if visual is None else visual
    chapter = chapter_label(data, doc.get("chapter_id")) if doc.get("chapter_id") else "ohne Kapitelangabe"
    if ai.is_available() and visual and doc.get("kind") != "image":
        content = read_data_file(doc["path"])
        if len(content) > MAX_VISUAL_BYTES:
            raise ai.AIError("Die Datei ist für die genaue Lesung zu groß (max. 30 MB). Bitte normal analysieren.")
        result = ai.complete_json([ai.pdf_block(content),
                                   {"type": "text", "text": VISUAL_PROMPT.format(module=module["name"], chapter=chapter)}],
                                  ai.VISUAL_ANALYSIS_SCHEMA, max_tokens=64000)
        slides = sorted(result.pop("slides", []), key=lambda s: s["page"])
        if slides:
            set_document_pages(doc, [s["text"] for s in slides], "ki-genau")
        result["mode"] = "ki"
        result["visual"] = True
    elif ai.is_available():
        result = ai.complete_json(ANALYSIS_PROMPT.format(module=module["name"], chapter=chapter,
                                                         text=get_document_text(doc, label="Folie")),
                                  ai.ANALYSIS_SCHEMA)
        result["mode"] = "ki"
    else:
        result = heuristic_analysis(get_document_pages(doc))
    result["created_at"] = now_iso()
    doc["analysis"] = result
    save_module(module_id)
    added = suggest_formulas(module_id, result.get("formulas", []),
                             source=f"{doc['filename']} ({'KI' if result['mode'] == 'ki' else 'heuristisch'})",
                             chapter_id=doc.get("chapter_id"))
    if added:
        return (f"Zusammenfassung erstellt. {added} Formel-Vorschlag/-Vorschläge – bitte unter "
                "„Formeln & Notizen“ prüfen, welche übernommen werden sollen.")
    return "Zusammenfassung erstellt."


def _notes_material(data: dict, unit: dict) -> str:
    notes = lecture_notes(data, unit["id"])
    parts = [f"{label}:\n{notes[field]}" for field, label in
             (("text", "Meine Notizen"), ("emphasized", "Vom Dozenten betont"),
              ("briefly", "Nur kurz angerissen"), ("examples", "Genannte Beispiele")) if notes[field].strip()]
    parts += [f"Tafelbild „{img['name']}“:\n{img['transcript']}" for img in notes["images"]
              if img.get("transcript") and not img.get("in_notes")]
    return "\n\n".join(parts)


def unit_material(data: dict, unit: dict, summaries_only: bool = False) -> str:
    """Unterlagen + Nachbereitung einer Einheit als KI-Kontext (bei vielen Vorlesungen nur Zusammenfassungen)."""
    material = []
    for doc in unit_docs(data, unit):
        if summaries_only:
            analysis = doc.get("analysis") or {}
            text = analysis.get("summary", "") + "\n" + "\n".join(
                f"- {c['term']}: {c['explanation']}" for c in analysis.get("key_concepts", []))
        else:
            text = get_document_text(doc)
        if text.strip():
            material.append(f"<dokument name=\"{doc['filename']}\" typ=\"{doc['doc_type']}\">\n{text}\n</dokument>")
    if unit["kind"] == "lecture" and (notes := _notes_material(data, unit)):
        material.append(f"<nachbereitung>\n{notes}\n</nachbereitung>")
    return "\n\n".join(material)


def _offline_cards(data: dict, unit: dict) -> list[dict]:
    """Ohne KI: Karten aus Analyse-Fragen, Kernbegriffen und Notizzeilen der Form „Begriff: Erklärung“."""
    cards = []
    for doc in unit_docs(data, unit):
        analysis = doc.get("analysis") or {}
        for q in analysis.get("check_questions", []):
            cards.append({"front": q["question"], "back": q["answer"]})
        for c in analysis.get("key_concepts", []):
            if not c["term"].startswith("Folie"):
                cards.append({"front": f"Was versteht man unter „{c['term']}“?", "back": c["explanation"]})
    if unit["kind"] == "lecture":
        notes = lecture_notes(data, unit["id"])
        for line in (notes["text"] + "\n" + notes["emphasized"]).splitlines():
            m = re.match(r"^\s*[-•*]?\s*([^:]{3,60}):\s+(.{5,})$", line)
            if m:
                cards.append({"front": f"{m.group(1).strip()}?", "back": m.group(2).strip()})
    return cards


def generate_unit_cards(cfg: dict, module_id: str, unit: dict, existing_cards: list[dict]) -> int:
    """Erstellt bzw. ergänzt die Lernkarten einer Vorlesung/Übung. Gibt die Zahl neuer Karten zurück."""
    module = get_module(cfg, module_id)
    data = load_module(module_id)
    if ai.is_available():
        material = unit_material(data, unit)
        if not material.strip():
            raise ai.AIError("Es gibt noch keine Unterlagen oder Notizen, aus denen Karten entstehen können.")
        title = unit.get("topic") or unit.get("title") or ""
        scope = (f"die Vorlesung vom {unit['date']:%d.%m.%Y} („{title}“)" if unit["kind"] == "lecture"
                 else f"die Übung „{title}“")
        chapters = {ch["title"]: ch["id"] for ch in data["chapters"]}
        existing = "; ".join(c["front"] for c in existing_cards) or "keine"
        result = ai.complete_json(CARDS_PROMPT.format(scope=scope, module=module["name"], existing=existing,
                                                      chapters=", ".join(chapters), material=material),
                                  ai.CARDS_SCHEMA, max_tokens=64000, task="cards")
        raw = [{"front": c["front"], "back": c["back"],
                "chapter_id": chapters.get(c.get("chapter_hint")) or unit.get("chapter_id")}
               for c in result.get("cards", [])]
        source = "KI"
    else:
        raw = _offline_cards(data, unit)
        source = "auto"
    known = {c["front"].strip().lower() for c in data["cards"]}
    added = 0
    for item in raw:
        if not item["front"].strip() or item["front"].strip().lower() in known:
            continue
        card = sr.new_card(item["front"], item["back"], source=source,
                           chapter_id=item.get("chapter_id") or unit.get("chapter_id"))
        card["unit"] = unit["id"]
        data["cards"].append(card)
        known.add(item["front"].strip().lower())
        added += 1
    data.setdefault("cards_generated", {})[unit["id"]] = now_iso()
    save_module(module_id)
    return added

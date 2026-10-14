"""PDF-Verarbeitung: Text-/Formelextraktion und automatische Zuordnung von Uploads."""

from __future__ import annotations

import gc
import io
import re
import zipfile
from pathlib import PurePosixPath

import streamlit as st

MAX_ZIP_MEMBER_BYTES = 150 * 1024 * 1024  # Schutz vor übergroßen Archiv-Einträgen


@st.cache_data(show_spinner=False, max_entries=8)
def extract_pdf(content: bytes) -> dict:
    """Extrahiert den Text seitenweise. pypdf zuerst (sparsam), pdfplumber nur als Fallback bei kleinen Dateien."""
    pages: list[str] = []
    method = "pypdf"
    try:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(content))
        pages = [(page.extract_text() or "") for page in reader.pages]
    except Exception:  # noqa: BLE001 - jede Parser-Ausnahme -> Fallback
        pages = []
    # pdfplumber braucht viel Arbeitsspeicher – nur für kleinere PDFs, wenn pypdf nichts findet
    if not any(p.strip() for p in pages) and len(content) <= 25 * 1024 * 1024:
        method = "pdfplumber"
        try:
            import pdfplumber

            with pdfplumber.open(io.BytesIO(content)) as pdf:
                pages = []
                for page in pdf.pages:
                    pages.append(page.extract_text() or "")
                    page.flush_cache()
        except Exception:  # noqa: BLE001
            method = "fehlgeschlagen"
    pages = [_clean(p) for p in pages]
    gc.collect()
    return {"pages": pages, "method": method}


def _clean(text: str) -> str:
    text = text.replace("\u00ad", "")  # weiche Trennstriche
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def pdfs_from_zip(content: bytes) -> list[tuple[str, bytes]]:
    """Liest alle PDFs aus einem ZIP (z. B. Moodle-Ordnerdownload). Pfade bleiben für die Zuordnung erhalten."""
    result = []
    with zipfile.ZipFile(io.BytesIO(content)) as zf:
        for info in zf.infolist():
            name = info.filename
            if info.is_dir() or "__MACOSX" in name or PurePosixPath(name).name.startswith("."):
                continue
            if not name.lower().endswith(".pdf") or info.file_size > MAX_ZIP_MEMBER_BYTES:
                continue
            result.append((name, zf.read(info)))
    return result


# ---------------------------------------------------------------------------
# Formeln
# ---------------------------------------------------------------------------

UNICODE_TO_LATEX = {
    "∑": r"\sum ", "∏": r"\prod ", "√": r"\sqrt ", "∫": r"\int ", "∂": r"\partial ",
    "≤": r"\leq ", "≥": r"\geq ", "≠": r"\neq ", "≈": r"\approx ", "±": r"\pm ",
    "·": r"\cdot ", "×": r"\times ", "÷": r"\div ", "∞": r"\infty ", "→": r"\rightarrow ",
    "⇒": r"\Rightarrow ", "⇔": r"\Leftrightarrow ", "∈": r"\in ", "∉": r"\notin ",
    "⊂": r"\subset ", "⊆": r"\subseteq ", "∪": r"\cup ", "∩": r"\cap ", "∅": r"\emptyset ",
    "α": r"\alpha ", "β": r"\beta ", "γ": r"\gamma ", "δ": r"\delta ", "Δ": r"\Delta ",
    "ε": r"\varepsilon ", "η": r"\eta ", "θ": r"\theta ", "λ": r"\lambda ", "μ": r"\mu ",
    "π": r"\pi ", "ρ": r"\rho ", "σ": r"\sigma ", "Σ": r"\Sigma ", "τ": r"\tau ",
    "φ": r"\varphi ", "χ": r"\chi ", "ω": r"\omega ", "Ω": r"\Omega ", "€": r"\text{€}",
    "²": "^2", "³": "^3", "¹": "^1", "⁰": "^0", "ⁿ": "^n", "₀": "_0", "₁": "_1",
    "₂": "_2", "₃": "_3", "ₜ": "_t", "ᵢ": "_i", "%": r"\%",
}

_MATH_CHARS = set("=+-*/^∑∏√∫∂≤≥≠≈±·×÷∞Δσμαβλπρ²³()")
_NUMERIC_ASSIGNMENT = re.compile(r"(\s*\w{1,6}\s*=\s*[-\d.,\s%€]+[;,]?)+")
_FORMULA_LINE = re.compile(r"[A-Za-zΑ-ω_]\s*(\(|_|\^)?.{0,40}[=≤≥≈]")


def unicode_to_latex(text: str) -> str:
    out = []
    for ch in text:
        out.append(UNICODE_TO_LATEX.get(ch, ch))
    latex = "".join(out)
    # Brüche der Form a/b vorsichtig in \frac umwandeln (nur einfache Tokens)
    latex = re.sub(r"\b([\w.]+)\s*/\s*([\w.]+)\b", r"\\frac{\1}{\2}", latex)
    return latex.strip()


def find_formula_candidates(pages: list[str], max_items: int = 40) -> list[dict]:
    """Heuristische Formelerkennung ohne KI: kurze Zeilen mit Gleichheits-/Relationszeichen."""
    seen = set()
    candidates = []
    for page_no, text in enumerate(pages, start=1):
        for line in text.splitlines():
            line = line.strip()
            if not (4 <= len(line) <= 140) or "http" in line or "@" in line:
                continue
            if not _FORMULA_LINE.search(line):
                continue
            math_share = sum(ch in _MATH_CHARS or ch.isdigit() for ch in line) / len(line)
            words = re.findall(r"[A-Za-zÄÖÜäöüß]{4,}", line)
            if math_share < 0.12 or len(words) > 6:
                continue
            if _NUMERIC_ASSIGNMENT.fullmatch(line):
                continue  # reine Zahlenwerte wie „i = 0,08“ sind keine Formeln
            key = re.sub(r"\s+", "", line)
            if key in seen:
                continue
            seen.add(key)
            name = ""
            if ":" in line.split("=")[0]:
                name, line = [part.strip() for part in line.split(":", 1)]
            candidates.append({
                "name": name or f"Formel (S. {page_no})",
                "latex": unicode_to_latex(line),
                "raw": line,
                "page": page_no,
                "explanation": f"Automatisch erkannt auf Seite {page_no} – bitte prüfen.",
            })
            if len(candidates) >= max_items:
                return candidates
    return candidates


# ---------------------------------------------------------------------------
# Heuristische Analyse (ohne KI)
# ---------------------------------------------------------------------------

_FIGURE_HINT = re.compile(r"\b(Abb\.|Abbildung|Grafik|Diagramm|Schaubild|Tabelle|Tab\.|Figure|Chart|Kurve)\b",
                          re.IGNORECASE)
_DEFINITION = re.compile(r"(Definition|versteht man|bezeichnet man|wird definiert|heißt|Merke|Wichtig)",
                         re.IGNORECASE)


def page_title(text: str) -> str:
    for line in text.splitlines():
        line = line.strip(" •-–·\t")
        if 3 <= len(line) <= 90 and not re.fullmatch(r"[\d\s/.]+", line):
            return line
    return ""


def find_figure_hints(pages: list[str]) -> list[dict]:
    hints = []
    for page_no, text in enumerate(pages, start=1):
        match = _FIGURE_HINT.search(text)
        if match:
            line = next((ln for ln in text.splitlines() if match.group(0) in ln), match.group(0))
            hints.append({"page": page_no, "reason": f"Verweis auf {match.group(0)}: „{line.strip()[:100]}“"})
        elif len(text.strip()) < 60:
            hints.append({"page": page_no,
                          "reason": "Kaum Text – vermutlich eine Grafik-/Diagrammfolie, unbedingt im Original ansehen."})
    return hints


def heuristic_analysis(pages: list[str]) -> dict:
    """Fallback-Analyse ohne API-Key: Gliederung, Definitionen, Abbildungen, Check-Fragen."""
    titles = []
    for page_no, text in enumerate(pages, start=1):
        title = page_title(text)
        if title and title not in [t for _, t in titles]:
            titles.append((page_no, title))

    concepts = []
    for page_no, text in enumerate(pages, start=1):
        for line in text.splitlines():
            if _DEFINITION.search(line) and 20 <= len(line) <= 220:
                concepts.append({"term": f"Folie {page_no}", "explanation": line.strip()})
        if len(concepts) >= 10:
            break

    summary_lines = ["**Gliederung der Folien (automatisch aus den Folientiteln):**", ""]
    summary_lines += [f"- Folie {p}: {t}" for p, t in titles[:25]]
    questions = []
    for page_no, title in titles[1:4] if len(titles) > 3 else titles[:3]:
        questions.append({
            "question": f"Erläutern Sie in eigenen Worten: {title}",
            "answer": f"Siehe Folie {page_no}. (Für ausformulierte Musterantworten API-Key hinterlegen.)",
        })
    return {
        "summary": "\n".join(summary_lines),
        "key_concepts": concepts,
        "important_slides": find_figure_hints(pages)[:12],
        "check_questions": questions,
        "formulas": find_formula_candidates(pages),
        "mode": "heuristik",
    }


# ---------------------------------------------------------------------------
# Automatische Zuordnung beim Bulk-Upload
# ---------------------------------------------------------------------------

DOC_TYPE_PATTERNS = [
    ("loesung", r"l(ö|oe|o)sung|musterl|solution|loes"),
    ("altklausur", r"klausur|exam|pr(ü|ue)fung|probeklausur"),
    ("uebung", r"(ü|ue)bung|blatt|exercise|aufgabe|tutorium|problem.?set|sheet"),
    ("folien", r"folie|vorlesung|slides|lecture|\bvl\b|vl[\s_-]?\d|kapitel|chapter|foliensatz"),
    ("skript", r"skript|script|literatur|reader|lehrbuch"),
]


def guess_doc_type(path: str, text: str = "") -> str:
    name = path.lower()
    for doc_type, pattern in DOC_TYPE_PATTERNS:
        if re.search(pattern, name):
            return doc_type
    head = text[:1500].lower()
    if re.search(r"musterl(ö|oe)sung|l(ö|oe)sungsvorschlag", head):
        return "loesung"
    if re.search(r"klausur|bearbeitungszeit|hilfsmittel", head):
        return "altklausur"
    if re.search(r"(ü|ue)bungsblatt|aufgabe\s+\d", head):
        return "uebung"
    return "folien"


def guess_module(path: str, text: str, modules_cfg: list[dict]) -> tuple[str | None, float]:
    """Punktesystem: Treffer im Pfad zählen stark, Treffer im Text schwächer."""
    name = path.lower()
    body = text[:20000].lower()
    best_id, best_score = None, 0.0
    for module in modules_cfg:
        score = 0.0
        tokens = [module["id"], module["short"].lower(), *[k.lower() for k in module["keywords"]]]
        for token in tokens:
            if token and token in name:
                score += 5
            if len(token) > 3:
                score += min(body.count(token), 10) * 0.3
        if module["name"].lower() in body:
            score += 4
        if score > best_score:
            best_id, best_score = module["id"], score
    return best_id, best_score


_CHAPTER_NR = re.compile(r"(?:kap(?:itel)?|chapter|ch|vl|vorlesung|lecture|woche|week|blatt|sheet|einheit|teil)"
                         r"[\s_.\-]*0*(\d{1,2})", re.IGNORECASE)


def guess_chapter_index(path: str, text: str, chapters: list[dict]) -> int:
    """Gibt den 1-basierten Kapitelindex zurück (0 = unbekannt)."""
    if not chapters:
        return 0
    match = _CHAPTER_NR.search(path) or _CHAPTER_NR.search(text[:300])
    if match:
        number = int(match.group(1))
        keyword = match.group(0).lower()
        if keyword.startswith(("woche", "week")):
            # Woche -> Kapitel, das in dieser Woche läuft
            candidates = [i for i, ch in enumerate(chapters, start=1) if (ch.get("week") or 99) <= number]
            return candidates[-1] if candidates else 1
        if 1 <= number <= len(chapters):
            return number
    head = text[:3000].lower()
    best, best_hits = 0, 0
    for i, ch in enumerate(chapters, start=1):
        words = [w for w in re.findall(r"[a-zäöüß]{5,}", ch["title"].lower())]
        hits = sum(head.count(w) for w in words)
        if hits > best_hits:
            best, best_hits = i, hits
    return best


_LECTURE_NR = re.compile(r"(?:(?<!\d)(\d{1,2})\.?[\s_\-]*(?:vorlesung|vl\b|lecture|einheit))|"
                         r"(?:(?:vorlesung|vl|lecture|einheit)[\s_.\-]*0*(\d{1,2})(?!\d))", re.IGNORECASE)
_SHEET_NR = re.compile(r"(?:(?:ü|ue|u)bungsblatt|blatt|sheet|problem[\s_\-]?set)[\s_.\-]*0*(\d{1,2})(?!\d)",
                       re.IGNORECASE)


def guess_chapter_from_plan(path: str, module_cfg: dict) -> str | None:
    """Kapitel anhand des Kursablaufs: „4. Vorlesung“ → Thema der 4. Vorlesung, „Übungsblatt 2“ → Kapitel von Blatt 2."""
    name = PurePosixPath(path).name
    sheet = _SHEET_NR.search(name)
    if sheet:
        number = int(sheet.group(1))
        pattern = re.compile(rf"blatt\s*{number}\b", re.IGNORECASE)
        for ex in module_cfg.get("exercises", []):
            if pattern.search(ex.get("title", "")) and ex.get("chapter_id"):
                return ex["chapter_id"]
        return None
    lecture = _LECTURE_NR.search(name)
    if lecture:
        number = int(lecture.group(1) or lecture.group(2))
        if "einheit" in lecture.group(0).lower():
            for ch in module_cfg.get("chapters", []):
                if re.search(rf"\beinheit\s*{number}\b", ch.get("title", ""), re.IGNORECASE):
                    return ch["id"]
        lectures = sorted(module_cfg.get("lectures", []), key=lambda lec: lec["date"])
        for lec in lectures:  # Nummerierung im Thema hat Vorrang (z. B. Mathe: „4. Vorlesung“)
            if re.match(rf"{number}\.\s", lec.get("topic", "")):
                return lec.get("chapter_id")
        if 1 <= number <= len(lectures):
            return lectures[number - 1].get("chapter_id")
    return None

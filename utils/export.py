"""Export (Markdown / PDF) und Backup (ZIP) der Lerninhalte."""

from __future__ import annotations

import io
import re
import zipfile
from datetime import datetime
from pathlib import Path, PurePosixPath

from utils import cloud_sync
from utils.config import get_module
from utils.storage import DATA_DIR, chapter_label, get_notes

# Ein Export besteht aus einer Liste von Blöcken (art, inhalt) – daraus werden
# Markdown und PDF erzeugt, damit beide Formate identische Inhalte haben.
Block = tuple[str, object]

UNICODE_FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans.ttf",
    "/Library/Fonts/Arial Unicode.ttf",
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    "C:/Windows/Fonts/arial.ttf",
    "C:/Windows/Fonts/segoeui.ttf",
]


def build_blocks(cfg: dict, modules_data: dict[str, dict], module_ids: list[str], include: dict) -> list[Block]:
    blocks: list[Block] = [("title", f"{cfg['app']['title']} – Lernexport"),
                           ("meta", f"Erstellt am {datetime.now():%d.%m.%Y %H:%M}")]
    for module_id in module_ids:
        module = get_module(cfg, module_id)
        data = modules_data[module_id]
        blocks.append(("h1", f"{module['icon']} {module['name']}"))

        for ch in data["chapters"]:
            ch_blocks: list[Block] = []
            if include.get("summaries"):
                for doc in data["documents"]:
                    analysis = doc.get("analysis")
                    if doc.get("chapter_id") != ch["id"] or not analysis:
                        continue
                    ch_blocks.append(("h3", f"Zusammenfassung: {doc['filename']}"))
                    ch_blocks.append(("p", analysis.get("summary", "")))
                    for concept in analysis.get("key_concepts", []):
                        ch_blocks.append(("bullet", f"{concept['term']}: {concept['explanation']}"))
                    if analysis.get("important_slides"):
                        ch_blocks.append(("h4", "Wichtige Folien/Abbildungen"))
                        for s in analysis["important_slides"]:
                            ch_blocks.append(("bullet", f"Folie {s['page']}: {s['reason']}"))
            if include.get("notes"):
                notes = data["notes"].get(ch["id"])
                if notes and any(notes.get(k) for k in ("text", "emphasized", "briefly", "examples", "pitch")):
                    notes = get_notes(data, ch["id"])
                    ch_blocks.append(("h3", "Eigene Notizen"))
                    for field, label in (("text", "Notizen"), ("emphasized", "Sehr wichtig"),
                                         ("briefly", "Nicht so wichtig"), ("examples", "Genannte Beispiele")):
                        if notes.get(field, "").strip():
                            ch_blocks.append(("h4", label))
                            ch_blocks.append(("p", notes[field]))
            if include.get("notes"):
                for lec in module.get("lectures", []):
                    notes = data.get("lecture_notes", {}).get(f"vl:{lec['date']}") or {}
                    if lec.get("chapter_id") != ch["id"] or not any(
                            (notes.get(k) or "").strip() for k in ("text", "emphasized", "briefly", "examples")):
                        continue
                    ch_blocks.append(("h3", f"Nachbereitung Vorlesung {lec['date'][8:10]}.{lec['date'][5:7]}.: "
                                            f"{lec.get('topic', '')}"))
                    for field, label in (("text", "Notizen"), ("emphasized", "Sehr wichtig"),
                                         ("briefly", "Nicht so wichtig"), ("examples", "Genannte Beispiele")):
                        if (notes.get(field) or "").strip():
                            ch_blocks.append(("h4", label))
                            ch_blocks.append(("p", notes[field]))
            if include.get("formulas"):
                formulas = [f for f in data["formulas"] if f.get("chapter_id") == ch["id"]]
                if formulas:
                    ch_blocks.append(("h3", "Formeln"))
                    for f in formulas:
                        ch_blocks.append(("formula", f))
            if include.get("cards"):
                cards = [c for c in data["cards"] if c.get("chapter_id") == ch["id"]]
                if cards:
                    ch_blocks.append(("h3", "Lernkarten"))
                    for c in cards:
                        ch_blocks.append(("qa", (c["front"], c["back"])))
            if ch_blocks:
                blocks.append(("h2", chapter_label(data, ch["id"])))
                blocks.extend(ch_blocks)

        # Inhalte ohne Kapitelzuordnung
        chapter_ids = {ch["id"] for ch in data["chapters"]}
        loose: list[Block] = []
        if include.get("formulas"):
            for f in data["formulas"]:
                if f.get("chapter_id") not in chapter_ids:
                    loose.append(("formula", f))
        if include.get("cards"):
            for c in data["cards"]:
                if c.get("chapter_id") not in chapter_ids:
                    loose.append(("qa", (c["front"], c["back"])))
        if loose:
            blocks.append(("h2", "Ohne Kapitelzuordnung"))
            blocks.extend(loose)
    return blocks


def to_markdown(blocks: list[Block]) -> str:
    lines: list[str] = []
    for kind, content in blocks:
        if kind == "title":
            lines += [f"# {content}", ""]
        elif kind == "meta":
            lines += [f"_{content}_", ""]
        elif kind == "h1":
            lines += ["", f"# {content}", ""]
        elif kind == "h2":
            lines += ["", f"## {content}", ""]
        elif kind == "h3":
            lines += [f"### {content}", ""]
        elif kind == "h4":
            lines += [f"**{content}**", ""]
        elif kind == "p":
            lines += [str(content), ""]
        elif kind == "bullet":
            lines.append(f"- {content}")
        elif kind == "formula":
            f = content
            lines += [f"**{f['name']}**", "", "$$", f["latex"], "$$", ""]
            if f.get("explanation"):
                lines += [f"> {f['explanation']}", ""]
        elif kind == "qa":
            q, a = content
            lines += [f"**Frage:** {q}", "", f"**Antwort:** {a}", ""]
    return "\n".join(lines).replace("\n\n\n", "\n\n")


def _find_font() -> str | None:
    for path in UNICODE_FONT_CANDIDATES:
        if Path(path).exists():
            return path
    return None


def to_pdf(blocks: list[Block]) -> bytes:
    """PDF-Erzeugung mit fpdf2. Formeln erscheinen als LaTeX-Quelltext (für Rendering: Markdown-Export nutzen)."""
    from fpdf import FPDF

    pdf = FPDF(format="A4")
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    font_path = _find_font()
    if font_path:
        pdf.add_font("Uni", "", font_path)
        family, bold = "Uni", ""

        def clean(text: str) -> str:
            return str(text)
    else:
        family, bold = "Helvetica", "B"

        def clean(text: str) -> str:
            return str(text).encode("latin-1", "replace").decode("latin-1")

    def strip_emoji(text: str) -> str:
        return re.sub(r"[\U0001F000-\U0001FFFF\u2600-\u27BF\uFE0F]", "", str(text)).strip()

    def write(text: str, size: int, style: str = "", height: float = 6, color=(0, 0, 0)) -> None:
        pdf.set_font(family, style if style != "B" else bold, size)
        pdf.set_text_color(*color)
        pdf.multi_cell(0, height, clean(strip_emoji(text)), new_x="LMARGIN", new_y="NEXT")

    for kind, content in blocks:
        if kind == "title":
            write(content, 18, "B", 10)
        elif kind == "meta":
            write(content, 9, color=(110, 110, 110))
            pdf.ln(4)
        elif kind == "h1":
            pdf.ln(4)
            write(content, 16, "B", 9, (20, 60, 120))
        elif kind == "h2":
            pdf.ln(3)
            write(content, 13, "B", 8, (20, 60, 120))
        elif kind == "h3":
            pdf.ln(2)
            write(content, 11, "B", 7)
        elif kind == "h4":
            write(content, 10, "B", 6, (60, 60, 60))
        elif kind == "p":
            plain = re.sub(r"[*_`#>]", "", str(content))
            write(plain, 10, height=5)
            pdf.ln(1)
        elif kind == "bullet":
            write(f"• {content}" if font_path else f"- {content}", 10, height=5)
        elif kind == "formula":
            f = content
            write(f["name"], 10, "B", 5)
            write(f["latex"], 9, height=5, color=(90, 30, 30))
            if f.get("explanation"):
                write(f["explanation"], 9, height=5, color=(90, 90, 90))
            pdf.ln(1)
        elif kind == "qa":
            q, a = content
            write(f"F: {q}", 10, "B", 5)
            write(f"A: {a}", 10, height=5)
            pdf.ln(1)
    return bytes(pdf.output())


# ---------------------------------------------------------------------------
# Backup
# ---------------------------------------------------------------------------

def backup_zip() -> bytes:
    cloud_sync.fetch_all()  # Unterlagen, die bisher nur im Cloud-Speicher liegen, mit sichern
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in DATA_DIR.rglob("*"):
            if path.is_file() and not path.name.startswith(".tmp-"):
                zf.write(path, path.relative_to(DATA_DIR).as_posix())
    return buffer.getvalue()


def restore_zip(content: bytes) -> int:
    """Stellt ein Backup wieder her. Nur Pfade innerhalb von data/ werden akzeptiert."""
    restored = 0
    data_root = DATA_DIR.resolve()
    with zipfile.ZipFile(io.BytesIO(content)) as zf:
        names = [i for i in zf.infolist() if not i.is_dir()]
        if not any(i.filename in ("settings.json",) or i.filename.startswith("modules/") for i in names):
            raise ValueError("Das ZIP sieht nicht wie ein Backup dieser App aus.")
        for info in names:
            rel = PurePosixPath(info.filename)
            if rel.is_absolute() or ".." in rel.parts:
                continue
            target = (DATA_DIR / Path(*rel.parts)).resolve()
            if data_root not in target.parents:
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(zf.read(info))
            cloud_sync.notify_changed(target)
            restored += 1
    return restored

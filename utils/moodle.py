"""Moodle-Anbindung über die offizielle Web-Service-Schnittstelle (dieselbe, die auch die Moodle-App nutzt).

Benötigt den persönlichen Sicherheitsschlüssel aus Moodle („Einstellungen → Sicherheitsschlüssel“,
Dienst „Moodle mobile web service“). Der Schlüssel wird nur aus den Secrets bzw. der .env gelesen
(MOODLE_TOKEN, optional MOODLE_URL) und niemals im Code oder in data/ gespeichert.
"""

from __future__ import annotations

import re
from datetime import date

import requests

from utils.config import get_secret

DEFAULT_URL = "https://moodle.lmu.de"
MAX_FILE_BYTES = 150 * 1024 * 1024

_ERRORS = {
    "invalidtoken": "Der Moodle-Sicherheitsschlüssel ist ungültig oder abgelaufen. Bitte in Moodle einen neuen "
                    "Schlüssel erzeugen und in den Secrets als MOODLE_TOKEN eintragen.",
    "accessexception": "Moodle verweigert den Zugriff mit diesem Schlüssel. Bitte prüfen, ob es der Schlüssel "
                       "für „Moodle mobile web service“ ist.",
    "servicenotavailable": "Die Moodle-Schnittstelle ist für diesen Schlüssel nicht freigeschaltet.",
    "webservicesnotenabled": "Die LMU hat die Moodle-Schnittstelle nicht freigegeben.",
}

_MONTHS = {
    "januar": 1, "jan": 1, "februar": 2, "feb": 2, "märz": 3, "maerz": 3, "mär": 3, "april": 4, "apr": 4,
    "mai": 5, "juni": 6, "jun": 6, "juli": 7, "jul": 7, "august": 8, "aug": 8, "september": 9, "sep": 9,
    "oktober": 10, "okt": 10, "november": 11, "nov": 11, "dezember": 12, "dez": 12,
}


class MoodleError(Exception):
    """Verständliche Fehlermeldung für die Oberfläche."""


def is_configured() -> bool:
    return bool(get_secret("MOODLE_TOKEN"))


class MoodleClient:
    def __init__(self, token: str | None = None, base_url: str | None = None):
        self.token = token or get_secret("MOODLE_TOKEN")
        self.base_url = (base_url or get_secret("MOODLE_URL") or DEFAULT_URL).rstrip("/")
        if not self.token:
            raise MoodleError("Kein Moodle-Sicherheitsschlüssel hinterlegt (MOODLE_TOKEN).")
        self.session = requests.Session()

    def call(self, function: str, **params):
        data = {"wstoken": self.token, "wsfunction": function, "moodlewsrestformat": "json"}
        for key, value in params.items():
            data[key] = value
        try:
            resp = self.session.post(f"{self.base_url}/webservice/rest/server.php", data=data, timeout=60)
        except requests.RequestException as exc:
            raise MoodleError(f"Keine Verbindung zu Moodle: {exc}") from exc
        if not resp.ok:
            raise MoodleError(f"Moodle antwortet mit Fehler {resp.status_code}.")
        try:
            result = resp.json()
        except ValueError as exc:
            raise MoodleError("Moodle hat keine gültige Antwort geliefert (Schnittstelle evtl. gesperrt).") from exc
        if isinstance(result, dict) and result.get("exception"):
            code = result.get("errorcode", "")
            raise MoodleError(_ERRORS.get(code, f"Moodle-Fehler: {result.get('message', code)}"))
        return result

    def site_info(self) -> dict:
        return self.call("core_webservice_get_site_info")

    def courses(self) -> list[dict]:
        user_id = self.site_info()["userid"]
        result = self.call("core_enrol_get_users_courses", userid=user_id)
        return [{"id": c["id"], "fullname": c.get("fullname", ""), "shortname": c.get("shortname", "")}
                for c in result]

    def course_pdfs(self, course_id: int) -> list[dict]:
        """Alle PDF-Dateien eines Kurses mit Abschnitt, Aktivitätsname und Änderungsdatum."""
        files = []
        for section in self.call("core_course_get_contents", courseid=course_id):
            section_name = re.sub(r"<[^>]+>", "", section.get("name", "")).strip()
            for module in section.get("modules", []):
                if module.get("modname") not in ("resource", "folder"):
                    continue
                for content in module.get("contents", []) or []:
                    name = content.get("filename", "")
                    if content.get("type") != "file" or not name.lower().endswith(".pdf"):
                        continue
                    files.append({
                        "course_id": course_id,
                        "section": section_name,
                        "title": module.get("name", name),
                        "filename": name,
                        "fileurl": content.get("fileurl", ""),
                        "filesize": content.get("filesize", 0),
                        "timemodified": content.get("timemodified", 0),
                        "key": f"{course_id}:{module.get('id')}:{name}:{content.get('timemodified', 0)}",
                    })
        return files

    def download(self, file: dict) -> bytes:
        if file.get("filesize", 0) > MAX_FILE_BYTES:
            raise MoodleError(f"{file['filename']} ist zu groß für den Import.")
        try:
            resp = self.session.get(file["fileurl"], params={"token": self.token}, timeout=120)
        except requests.RequestException as exc:
            raise MoodleError(f"Download fehlgeschlagen: {exc}") from exc
        content_type = resp.headers.get("Content-Type", "")
        if not resp.ok or "json" in content_type or not resp.content.startswith(b"%PDF"):
            raise MoodleError(f"{file['filename']} ist (noch) nicht verfügbar – evtl. erst ab einem späteren Datum.")
        return resp.content


_GENERIC = {"grundlagen", "einführung", "wise", "wintersemester", "sose", "sommersemester", "für", "fuer", "und",
            "der", "die", "das", "wirtschaftswissenschaftler", "vorlesung", "übung", "kurs"}


def _course_score(module_cfg: dict, title: str) -> int:
    title = title.lower()
    words = {w for w in re.findall(r"[a-zäöüß]{4,}", module_cfg["name"].lower()) if w not in _GENERIC}
    score = sum(3 for w in words if w in title)
    score += sum(2 for k in module_cfg.get("keywords", []) if len(k) > 3 and k.lower() not in _GENERIC
                 and k.lower() in title)
    return score


def match_courses(modules: list[dict], courses: list[dict]) -> dict[str, int]:
    """Ordnet jedem Fach höchstens einen Moodle-Kurs zu (jeder Kurs nur einmal, beste Treffer zuerst)."""
    pairs = sorted(((_course_score(m, c["fullname"]), m["id"], c["id"]) for m in modules for c in courses),
                   reverse=True)
    result: dict[str, int] = {}
    used: set[int] = set()
    for score, module_id, course_id in pairs:
        if score < 2 or module_id in result or course_id in used:
            continue
        result[module_id] = course_id
        used.add(course_id)
    return result


def section_date(section_name: str, semester_start: date) -> date | None:
    """Liest „12. Oktober - 18. Oktober“ → Datum des Abschnittsbeginns."""
    match = re.search(r"(\d{1,2})\.\s*([A-Za-zÄÖÜäöü]+)", section_name)
    if not match:
        return None
    month = _MONTHS.get(match.group(2).lower().rstrip("."))
    if not month:
        return None
    year = semester_start.year if month >= semester_start.month - 1 else semester_start.year + 1
    try:
        return date(year, month, int(match.group(1)))
    except ValueError:
        return None

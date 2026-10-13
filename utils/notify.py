"""Push-Erinnerungen aufs Handy über ntfy (kostenlose App „ntfy“ für iPhone/Android, kein Konto nötig).

Die App plant beim Öffnen die Erinnerungen der nächsten 3 Tage beim ntfy-Server ein (ntfy erlaubt
maximal 3 Tage im Voraus). Der Server schickt sie dann zur gewünschten Uhrzeit – auch wenn die App zu ist.
"""

from __future__ import annotations

import secrets
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import requests

from utils import spaced_repetition as sr
from utils.config import get_module
from utils.storage import load_module, load_settings, save_settings

NTFY_SERVER = "https://ntfy.sh"
TZ = ZoneInfo("Europe/Berlin")
DEFAULTS = {"enabled": False, "topic": "", "time": "18:00", "scheduled": {}}


def settings() -> dict:
    data = load_settings().setdefault("notify", {})
    for key, value in DEFAULTS.items():
        data.setdefault(key, value if not isinstance(value, dict) else {})
    if not data["topic"]:
        data["topic"] = f"bwl-lernen-{secrets.token_hex(6)}"
        save_settings()
    return data


def send(topic: str, title: str, message: str, at: datetime | None = None, tags: list[str] | None = None) -> None:
    payload = {"topic": topic, "title": title, "message": message, "tags": tags or ["books"], "priority": 3}
    if at is not None:
        payload["delay"] = str(int(at.timestamp()))
    response = requests.post(NTFY_SERVER, json=payload, timeout=10)
    response.raise_for_status()


def reminder_text(cfg: dict, day: date) -> str | None:
    """Text der Erinnerung für einen Tag: fällige Karteikarten pro Modul (None = nichts fällig)."""
    parts, total = [], 0
    for module in cfg["modules"]:
        cards = load_module(module["id"])["cards"]
        due = sum(1 for c in cards if sr.is_due(c, day))
        if due:
            parts.append(f"{get_module(cfg, module['id'])['short']} {due}")
            total += due
    if not total:
        return None
    return f"Etwa {total} Karteikarten warten auf dich: " + " · ".join(parts) + ". 15 Minuten reichen schon!"


def ensure_scheduled(cfg: dict, today: date) -> str | None:
    """Plant fehlende Erinnerungen für heute bis übermorgen ein. Gibt eine Fehlermeldung zurück oder None."""
    conf = settings()
    if not conf["enabled"]:
        return None
    hour, minute = (int(x) for x in conf["time"].split(":"))
    now = datetime.now(TZ)
    changed = False
    for offset in range(3):
        day = today + timedelta(days=offset)
        key = day.isoformat()
        when = datetime.combine(day, time(hour, minute), tzinfo=TZ)
        if key in conf["scheduled"] or when <= now + timedelta(minutes=1):
            continue
        text = reminder_text(cfg, day)
        if not text:
            continue  # (noch) nichts fällig – beim nächsten Öffnen erneut prüfen
        try:
            send(conf["topic"], "Zeit für Spaced Repetition", text, at=when)
        except requests.RequestException as exc:
            return f"Erinnerungen konnten nicht eingeplant werden: {exc}"
        conf["scheduled"][key] = True
        changed = True
    for key in [k for k in conf["scheduled"] if k < (today - timedelta(days=7)).isoformat()]:
        del conf["scheduled"][key]
        changed = True
    if changed:
        save_settings()
    return None

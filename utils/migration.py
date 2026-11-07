"""Umstellung auf das neue Lernsystem (Vorlesungs-Check + Wochentraining) – ohne Datenverlust.

Ablauf pro Modul (läuft genau einmal, erkennbar an learning_version = 2):
1. Backup: alle Lerndaten (Modul-JSONs, settings.json, todos.json, extra/*.json) unverändert nach
   data/backups/vor-lernsystem-2_<Zeitpunkt>/ kopieren (wird wie alles andere in den Cloud-Speicher gespiegelt).
2. Prüfwerte der Karteikarten merken (Anzahl, Verlaufseinträge, Prüfsumme).
3. NUR neue Felder ergänzen – die Karten selbst bleiben Byte für Byte, wo sie sind; die Markierung
   cards_archived sorgt dafür, dass sie nur noch unter Einstellungen → Ausgeblendet erscheinen.
4. Gegenprobe: stimmen die Prüfwerte nicht, wird nichts gespeichert und das Modul bleibt im alten Zustand.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime

from utils import cloud_sync, storage

VERSION = 2
BACKUP_PREFIX = "vor-lernsystem-2_"


class MigrationError(Exception):
    pass


def fingerprint(cards: list[dict]) -> dict:
    raw = json.dumps(cards, sort_keys=True, ensure_ascii=False, default=str).encode()
    return {"count": len(cards), "history": sum(len(c.get("history") or []) for c in cards),
            "sha256": hashlib.sha256(raw).hexdigest()}


def needs_migration(data: dict) -> bool:
    return int(data.get("learning_version", 1)) < VERSION


def backup_dir_name(now: datetime | None = None) -> str:
    return BACKUP_PREFIX + (now or datetime.now()).strftime("%Y-%m-%d_%H-%M-%S")


def make_backup(name: str | None = None) -> str:
    """Kopiert alle Lerndaten-Dateien (ohne PDFs/Bilder, die unverändert bleiben) in einen Backup-Ordner.
    Gibt den Ordner relativ zu data/ zurück."""
    name = name or backup_dir_name()
    target = storage.DATA_DIR / "backups" / name
    files = []
    for path in storage.DATA_DIR.rglob("*.json"):
        rel = path.relative_to(storage.DATA_DIR)
        if rel.parts[0] in ("backups", "texts") or path.name.startswith(".tmp-"):
            continue
        files.append((path, rel))
    for path, rel in files:
        dest = target / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, dest)
        cloud_sync.notify_changed(dest)
    marker = target / "INFO.json"
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(json.dumps({"created_at": storage.now_iso(), "files": [r.as_posix() for _, r in files],
                                  "reason": "Backup vor der Umstellung auf Vorlesungs-Check und Wochentraining"},
                                 ensure_ascii=False, indent=2), encoding="utf-8")
    cloud_sync.notify_changed(marker)
    return f"backups/{name}"


def migrate_data(data: dict, backup: str, held_reviewed: list[str]) -> dict:
    """Ergänzt nur neue Felder (in-place). held_reviewed = Vorlesungen, die vor der Umstellung schon
    nachbereitet waren (für sie gibt es keinen Vorlesungs-Check als To-do)."""
    before = fingerprint(data.get("cards", []))
    data.setdefault("cards", [])
    data["cards_archived"] = {"at": storage.now_iso(), "count": before["count"], "history": before["history"],
                              "sha256": before["sha256"], "backup": backup}
    data.setdefault("topics", {})
    data.setdefault("mastery", {})
    data.setdefault("questions", [])
    data.setdefault("sessions", [])
    data.setdefault("archive_map", {})
    data["legacy_lectures"] = sorted(set(data.get("legacy_lectures", [])) | set(held_reviewed))
    after = fingerprint(data["cards"])
    if after != before:
        raise MigrationError("Prüfwerte der Karteikarten stimmen nicht überein.")
    data["learning_version"] = VERSION
    return data


def ensure_all(cfg: dict) -> list[str]:
    """Migriert alle Module, die es noch brauchen. Gibt Fehlermeldungen zurück (leer = alles gut)."""
    from utils import planner, units
    from utils.config import get_module

    pending = [m["id"] for m in cfg["modules"] if needs_migration(storage.load_module(m["id"]))]
    if not pending:
        return []
    backup = make_backup()
    state = storage.load_todos()
    errors = []
    for module_id in pending:
        data = storage.load_module(module_id)
        snapshot = json.loads(json.dumps(data, default=str))
        try:
            lecs, _ = units.all_units(cfg, get_module(cfg, module_id), data)
            reviewed = [lec["id"] for lec in lecs
                        if state.get(planner.lecture_key(module_id, lec["date"], "nachbereitet"))]
            migrate_data(data, backup, reviewed)
        except Exception as exc:  # noqa: BLE001 – nie halb migriert speichern
            data.clear()
            data.update(snapshot)
            errors.append(f"{module_id}: Umstellung abgebrochen ({exc}). Deine Daten sind unverändert; "
                          f"Backup unter data/{backup}.")
            continue
        storage.save_module(module_id)
    return errors

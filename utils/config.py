"""Laden der Modul-Konfiguration aus config.json."""

from __future__ import annotations

import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = BASE_DIR / "config.json"

WEEKDAYS = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]
WEEKDAYS_SHORT = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]


def load_config() -> dict:
    """Liest config.json bei jedem Aufruf neu ein (Änderungen wirken sofort)."""
    with CONFIG_PATH.open(encoding="utf-8") as f:
        cfg = json.load(f)
    cfg.setdefault("modules", [])
    cfg.setdefault("document_types", {"sonstiges": "Sonstiges"})
    for module in cfg["modules"]:
        module.setdefault("icon", "📘")
        module.setdefault("short", module["name"][:12])
        module.setdefault("color", "#1f77b4")
        module.setdefault("keywords", [])
        module.setdefault("schedule", [])
        module.setdefault("chapters", [])
        module.setdefault("base_formulas", [])
    return cfg


def module_ids(cfg: dict) -> list[str]:
    return [m["id"] for m in cfg["modules"]]


def get_module(cfg: dict, module_id: str) -> dict:
    for module in cfg["modules"]:
        if module["id"] == module_id:
            return module
    raise KeyError(f"Unbekanntes Modul: {module_id}")


def module_label(cfg: dict, module_id: str, short: bool = False) -> str:
    module = get_module(cfg, module_id)
    return f"{module['icon']} {module['short'] if short else module['name']}"

"""Laden der Modul-Konfiguration aus config.json."""

from __future__ import annotations

import json
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = BASE_DIR / "config.json"

load_dotenv(BASE_DIR / ".env")

WEEKDAYS = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]
WEEKDAYS_SHORT = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]


def get_secret(name: str) -> str | None:
    """Liest einen geheimen Wert: zuerst aus der .env/Umgebung, sonst aus den Streamlit-Secrets (Cloud)."""
    value = os.getenv(name, "").strip()
    if value:
        return value
    try:
        import streamlit as st

        value = st.secrets.get(name)
    except Exception:  # noqa: BLE001 - keine secrets.toml vorhanden
        return None
    return str(value).strip() if value else None


def load_config() -> dict:
    """Liest config.json bei jedem Aufruf neu ein (Änderungen wirken sofort)."""
    with CONFIG_PATH.open(encoding="utf-8") as f:
        cfg = json.load(f)
    cfg.setdefault("modules", [])
    cfg.setdefault("document_types", {"sonstiges": "Sonstiges"})
    for module in cfg["modules"]:
        module.setdefault("icon", "")
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
    return f"{module['short'] if short else module['name']}"

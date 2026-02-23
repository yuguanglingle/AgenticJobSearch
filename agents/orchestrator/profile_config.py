"""Profile and project configuration helpers."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional


ROOT_DIR = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT_DIR / "config"
PROFILES_DIR = CONFIG_DIR / "profiles"
PROJECT_CONFIG_PATH = CONFIG_DIR / "project.json"
AGENTS_DIR = ROOT_DIR / "agents"


def list_profiles() -> list[str]:
    if not PROFILES_DIR.exists():
        return []
    return sorted(path.stem for path in PROFILES_DIR.glob("*.json"))


def load_project_config() -> dict:
    if not PROJECT_CONFIG_PATH.exists():
        return {}
    try:
        return json.loads(PROJECT_CONFIG_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def save_project_config(config: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    PROJECT_CONFIG_PATH.write_text(json.dumps(config, indent=2), encoding="utf-8")


def get_default_profile() -> Optional[str]:
    config = load_project_config()
    value = config.get("default_profile")
    return value if isinstance(value, str) and value.strip() else None


def set_default_profile(profile_name: str) -> None:
    save_project_config({"default_profile": profile_name})


def profile_config_path(profile_name: str) -> Path:
    return PROFILES_DIR / f"{profile_name}.json"


def load_profile_config(profile_name: str) -> dict:
    path = profile_config_path(profile_name)
    if not path.exists():
        raise FileNotFoundError(f"Profile config not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def save_profile_config(profile_name: str, config: dict) -> None:
    PROFILES_DIR.mkdir(parents=True, exist_ok=True)
    path = profile_config_path(profile_name)
    path.write_text(json.dumps(config, indent=2), encoding="utf-8")


def resolve_db_path(profile_name: str, profile_config: dict) -> Path:
    db_path = profile_config.get("db_path")
    if not db_path:
        db_path = profile_config.get("storage", {}).get("db_path")
    if not db_path:
        if profile_name == "default":
            db_path = str(AGENTS_DIR / "data" / "app.db")
        else:
            db_path = str(AGENTS_DIR / "data" / f"jobs_{profile_name}.db")
    return Path(db_path).expanduser().resolve()


def resolve_logs_dir(profile_name: str, profile_config: dict) -> Path:
    logs_dir = profile_config.get("logs_dir")
    if not logs_dir:
        logs_dir = str(ROOT_DIR / "logs" / profile_name)
    return Path(logs_dir).expanduser().resolve()


def apply_profile_env(profile_name: str, profile_config: dict) -> tuple[Path, Path]:
    db_path = resolve_db_path(profile_name, profile_config)
    logs_dir = resolve_logs_dir(profile_name, profile_config)
    os.environ["DB_PATH"] = str(db_path)
    os.environ["LOG_DIR"] = str(logs_dir)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)
    return db_path, logs_dir

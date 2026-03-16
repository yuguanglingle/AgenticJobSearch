"""Shared runtime helpers for app CLI and UI."""

from __future__ import annotations

import io
import json
import os
import sys
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parents[1]
AGENTS_DIR = ROOT_DIR / "agents"
if str(AGENTS_DIR) not in sys.path:
    sys.path.insert(0, str(AGENTS_DIR))

from candidate_profile.src import db as candidate_db
from job_search.job_search_client import DEFAULT_CONFIG
from orchestrator import pipeline
from orchestrator.profile_config import apply_profile_env, load_profile_config, profile_config_path

ENV_PATH = ROOT_DIR / ".env"


class _Tee(io.TextIOBase):
    def __init__(self, *streams):
        self._streams = streams

    def write(self, text: str) -> int:
        for stream in self._streams:
            stream.write(text)
            stream.flush()
        return len(text)

    def flush(self) -> None:
        for stream in self._streams:
            stream.flush()


def _resolve_profile_config(profile_name: str) -> dict:
    path = profile_config_path(profile_name)
    if not path.exists() and profile_name == "default":
        return {}
    return load_profile_config(profile_name)


def _resolve_candidate_id(profile_config: dict, candidate_override: Optional[str]) -> Optional[str]:
    if candidate_override:
        return candidate_override
    candidate_id = profile_config.get("candidate_id")
    if candidate_id:
        return str(candidate_id)
    candidates = candidate_db.list_candidates()
    return candidates[0].id if candidates else None


def _resolve_provider_config(profile_config: dict) -> dict:
    provider_config = profile_config.get("provider_config")
    if provider_config:
        return provider_config
    if "providers" in profile_config:
        return {"providers": profile_config.get("providers", [])}
    return DEFAULT_CONFIG


def run_pipeline_command(
    *,
    command_name: str,
    profile_name: str,
    candidate_id: Optional[str] = None,
    limit_to_score: Optional[int] = None,
) -> dict:
    """Run the daily orchestrator pipeline with per-run logging."""
    load_dotenv(ENV_PATH)

    profile_config = _resolve_profile_config(profile_name)
    db_path, logs_dir = apply_profile_env(profile_name, profile_config)
    effective_candidate = _resolve_candidate_id(profile_config, candidate_id)
    if not effective_candidate:
        raise ValueError(
            "No candidate found. Create a candidate in Streamlit first or set candidate_id in profile config."
        )

    provider_config = _resolve_provider_config(profile_config)
    effective_limit = int(profile_config.get("limit_to_score", 50))
    if limit_to_score is not None:
        effective_limit = max(0, int(limit_to_score))

    logs_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = logs_dir / f"{command_name}_{timestamp}.log"

    with open(log_path, "a", encoding="utf-8") as handle:
        tee_out = _Tee(sys.stdout, handle)
        tee_err = _Tee(sys.stderr, handle)
        with redirect_stdout(tee_out), redirect_stderr(tee_err):
            print(
                f"[app] command={command_name} profile={profile_name} "
                f"candidate_id={effective_candidate} limit_to_score={effective_limit}"
            )
            print(f"[app] DB_PATH={db_path}")
            print(f"[app] LOG_DIR={logs_dir}")
            stats = pipeline.run_daily(
                candidate_id=effective_candidate,
                provider_config=provider_config,
                limit_to_score=effective_limit,
            )
            print(f"[app] completed stats={json.dumps(stats, ensure_ascii=True)}")

    return {
        "command": command_name,
        "profile": profile_name,
        "candidate_id": effective_candidate,
        "limit_to_score": effective_limit,
        "db_path": str(db_path),
        "log_file": str(log_path),
        "stats": stats,
    }

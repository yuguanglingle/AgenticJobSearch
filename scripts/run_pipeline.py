"""CLI entrypoint for running the daily pipeline with optional profiles."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parents[1]
AGENTS_DIR = ROOT_DIR / "agents"
if str(AGENTS_DIR) not in sys.path:
    sys.path.insert(0, str(AGENTS_DIR))

from job_search.job_search_client import DEFAULT_CONFIG
from orchestrator import pipeline

load_dotenv()


def _profile_config_path(profile_name: str) -> Path:
    return ROOT_DIR / "config" / "profiles" / f"{profile_name}.json"


def _load_profile_config(profile_name: str) -> dict:
    config_path = _profile_config_path(profile_name)
    if not config_path.exists():
        raise FileNotFoundError(
            f"Profile config not found: {config_path}. "
            "Create config/profiles/<name>.json to use --profile."
        )
    return json.loads(config_path.read_text(encoding="utf-8"))


def _resolve_db_path(profile_name: str, profile_config: dict) -> Path:
    db_path = profile_config.get("db_path")
    if not db_path:
        db_path = profile_config.get("storage", {}).get("db_path")
    if not db_path:
        db_path = str(ROOT_DIR / "storage" / profile_name / "app.db")
    return Path(db_path).expanduser().resolve()


def _resolve_logs_dir(profile_name: str, profile_config: dict) -> Path:
    logs_dir = profile_config.get("logs_dir")
    if not logs_dir:
        logs_dir = str(ROOT_DIR / "logs" / profile_name)
    return Path(logs_dir).expanduser().resolve()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the daily pipeline.")
    parser.add_argument("--profile", help="Profile name (loads config/profiles/<name>.json).")
    parser.add_argument("--candidate-id", help="Override candidate id.")
    parser.add_argument("--limit", type=int, help="Override limit_to_score.")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()

    provider_config = DEFAULT_CONFIG
    limit_to_score = 50
    candidate_id = args.candidate_id

    if args.profile:
        profile_config = _load_profile_config(args.profile)
        db_path = _resolve_db_path(args.profile, profile_config)
        logs_dir = _resolve_logs_dir(args.profile, profile_config)
        os.environ["DB_PATH"] = str(db_path)
        os.environ["LOG_DIR"] = str(logs_dir)
        os.makedirs(db_path.parent, exist_ok=True)
        os.makedirs(logs_dir, exist_ok=True)

        provider_config = profile_config.get("provider_config") or DEFAULT_CONFIG
        limit_to_score = profile_config.get("limit_to_score", limit_to_score)
        candidate_id = candidate_id or profile_config.get("candidate_id")

        print(f"[cli] profile={args.profile} db_path={db_path}")
        print(f"[cli] profile={args.profile} logs_dir={logs_dir}")

    if args.limit is not None:
        limit_to_score = args.limit

    if not candidate_id:
        print("Missing candidate id. Provide --candidate-id or set candidate_id in the profile config.")
        return 2

    stats = pipeline.run_daily(
        candidate_id=candidate_id,
        provider_config=provider_config,
        limit_to_score=limit_to_score,
    )
    print(stats)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

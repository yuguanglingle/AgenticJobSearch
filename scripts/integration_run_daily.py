"""Run a small end-to-end daily pipeline integration test."""

from __future__ import annotations

import argparse
import ast
import json
import os
import sys
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from dotenv import load_dotenv

AGENTS_DIR = Path(__file__).resolve().parents[1] / "agents"
if str(AGENTS_DIR) not in sys.path:
    sys.path.insert(0, str(AGENTS_DIR))

from candidate_profile.src import db as candidate_db
from job_search.job_search_client import DEFAULT_CONFIG
from orchestrator import pipeline

load_dotenv()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ensure_candidate_id(sample_profile_path: Path | None = None) -> str:
    candidates = candidate_db.list_candidates()
    if candidates:
        return candidates[0].id

    candidate_id = str(uuid4())
    now = _now_iso()
    if sample_profile_path and sample_profile_path.exists():
        profile_json = json.loads(sample_profile_path.read_text(encoding="utf-8"))
        candidate_profile_json = json.dumps(profile_json)
    else:
        candidate_profile_json = (
            "{"
            '"ok": true,'
            '"agent": "CandidateProfileAgent",'
            f'"run_id": "{uuid4()}",'
            f'"timestamp": "{now}",'
            '"result": {"candidate_profile": {'
            '"headline": "Sample candidate",'
            '"seniority_estimate": "mid",'
            '"core_skills": ["python", "sql"],'
            '"domains": ["data"],'
            '"experience_highlights": [],'
            '"keywords_for_search": ["python", "sql"],'
            '"tone_style": {"voice": "direct", "length": "short"}'
            "}},"
            '"confidence": 0.5,'
            '"evidence": [],'
            '"next_actions": [],'
            '"questions_for_user": []'
            "}"
        )
    candidate_db.save_candidate(
        candidate_id=candidate_id,
        resume_raw="Sample resume for integration run.",
        candidate_profile_json=candidate_profile_json,
        llm_model="integration",
        prompt_version="integration",
        created_at=now,
        updated_at=now,
        preferences={
            "locations": ["Remote"],
            "remote_preference": "remote",
            "role_targets": ["Engineer"],
            "industries": ["Tech"],
            "dealbreakers": [],
            "comp_min": 120000,
            "work_auth": "US",
        },
    )
    return candidate_id


def _load_sample_batch(sample_jobs_path: Path, limit: int) -> dict:
    raw_text = sample_jobs_path.read_text(encoding="utf-8")
    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError:
        payload = ast.literal_eval(raw_text)

    jobs = payload.get("data", [])[:limit]
    for job in jobs:
        job.setdefault("source", "theirstack")

    now = _now_iso()
    return {
        "retrieval_batch": {
            "batch_id": f"sample-{uuid4()}",
            "started_at": now,
            "finished_at": now,
        },
        "jobs": jobs,
        "stats": {"sources_checked": 1, "jobs_fetched": len(jobs)},
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mock", action="store_true", help="Use sample candidate + jobs.")
    parser.add_argument("--limit", type=int, default=2, help="Limit number of jobs.")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    os.environ.setdefault("DB_PATH", str((AGENTS_DIR / "data" / "app.db").resolve()))
    sample_profile_path = AGENTS_DIR / "candidate_profile" / "samples" / "sample_profile.json"
    candidate_id = _ensure_candidate_id(sample_profile_path if args.mock else None)

    if args.mock:
        sample_jobs_path = AGENTS_DIR / "job_search" / "sample_theirstack_response.json"
        batch = _load_sample_batch(sample_jobs_path, limit=max(1, args.limit))
        stats = pipeline.run_daily_from_batch(
            candidate_id=candidate_id,
            batch_data=batch,
            limit_to_score=args.limit,
        )
        print(stats)
        return 0

    api_key = os.getenv("THEIRSTACK_API_KEY")
    if not api_key:
        print("Missing THEIRSTACK_API_KEY; set it to run integration.")
        return 1

    provider_config = deepcopy(DEFAULT_CONFIG)
    provider_config["providers"][0]["payload_overrides"] = {"limit": args.limit}

    stats = pipeline.run_daily(
        candidate_id=candidate_id,
        provider_config=provider_config,
        limit_to_score=args.limit,
    )
    print(stats)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

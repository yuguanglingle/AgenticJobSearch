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

ROOT_DIR = Path(__file__).resolve().parents[1]
AGENTS_DIR = ROOT_DIR / "agents"
SHARED_DB_PATH = (AGENTS_DIR / "data" / "app.db").resolve()
if str(AGENTS_DIR) not in sys.path:
    sys.path.insert(0, str(AGENTS_DIR))

from candidate_profile.src import db as candidate_db
from job_search import db as job_search_db
from job_search.job_search_client import DEFAULT_CONFIG
from orchestrator import pipeline
from sqlmodel import Session, select

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

    # Add a high-quality mock job that matches the sample candidate profile
    high_match_job = {
        "id": 999999999,
        "source": "mock",
        "job_title": "Senior Business Development Manager",
        "title": "Senior Business Development Manager",
        "company": "TechFlow Partners",
        "location": "San Francisco, CA",
        "remote": True,
        "hybrid": False,
        "job_description": """
Join TechFlow Partners as a Senior Business Development Manager leading our corporate strategy initiatives. 
We are seeking an experienced professional to drive Business Development and Corporate Strategy efforts across our enterprise platform.

Key Responsibilities:
- Lead strategic planning initiatives to identify new market opportunities
- Develop and execute corporate strategy for business expansion
- Build and manage relationships with key partners and stakeholders
- Analyze market trends and competitive landscape for strategic decision-making
- Drive business development efforts across multiple verticals

Required Experience:
- 5+ years in Business Development, Corporate Strategy, or Strategic Planning
- Proven track record building high-performing teams
- Experience with market analysis and strategic planning
- Strong understanding of enterprise software markets
- Ability to partner across organizations and navigate complex stakeholder landscapes

Why Join Us:
- Competitive compensation with equity upside
- Remote-friendly, collaborative culture
- Opportunity to shape company strategy
- Leadership role in a fast-growing organization
""",
        "description": """
Join TechFlow Partners as a Senior Business Development Manager leading our corporate strategy initiatives. 
We are seeking an experienced professional to drive Business Development and Corporate Strategy efforts across our enterprise platform.

Key Responsibilities:
- Lead strategic planning initiatives to identify new market opportunities
- Develop and execute corporate strategy for business expansion
- Build and manage relationships with key partners and stakeholders
- Analyze market trends and competitive landscape for strategic decision-making
- Drive business development efforts across multiple verticals

Required Experience:
- 5+ years in Business Development, Corporate Strategy, or Strategic Planning
- Proven track record building high-performing teams
- Experience with market analysis and strategic planning
- Strong understanding of enterprise software markets
- Ability to partner across organizations and navigate complex stakeholder landscapes

Why Join Us:
- Competitive compensation with equity upside
- Remote-friendly, collaborative culture
- Opportunity to shape company strategy
- Leadership role in a fast-growing organization
""",
        "seniority": "mid_level",
        "date_posted": datetime.now(timezone.utc).isoformat(),
        "discovered_at": datetime.now(timezone.utc).isoformat(),
        "employment_statuses": ["full_time"],
    }
    jobs.append(high_match_job)

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


def _load_existing_jobs(limit: int) -> list[dict]:
    db_path = job_search_db.get_db_path()
    engine = job_search_db.init_db(db_path)
    with Session(engine) as session:
        statement = select(job_search_db.Job).order_by(job_search_db.Job.created_at.desc()).limit(limit)
        jobs = session.exec(statement).all()
        return [
            {
                "source": job.source,
                "source_job_id": job.source_job_id,
                "job_title": job.job_title,
                "title": job.job_title,
                "company": job.company,
                "location": job.location,
                "description": job.description or job.description_text,
                "canonical_url": job.canonical_url,
                "dedupe_key_strong": job.dedupe_key_strong,
                "dedupe_key_soft": job.dedupe_key_soft,
                "description_hash": job.description_hash,
            }
            for job in jobs
        ]


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mock", action="store_true", help="Use sample candidate + jobs.")
    parser.add_argument("--sample", action="store_true", help="Force use of sample job payload (skip existing DB jobs).")
    parser.add_argument("--limit", type=int, default=2, help="Limit number of jobs.")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    # Ensure DB_PATH is set even if the environment variable is present but empty
    if not os.getenv("DB_PATH"):
        os.environ["DB_PATH"] = str(SHARED_DB_PATH)
    print(f"[integration] using DB_PATH={os.environ.get('DB_PATH')}")
    sample_profile_path = AGENTS_DIR / "candidate_profile" / "samples" / "sample_profile.json"
    candidate_id = _ensure_candidate_id(sample_profile_path if args.mock else None)

    if args.mock:
        print("[integration] running daily pipeline with mock data")
        existing_jobs = [] if args.sample else _load_existing_jobs(limit=max(1, args.limit))
        if existing_jobs and not args.sample:
            now = _now_iso()
            batch = {
                "retrieval_batch": {
                    "batch_id": f"existing-{uuid4()}",
                    "started_at": now,
                    "finished_at": now,
                },
                "jobs": existing_jobs,
                "stats": {"sources_checked": 1, "jobs_fetched": len(existing_jobs)},
            }
            print(f"[integration] using existing jobs from db count={len(existing_jobs)}")
        else:
            sample_jobs_path = AGENTS_DIR / "job_search" / "sample_theirstack_response.json"
            batch = _load_sample_batch(sample_jobs_path, limit=max(1, args.limit))
            print("[integration] using sample job payload")
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

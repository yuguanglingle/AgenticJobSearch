import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlmodel import select

BASE_DIR = Path(__file__).resolve().parents[1]
AGENTS_DIR = BASE_DIR.parent

if str(AGENTS_DIR) not in sys.path:
    sys.path.insert(0, str(AGENTS_DIR))

from candidate_profile.src import db as candidate_db
from job_match import db as job_match_db
from job_search import db as job_search_db
from orchestrator import pipeline, state as orchestrator_state


def _seed_candidate(candidate_id: str) -> None:
    candidate_db.save_candidate(
        candidate_id=candidate_id,
        resume_raw="Resume",
        candidate_profile_json=json.dumps(
            {
                "result": {
                    "candidate_profile": {
                        "keywords_for_search": ["python", "sql", "data"],
                        "core_skills": ["python", "sql"],
                        "domains": ["data"],
                    }
                }
            }
        ),
        llm_model="test-model",
        prompt_version="v1",
        created_at="2026-01-01T00:00:00Z",
        updated_at="2026-01-01T00:00:00Z",
        preferences={
            "locations": ["Remote"],
            "remote_preference": "remote",
            "role_targets": ["Engineer"],
            "industries": ["Tech"],
            "dealbreakers": [],
        },
    )


def _batch_payload() -> dict:
    return {
        "retrieval_batch": {
            "batch_id": "batch-pipeline-1",
            "started_at": "2026-01-01T00:00:00Z",
            "finished_at": "2026-01-01T01:00:00Z",
        },
        "jobs": [
            {
                "source": "theirstack",
                "source_job_id": "job-1",
                "title": "Python Data Engineer",
                "company": "Acme",
                "canonical_url": "https://example.com/jobs/1",
                "location": "Remote",
                "remote": True,
                "description": "Build data pipelines with Python and SQL.",
            },
            {
                "source": "theirstack",
                "source_job_id": "job-2",
                "title": "Data Analyst",
                "company": "Beta",
                "canonical_url": "https://example.com/jobs/2",
                "location": "Remote",
                "remote": True,
                "description": "Analyze data and build dashboards.",
            },
        ],
        "stats": {"sources_checked": 1, "jobs_fetched": 2},
    }


def _batch_payload_single() -> dict:
    return {
        "retrieval_batch": {
            "batch_id": "batch-single-1",
            "started_at": "2026-01-01T00:00:00Z",
            "finished_at": "2026-01-01T01:00:00Z",
        },
        "jobs": [
            {
                "source": "theirstack",
                "source_job_id": "job-1",
                "title": "Python Data Engineer",
                "company": "Acme",
                "canonical_url": "https://example.com/jobs/1",
                "location": "Remote",
                "remote": True,
                "description": "Build data pipelines with Python and SQL.",
            }
        ],
        "stats": {"sources_checked": 1, "jobs_fetched": 1},
    }


def _count_opportunities() -> int:
    db_path = job_match_db.get_db_path()
    engine = job_match_db.init_db(db_path)
    with job_match_db.Session(engine) as session:
        return len(session.exec(select(job_match_db.JobOpportunity)).all())


def _load_job(job_id: str):
    db_path = job_search_db.get_db_path()
    engine = job_search_db.init_db(db_path)
    with job_search_db.Session(engine) as session:
        return session.get(job_search_db.Job, job_id)


def _update_opportunity(opportunity_id: str, **updates) -> None:
    db_path = job_match_db.get_db_path()
    engine = job_match_db.init_db(db_path)
    with job_match_db.Session(engine) as session:
        opp = session.get(job_match_db.JobOpportunity, opportunity_id)
        for key, value in updates.items():
            setattr(opp, key, value)
        session.add(opp)
        session.commit()


def test_pipeline_twice_no_duplicate_opportunities(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = tmp_path / "test.db"
    monkeypatch.setenv("DB_PATH", str(db_path))
    candidate_id = "cand-1"
    _seed_candidate(candidate_id)
    batch = _batch_payload()

    stats_first = pipeline.run_daily_from_batch(
        candidate_id=candidate_id,
        batch_data=batch,
        limit_to_score=10,
    )
    assert _count_opportunities() == 2

    stats_second = pipeline.run_daily_from_batch(
        candidate_id=candidate_id,
        batch_data=batch,
        limit_to_score=10,
    )
    assert _count_opportunities() == 2
    assert stats_second["num_scored"] == 0
    assert stats_second["num_pre_ranked"] == 0


def test_skip_rescore_with_recent_same_description(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = tmp_path / "test.db"
    monkeypatch.setenv("DB_PATH", str(db_path))
    candidate_id = "cand-2"
    _seed_candidate(candidate_id)
    batch = _batch_payload_single()

    job_ids = job_search_db.save_retrieval_batch(batch)
    job_id = job_ids[0]
    job = _load_job(job_id)
    opp = orchestrator_state.get_or_create_opportunity(candidate_id, job_id)

    _update_opportunity(
        opp.id,
        last_scored_at=datetime.now(timezone.utc).isoformat(),
        last_scored_description_hash=job.description_hash,
    )

    stats = pipeline.run_daily_from_batch(
        candidate_id=candidate_id,
        batch_data=batch,
        limit_to_score=10,
    )
    assert stats["num_scored"] == 0

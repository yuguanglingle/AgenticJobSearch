"""Integration tests for the full pipeline flow."""

import json
import sys
from pathlib import Path

from sqlmodel import Session, select

BASE_DIR = Path(__file__).resolve().parents[1]
AGENTS_DIR = BASE_DIR / "agents"
if str(AGENTS_DIR) not in sys.path:
    sys.path.insert(0, str(AGENTS_DIR))

from candidate_profile.src import db as candidate_db
from job_match import db as job_match_db
from orchestrator import pipeline
from orchestrator import state as orchestrator_state


def _seed_candidate(candidate_id: str = "cand-integration-1") -> str:
    candidate_db.save_candidate(
        candidate_id=candidate_id,
        resume_raw="Resume text",
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
            "comp_min": 120000,
            "work_auth": "US",
        },
    )
    return candidate_id


def _batch_payload() -> dict:
    jobs = []
    for i in range(5):
        jobs.append(
            {
                "source": "theirstack",
                "source_job_id": f"high-{i}",
                "title": f"Python Data Engineer {i}",
                "company": "Acme",
                "canonical_url": f"https://example.com/jobs/high-{i}",
                "location": "Remote",
                "remote": True,
                "description": "Build data pipelines with Python and SQL.",
            }
        )
    for i in range(5):
        jobs.append(
            {
                "source": "theirstack",
                "source_job_id": f"low-{i}",
                "title": f"Account Executive {i}",
                "company": "Beta",
                "canonical_url": f"https://example.com/jobs/low-{i}",
                "location": "Onsite",
                "remote": False,
                "description": "Cold calling and outbound sales targets.",
            }
        )
    return {
        "retrieval_batch": {
            "batch_id": "batch-integration-1",
            "started_at": "2026-01-01T00:00:00Z",
            "finished_at": "2026-01-01T01:00:00Z",
        },
        "jobs": jobs,
        "stats": {"sources_checked": 1, "jobs_fetched": len(jobs)},
    }


def test_integration_flow_end_to_end() -> None:
    candidate_id = _seed_candidate()
    batch_data = _batch_payload()

    stats = pipeline.run_daily_from_batch(
        candidate_id=candidate_id,
        batch_data=batch_data,
        limit_to_score=10,
    )
    assert stats["num_pre_ranked"] == 10
    assert stats["num_scored"] == 10

    db_path = job_match_db.get_db_path()
    engine = job_match_db.init_db(db_path)
    with Session(engine) as session:
        stmt = select(job_match_db.JobOpportunity).where(
            job_match_db.JobOpportunity.candidate_id == candidate_id
        )
        opportunities = list(session.exec(stmt))

    assert len(opportunities) == 10
    assert all(opp.state == "SCREENED" for opp in opportunities)

    approved = orchestrator_state.approve(opportunities[0].id)
    assert approved.state == "APPROVED"

    applied = orchestrator_state.mark_applied(opportunities[0].id)
    assert applied.state == "APPLIED"

    with Session(engine) as session:
        stmt = select(job_match_db.Application).where(
            job_match_db.Application.candidate_id == candidate_id
        )
        applications = list(session.exec(stmt))
    assert len(applications) == 1

    pipeline.run_daily_from_batch(
        candidate_id=candidate_id,
        batch_data=batch_data,
        limit_to_score=10,
    )
    with Session(engine) as session:
        stmt = select(job_match_db.JobOpportunity).where(
            job_match_db.JobOpportunity.candidate_id == candidate_id
        )
        opportunities_after = list(session.exec(stmt))
    assert len(opportunities_after) == 10

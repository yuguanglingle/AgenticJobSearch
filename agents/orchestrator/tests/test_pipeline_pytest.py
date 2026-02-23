"""Pytest-friendly tests for the orchestrator pipeline.

This module is collected by pytest. It reuses the same test class and helpers
from the manual-run module but is structured for pytest discovery.
"""
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

BASE_DIR = Path(__file__).resolve().parents[1]
AGENTS_DIR = BASE_DIR.parent
if str(AGENTS_DIR) not in sys.path:
    sys.path.insert(0, str(AGENTS_DIR))

from candidate_profile.src import db as candidate_db
from job_match import db as job_match_db
from job_match.agent import evaluate_and_persist
from job_match.pre_ranker import compute_retrieval_score
from job_search import db as job_search_db
from orchestrator import pipeline
from orchestrator import state as orchestrator_state


def _load_job(job_id: str):
    """Load a job record by id.

    Args:
        job_id: Job primary key.

    Returns:
        Job record or None.
    """
    db_path = job_search_db.get_db_path()
    engine = job_search_db.init_db(db_path)
    with job_search_db.Session(engine) as session:
        return session.get(job_search_db.Job, job_id)


def json_dump(payload: dict) -> str:
    """Serialize a dict to JSON.

    Args:
        payload: Dict to serialize.

    Returns:
        JSON string.
    """
    return json.dumps(payload)


class OrchestratorPipelineTests:
    """A pytest-style wrapper that mirrors the unittest.TestCase behavior.

    We keep the tests as plain functions here so pytest can collect and run them.
    Each test sets up its own temp DB via environment `DB_PATH` to keep isolation.
    """

    def _seed_candidate(self):
        candidate_id = "cand-pipeline-1"
        candidate_db.save_candidate(
            candidate_id=candidate_id,
            resume_raw="Resume",
            candidate_profile_json=json_dump(
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
                "dealbreakers": ["clearance required"],
                "comp_min": 150000,
                "work_auth": "US",
            },
        )
        return candidate_id


def test_pre_ranker_high_match_triggers_llm(monkeypatch):
    candidate_id = OrchestratorPipelineTests()._seed_candidate()
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    batch = {
        "retrieval_batch": {"batch_id": "batch-high-match", "started_at": "2026-01-01T00:00:00Z", "finished_at": "2026-01-01T01:00:00Z"},
        "jobs": [
            {
                "source": "theirstack",
                "source_job_id": "high-match-1",
                "title": "Senior Python Engineer",
                "company": "TechCorp",
                "canonical_url": "https://techcorp.com/jobs/high",
                "location": "Remote",
                "remote": True,
                "description": (
                    "We are seeking a Senior Python Engineer with strong SQL and data engineering "
                    "skills to build and optimize our data pipelines. "
                    "Python is essential. SQL knowledge required. "
                    "This is a remote position focused on data infrastructure."
                ),
            }
        ],
        "stats": {"sources_checked": 1, "jobs_fetched": 1},
    }

    job_ids = job_search_db.save_retrieval_batch(batch)
    job_id = job_ids[0]
    job = _load_job(job_id)

    retrieval_score, _ = compute_retrieval_score(
        job_title=job.job_title,
        job_description=job.description or job.description_text,
        job_location=job.location,
        job_remote=job.remote,
        job_hybrid=job.hybrid,
        keywords=["python", "sql", "data"],
        dealbreakers=["clearance required"],
        preferred_locations=["Remote"],
        remote_preference="remote",
    )

    assert retrieval_score >= 0.25

    llm_called = {"called": False}

    class MockLLMClient:
        def __init__(self) -> None:
            self.model = "test-gpt-4"

        def generate(self, *args, **kwargs):
            llm_called["called"] = True
            return json.dumps(
                {
                    "overall_score": 75,
                    "decision": "strong_yes",
                    "top_reasons": ["Strong Python skills", "Remote available"],
                }
            )

    result = evaluate_and_persist(candidate_id, job_id, llm_client=MockLLMClient())

    assert llm_called["called"]
    assert result.used_llm
    assert result.overall_score > 50

"""Tests for JobFitAgent, pre-ranker, and state machine."""
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
AGENTS_DIR = BASE_DIR.parent
if str(AGENTS_DIR) not in sys.path:
    sys.path.insert(0, str(AGENTS_DIR))

from candidate_profile.src import db as candidate_db
from job_match import db as job_match_db
from job_match.agent import JobFitAgent, evaluate_and_persist
from job_match.state_machine import JobState
from job_search import db as job_search_db


class RaiseOnCallLLM:
    def __init__(self) -> None:
        """Initialize stub LLM client.

        Args:
            None.

        Returns:
            None.
        """
        self.model = "test-model"

    def generate(self, *args, **kwargs):
        """Raise to ensure LLM is not called.

        Args:
            *args: Positional args.
            **kwargs: Keyword args.

        Returns:
            None.
        """
        raise AssertionError("LLM should not be called.")


class JobMatchTests(unittest.TestCase):
    def setUp(self) -> None:
        """Create a temporary SQLite database for isolation.

        Args:
            None.

        Returns:
            None.
        """
        self._old_db_path = os.environ.get("DB_PATH")
        self._old_openai_key = os.environ.get("OPENAI_API_KEY")
        self._tmpdir = tempfile.TemporaryDirectory()
        self._db_path = str(Path(self._tmpdir.name) / "test.db")
        os.environ["DB_PATH"] = self._db_path

    def tearDown(self) -> None:
        """Restore environment variables and clean up temp files.

        Args:
            None.

        Returns:
            None.
        """
        if self._old_db_path is None:
            os.environ.pop("DB_PATH", None)
        else:
            os.environ["DB_PATH"] = self._old_db_path
        if self._old_openai_key is None:
            os.environ.pop("OPENAI_API_KEY", None)
        else:
            os.environ["OPENAI_API_KEY"] = self._old_openai_key
        try:
            self._tmpdir.cleanup()
        except PermissionError:
            pass

    def _seed_candidate(self) -> str:
        """Seed a candidate for tests.

        Args:
            None.

        Returns:
            Candidate id string.
        """
        candidate_id = "cand-1"
        candidate_db.save_candidate(
            candidate_id=candidate_id,
            resume_raw="Resume",
            candidate_profile_json=json_dump(
                {
                    "result": {
                        "candidate_profile": {
                            "keywords_for_search": ["engineer", "python"],
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

    def _seed_job(self, *, title: str, location: str, description: str, source_job_id: str) -> str:
        """Seed a job record for tests.

        Args:
            title: Job title.
            location: Job location.
            description: Job description.
            source_job_id: Source job id.

        Returns:
            Job id string.
        """
        batch = {
            "retrieval_batch": {
                "batch_id": "batch-1",
                "started_at": "2026-01-01T00:00:00Z",
                "finished_at": "2026-01-01T01:00:00Z",
            },
            "jobs": [
                {
                    "source": "theirstack",
                    "source_job_id": source_job_id,
                    "title": title,
                    "company": "Acme",
                    "canonical_url": f"https://example.com/jobs/{source_job_id}",
                    "location": location,
                    "description": description,
                }
            ],
            "stats": {"sources_checked": 1, "jobs_fetched": 1},
        }
        job_ids = job_search_db.save_retrieval_batch(batch)
        return job_ids[0]

    def test_pre_ranker_prevents_openai_call(self) -> None:
        """Ensure pre-ranker avoids LLM calls for low scores.

        Args:
            None.

        Returns:
            None.
        """
        candidate_id = self._seed_candidate()
        job_id = self._seed_job(
            title="Sales Representative",
            location="Onsite",
            description="Cold calling and outbound sales.",
            source_job_id="100",
        )
        os.environ["OPENAI_API_KEY"] = "test-key"
        agent = JobFitAgent(llm_client=RaiseOnCallLLM())
        result = agent.evaluate(candidate_id, job_id)
        self.assertEqual(result.used_llm, False)
        self.assertEqual(result.decision, "no")

    def test_fallback_without_openai_key(self) -> None:
        """Ensure fallback path works without OPENAI_API_KEY.

        Args:
            None.

        Returns:
            None.
        """
        candidate_id = self._seed_candidate()
        job_id = self._seed_job(
            title="Software Engineer",
            location="Remote",
            description="Python data pipelines.",
            source_job_id="200",
        )
        os.environ.pop("OPENAI_API_KEY", None)
        agent = JobFitAgent(llm_client=None)
        result = agent.evaluate(candidate_id, job_id)
        self.assertEqual(result.used_llm, False)
        self.assertIn(result.decision, {"strong_yes", "maybe", "no"})

    def test_skip_applied_within_7_days(self) -> None:
        """Ensure recently-applied jobs are skipped.

        Args:
            None.

        Returns:
            None.
        """
        candidate_id = self._seed_candidate()
        job_id = self._seed_job(
            title="Data Engineer",
            location="Remote",
            description="Python and SQL.",
            source_job_id="300",
        )
        job = _load_job(job_id)
        applied_at = datetime.now(timezone.utc).isoformat()
        job_match_db.add_application(
            candidate_id=candidate_id,
            dedupe_key_strong=job.dedupe_key_strong,
            canonical_url=job.canonical_url,
            dedupe_key_soft=job.dedupe_key_soft,
            description_hash=job.description_hash,
            applied_at=applied_at,
        )
        opportunity = job_match_db.get_or_create_opportunity(candidate_id, job_id)
        should_skip = job_match_db.should_skip_recently_applied(
            candidate_id,
            dedupe_key_strong=job.dedupe_key_strong,
            canonical_url=job.canonical_url,
            dedupe_key_soft=job.dedupe_key_soft,
            description_hash=job.description_hash,
        )
        self.assertTrue(should_skip)
        updated = job_match_db.mark_skipped_recently_applied(opportunity.id)
        self.assertTrue(updated.is_skipped_recently_applied)
        self.assertEqual(updated.skip_reason, "applied_within_7_days")

    def test_state_transitions(self) -> None:
        """Verify allowed state transitions.

        Args:
            None.

        Returns:
            None.
        """
        candidate_id = self._seed_candidate()
        job_id = self._seed_job(
            title="Analyst",
            location="Remote",
            description="SQL and reporting.",
            source_job_id="400",
        )
        opportunity = job_match_db.get_or_create_opportunity(candidate_id, job_id)
        scored = job_match_db.set_opportunity_scored(
            opportunity.id,
            score=10,
            decision="no",
            screen_bucket="low_match",
        )
        self.assertEqual(scored.state, JobState.SCREENED.value)
        approved = job_match_db.update_opportunity_state(scored.id, JobState.APPROVED)
        self.assertEqual(approved.state, JobState.APPROVED.value)
        applied = job_match_db.update_opportunity_state(approved.id, JobState.APPLIED)
        self.assertEqual(applied.state, JobState.APPLIED.value)


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
    import json

    return json.dumps(payload)


if __name__ == "__main__":
    unittest.main()

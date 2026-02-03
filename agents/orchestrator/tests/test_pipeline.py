"""Tests for orchestrator pipeline and state helpers."""
import os
import sys
import tempfile
import unittest
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


class OrchestratorPipelineTests(unittest.TestCase):
    def setUp(self) -> None:
        """Create a temporary SQLite database for isolation.

        Args:
            None.

        Returns:
            None.
        """
        self._old_db_path = os.environ.get("DB_PATH")
        self._tmpdir = tempfile.TemporaryDirectory()
        self._db_path = str(Path(self._tmpdir.name) / "test.db")
        os.environ["DB_PATH"] = self._db_path

    def tearDown(self) -> None:
        """Restore DB_PATH and clean up temp files.

        Args:
            None.

        Returns:
            None.
        """
        if self._old_db_path is None:
            os.environ.pop("DB_PATH", None)
        else:
            os.environ["DB_PATH"] = self._old_db_path
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

    def _batch_payload(self) -> dict:
        """Build a batch payload with high and low match jobs.

        Args:
            None.

        Returns:
            Batch payload dict.
        """
        return {
            "retrieval_batch": {
                "batch_id": "batch-pipeline-1",
                "started_at": "2026-01-01T00:00:00Z",
                "finished_at": "2026-01-01T01:00:00Z",
            },
            "jobs": [
                {
                    "source": "theirstack",
                    "source_job_id": "high-1",
                    "title": "Python Data Engineer",
                    "company": "Acme",
                    "canonical_url": "https://example.com/jobs/high-1",
                    "location": "Remote",
                    "remote": True,
                    "description": "Build data pipelines with Python and SQL.",
                },
                {
                    "source": "theirstack",
                    "source_job_id": "low-1",
                    "title": "Sales Representative",
                    "company": "Beta",
                    "canonical_url": "https://example.com/jobs/low-1",
                    "location": "Onsite",
                    "remote": False,
                    "description": "Cold calling and outbound sales.",
                },
            ],
            "stats": {"sources_checked": 1, "jobs_fetched": 2},
        }

    def test_pipeline_creates_opportunities_and_screens(self) -> None:
        """Pipeline creates opportunities, pre-ranks, and screens jobs.

        Args:
            None.

        Returns:
            None.
        """
        candidate_id = self._seed_candidate()
        batch_data = self._batch_payload()

        class FakeClient:
            def __init__(self, config: dict) -> None:
                self.config = config

            def run(self) -> dict:
                return batch_data

        original_pre_rank = pipeline._pre_rank_discovered

        def _assert_discovered_then_pre_rank(*args, **kwargs):
            job_ids = args[1]
            for job_id in job_ids:
                opp = orchestrator_state.get_or_create_opportunity(candidate_id, job_id)
                self.assertEqual(opp.state, "DISCOVERED")
            return original_pre_rank(*args, **kwargs)

        with patch.object(pipeline, "JobSearchClient", FakeClient):
            with patch.object(pipeline, "_pre_rank_discovered", _assert_discovered_then_pre_rank):
                calls = []
                original_apply = orchestrator_state.apply_fit_result

                def _spy_apply(*args, **kwargs):
                    calls.append((args, kwargs))
                    return original_apply(*args, **kwargs)

                with patch.object(orchestrator_state, "apply_fit_result", side_effect=_spy_apply):
                    stats = pipeline.run_daily(
                        candidate_id=candidate_id,
                        provider_config={"providers": []},
                        limit_to_score=10,
                    )

        self.assertEqual(stats["num_pre_ranked"], 2)
        self.assertEqual(stats["num_scored"], 2)
        self.assertEqual(len(calls), 2)

        db_path = job_search_db.get_db_path()
        engine = job_search_db.init_db(db_path)
        with job_search_db.Session(engine) as session:
            jobs = session.exec(job_search_db.select(job_search_db.Job)).all()
            self.assertEqual(len(jobs), 2)
            for job in jobs:
                opp = orchestrator_state.get_or_create_opportunity(candidate_id, job.id)
                self.assertEqual(opp.state, "SCREENED")

    def test_pre_ranker_gating_low_overlap(self) -> None:
        """Low overlap should skip LLM and use fallback scoring.

        Args:
            None.

        Returns:
            None.
        """
        candidate_id = self._seed_candidate()
        batch = {
            "retrieval_batch": {
                "batch_id": "batch-low-1",
                "started_at": "2026-01-01T00:00:00Z",
                "finished_at": "2026-01-01T01:00:00Z",
            },
            "jobs": [
                {
                    "source": "theirstack",
                    "source_job_id": "low-2",
                    "title": "Sales Representative",
                    "company": "Gamma",
                    "canonical_url": "https://example.com/jobs/low-2",
                    "location": "Onsite",
                    "remote": False,
                    "description": "Cold calling and outbound sales.",
                }
            ],
            "stats": {"sources_checked": 1, "jobs_fetched": 1},
        }
        job_ids = job_search_db.save_retrieval_batch(batch)
        job_id = job_ids[0]

        orchestrator_state.get_or_create_opportunity(candidate_id, job_id)
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

        class RaiseOnCallLLM:
            def __init__(self) -> None:
                self.model = "test-model"

            def generate(self, *args, **kwargs):
                raise AssertionError("LLM should not be called.")

        result = evaluate_and_persist(candidate_id, job_id, llm_client=RaiseOnCallLLM())
        self.assertFalse(result.used_llm)
        expected_score = int(round(retrieval_score * 100))
        self.assertEqual(result.overall_score, expected_score)

    def test_pipeline_skips_previously_processed_jobs(self) -> None:
        """Pipeline should not score skipped or already screened jobs.

        Args:
            None.

        Returns:
            None.
        """
        candidate_id = self._seed_candidate()
        batch_data = self._batch_payload()
        job_ids = job_search_db.save_retrieval_batch(batch_data)
        skipped_job_id = job_ids[0]
        screened_job_id = job_ids[1]

        orchestrator_state.mark_skipped_recently_applied(candidate_id, skipped_job_id)
        orchestrator_state.apply_fit_result(
            candidate_id,
            screened_job_id,
            score=10,
            decision="no",
            bucket="low_match",
        )

        with patch("job_match.agent.JobFitAgent.evaluate") as mock_evaluate:
            stats = pipeline.run_daily_from_batch(
                candidate_id=candidate_id,
                batch_data=batch_data,
                limit_to_score=10,
            )

        mock_evaluate.assert_not_called()
        self.assertEqual(stats["num_scored"], 0)

    def test_user_actions_state_transitions(self) -> None:
        """Validate SCREENED->APPROVED/CLOSED and APPROVED->APPLIED transitions.

        Args:
            None.

        Returns:
            None.
        """
        candidate_id = self._seed_candidate()
        batch = self._batch_payload()
        job_ids = job_search_db.save_retrieval_batch(batch)
        job_id = job_ids[0]
        opportunity = orchestrator_state.get_or_create_opportunity(candidate_id, job_id)
        orchestrator_state.apply_fit_result(
            candidate_id,
            job_id,
            score=80,
            decision="strong_yes",
            bucket="recommended",
        )

        approved = orchestrator_state.approve(opportunity.id)
        self.assertEqual(approved.state, "APPROVED")

        applied = orchestrator_state.mark_applied(opportunity.id)
        self.assertEqual(applied.state, "APPLIED")

        other_job_id = job_ids[1]
        other_opp = orchestrator_state.get_or_create_opportunity(candidate_id, other_job_id)
        orchestrator_state.apply_fit_result(
            candidate_id,
            other_job_id,
            score=20,
            decision="no",
            bucket="low_match",
        )
        closed = orchestrator_state.close(other_opp.id, reason="user_closed")
        self.assertEqual(closed.state, "CLOSED")
        self.assertEqual(closed.skip_reason, "user_closed")


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

"""Optional LLM integration test for JobFitAgent (skips without OPENAI_API_KEY)."""
import os
import sys
import tempfile
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
AGENTS_DIR = BASE_DIR.parent
if str(AGENTS_DIR) not in sys.path:
    sys.path.insert(0, str(AGENTS_DIR))

from dotenv import load_dotenv

_ENV_PATH = AGENTS_DIR / ".env"
if _ENV_PATH.exists():
    load_dotenv(dotenv_path=_ENV_PATH)

from candidate_profile.src import db as candidate_db
from job_match.agent import JobFitAgent
from job_search import db as job_search_db
from candidate_profile.src.llm_client import LLMClient


class JobMatchLLMIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self._old_db_path = os.environ.get("DB_PATH")
        self._tmpdir = tempfile.TemporaryDirectory()
        self._db_path = str(Path(self._tmpdir.name) / "test.db")
        os.environ["DB_PATH"] = self._db_path

    def tearDown(self) -> None:
        if self._old_db_path is None:
            os.environ.pop("DB_PATH", None)
        else:
            os.environ["DB_PATH"] = self._old_db_path
        try:
            self._tmpdir.cleanup()
        except PermissionError:
            pass

    @unittest.skipIf(
        not os.getenv("OPENAI_API_KEY"),
        "OPENAI_API_KEY not set; skipping live LLM integration test.",
    )
    def test_live_llm_job_fit(self) -> None:
        candidate_id = "cand-llm-1"
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
                "dealbreakers": [],
                "comp_min": 150000,
                "work_auth": "US",
            },
        )

        job_id = _seed_job(
            title="Python Data Engineer",
            location="Remote",
            description="Build data pipelines with Python and SQL.",
            source_job_id="llm-100",
        )

        llm_client = LLMClient()
        agent = JobFitAgent(llm_client=llm_client)
        result = agent.evaluate(candidate_id, job_id)
        print(f"LLM Job Fit Result: {result}")
        self.assertIn(result.decision, {"strong_yes", "maybe", "no"})
        self.assertGreaterEqual(result.overall_score, 0)
        self.assertLessEqual(result.overall_score, 100)


def _seed_job(*, title: str, location: str, description: str, source_job_id: str) -> str:
    batch = {
        "retrieval_batch": {
            "batch_id": "batch-llm-1",
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


def json_dump(payload: dict) -> str:
    import json

    return json.dumps(payload)


if __name__ == "__main__":
    unittest.main()

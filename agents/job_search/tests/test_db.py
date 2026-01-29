"""Tests for job_search database persistence helpers."""
import os
import sys
import tempfile
import unittest
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
AGENTS_DIR = BASE_DIR.parent
if str(AGENTS_DIR) not in sys.path:
    sys.path.insert(0, str(AGENTS_DIR))

spec = spec_from_file_location("job_search_db", str(BASE_DIR / "db.py"))
job_search_db = module_from_spec(spec)
if spec and spec.loader:
    spec.loader.exec_module(job_search_db)
else:
    raise RuntimeError("Failed to load job_search db module.")

save_retrieval_batch = job_search_db.save_retrieval_batch
get_retrieval_batch = job_search_db.get_retrieval_batch
get_recent_jobs = job_search_db.get_recent_jobs


class JobSearchDbTests(unittest.TestCase):
    def setUp(self) -> None:
        """Create a temporary SQLite database for isolation."""
        self._old_db_path = os.environ.get("DB_PATH")
        self._tmpdir = tempfile.TemporaryDirectory()
        self._db_path = str(Path(self._tmpdir.name) / "test.db")
        os.environ["DB_PATH"] = self._db_path

    def tearDown(self) -> None:
        """Restore DB_PATH and clean up temp files."""
        if self._old_db_path is None:
            os.environ.pop("DB_PATH", None)
        else:
            os.environ["DB_PATH"] = self._old_db_path
        try:
            self._tmpdir.cleanup()
        except PermissionError:
            pass

    def test_save_and_get_retrieval_batch(self) -> None:
        """Verify batch persistence and recent job retrieval."""
        batch = {
            "retrieval_batch": {
                "batch_id": "batch-1",
                "started_at": "2026-01-01T00:00:00Z",
                "finished_at": "2026-01-01T01:00:00Z",
            },
            "jobs": [
                {
                    "job_id": "job-1",
                    "source": "theirstack",
                    "source_job_id": "123",
                    "title": "Engineer",
                    "company": "Acme",
                    "canonical_url": "https://example.com/job",
                    "location": "Remote",
                    "employment_type": "full_time",
                    "posted_at": "2026-01-01",
                    "updated_at": "2026-01-02",
                    "date_found": "2026-01-03",
                    "description_text": "A role",
                    "description_hash": "hash",
                    "dedupe_key_strong": "strong",
                    "dedupe_key_soft": "soft",
                    "retrieval_score": 0.1,
                }
            ],
            "stats": {
                "sources_checked": 1,
                "jobs_fetched": 1,
                "jobs_new": 1,
                "jobs_updated": 0,
                "jobs_deduped": 0,
            },
        }

        save_retrieval_batch(batch)
        fetched = get_retrieval_batch("batch-1")
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched["retrieval_batch"]["batch_id"], "batch-1")
        self.assertEqual(len(fetched["jobs"]), 1)
        self.assertEqual(fetched["jobs"][0]["title"], "Engineer")

        recent = get_recent_jobs(limit=10)
        self.assertEqual(len(recent), 1)
        self.assertEqual(recent[0]["title"], "Engineer")


if __name__ == "__main__":
    unittest.main()

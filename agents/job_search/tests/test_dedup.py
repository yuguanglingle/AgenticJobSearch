"""Tests for job deduplication logic."""
import os
import sys
import tempfile
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
AGENTS_DIR = BASE_DIR.parent
if str(AGENTS_DIR) not in sys.path:
    sys.path.insert(0, str(AGENTS_DIR))

from job_search import db as job_search_db


class JobSearchDedupTests(unittest.TestCase):
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

    def test_dedup_by_provider_job_id(self) -> None:
        """Verify dedupe by source job id.

        Args:
            None.

        Returns:
            None.
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
                    "source_job_id": "123",
                    "title": "Engineer I",
                    "company": "Acme",
                    "canonical_url": "https://example.com/jobs/123",
                    "location": "Remote",
                },
                {
                    "source": "theirstack",
                    "source_job_id": "123",
                    "title": "Engineer I (duplicate)",
                    "company": "Acme",
                    "canonical_url": "https://example.com/jobs/123?utm_source=tracker",
                    "location": "Remote",
                },
            ],
            "stats": {"sources_checked": 1, "jobs_fetched": 2},
        }

        ids = job_search_db.save_retrieval_batch(batch)
        self.assertEqual(len(ids), 1)
        engine = job_search_db.init_db(self._db_path)
        with job_search_db.Session(engine) as session:
            jobs = session.exec(job_search_db.select(job_search_db.Job)).all()
        self.assertEqual(len(jobs), 1)

    def test_dedup_by_canonical_url(self) -> None:
        """Verify dedupe by canonical URL.

        Args:
            None.

        Returns:
            None.
        """
        batch = {
            "retrieval_batch": {
                "batch_id": "batch-2",
                "started_at": "2026-01-02T00:00:00Z",
                "finished_at": "2026-01-02T01:00:00Z",
            },
            "jobs": [
                {
                    "source": "theirstack",
                    "source_job_id": "999",
                    "title": "Analyst",
                    "company": "Beta",
                    "canonical_url": "https://example.com/jobs/999/?utm_medium=email",
                    "location": "NYC",
                },
                {
                    "source": "theirstack",
                    "source_job_id": "998",
                    "title": "Analyst",
                    "company": "Beta",
                    "canonical_url": "https://example.com/jobs/999",
                    "location": "NYC",
                },
            ],
            "stats": {"sources_checked": 1, "jobs_fetched": 2},
        }

        ids = job_search_db.save_retrieval_batch(batch)
        self.assertEqual(len(ids), 1)
        engine = job_search_db.init_db(self._db_path)
        with job_search_db.Session(engine) as session:
            jobs = session.exec(job_search_db.select(job_search_db.Job)).all()
        self.assertEqual(len(jobs), 1)


if __name__ == "__main__":
    unittest.main()

"""Tests for candidate profile database helpers."""
import os
import sys
import tempfile
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
AGENTS_DIR = BASE_DIR.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))
if str(AGENTS_DIR) not in sys.path:
    sys.path.insert(0, str(AGENTS_DIR))

from src import db


class CandidateDbTests(unittest.TestCase):
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

    def test_save_and_get_candidate(self) -> None:
        """Verify candidate and preferences persist and can be read back."""
        db.save_candidate(
            candidate_id="cand-1",
            resume_raw="Resume",
            candidate_profile_json='{"ok": true}',
            llm_model="test-model",
            prompt_version="v1",
            created_at="2026-01-01T00:00:00Z",
            updated_at="2026-01-01T00:00:00Z",
            preferences={
                "locations": ["SF"],
                "remote_preference": "remote",
                "role_targets": ["Engineer"],
                "industries": ["Tech"],
                "dealbreakers": ["None"],
                "comp_min": 150000,
                "work_auth": "US",
            },
        )

        candidates = db.list_candidates()
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].id, "cand-1")

        candidate = db.get_candidate("cand-1")
        self.assertIsNotNone(candidate)
        self.assertEqual(candidate.name, None)
        self.assertEqual(candidate.resume_raw, "Resume")

        prefs = db.get_candidate_preferences("cand-1")
        self.assertIsNotNone(prefs)
        self.assertEqual(prefs.remote_preference, "remote")


if __name__ == "__main__":
    unittest.main()

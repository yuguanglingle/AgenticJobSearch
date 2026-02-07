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

    def test_save_and_get_candidate(self) -> None:
        """Verify candidate and preferences persist and can be read back.

        Args:
            None.

        Returns:
            None.
        """
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

    def test_candidate_profile_json_structure(self) -> None:
        """Test that candidate profile JSON contains expected keys.
        
        Ensures that the stored profile JSON has the correct structure
        with all required fields for job matching (keywords, skills, domains).
        
        Args:
            None.
            
        Returns:
            None.
        """
        import json
        profile_json = json.dumps({
            "ok": True,
            "agent": "CandidateProfileAgent",
            "result": {
                "candidate_profile": {
                    "headline": "Senior Engineer",
                    "seniority_estimate": "senior",
                    "core_skills": ["Python", "SQL", "AWS"],
                    "domains": ["Data", "Backend"],
                    "keywords_for_search": ["Python", "SQL", "AWS", "Data Engineer"],
                    "experience_highlights": []
                }
            }
        })
        
        db.save_candidate(
            candidate_id="cand-profile-test",
            resume_raw="Test resume",
            candidate_profile_json=profile_json,
            llm_model="gpt-4",
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
        
        candidate = db.get_candidate("cand-profile-test")
        self.assertIsNotNone(candidate)
        
        # Parse and verify JSON structure
        parsed = json.loads(candidate.candidate_profile_json)
        self.assertTrue(parsed.get("ok"))
        self.assertEqual(parsed.get("agent"), "CandidateProfileAgent")
        
        profile = parsed.get("result", {}).get("candidate_profile", {})
        self.assertIn("headline", profile)
        self.assertIn("core_skills", profile)
        self.assertIn("domains", profile)
        self.assertIn("keywords_for_search", profile)
        
        # Verify lists
        self.assertIsInstance(profile.get("core_skills"), list)
        self.assertIsInstance(profile.get("domains"), list)
        self.assertIsInstance(profile.get("keywords_for_search"), list)
        
        # Verify content
        self.assertGreater(len(profile.get("keywords_for_search", [])), 0)

    def test_preferences_all_fields(self) -> None:
        """Test that all preference fields are persisted correctly.
        
        Verifies that complex preference structures (arrays, strings, numbers)
        are stored and retrieved with correct data types.
        
        Args:
            None.
            
        Returns:
            None.
        """
        import json
        
        locations = ["San Francisco", "Remote", "Austin"]
        role_targets = ["Data Engineer", "ML Engineer"]
        industries = ["Tech", "FinTech"]
        dealbreakers = ["Relocation required", "On-call 24/7"]
        
        db.save_candidate(
            candidate_id="cand-prefs",
            resume_raw="Resume",
            candidate_profile_json='{"ok": true}',
            llm_model="gpt-4",
            prompt_version="v1",
            created_at="2026-01-01T00:00:00Z",
            updated_at="2026-01-01T00:00:00Z",
            preferences={
                "locations": locations,
                "remote_preference": "hybrid",
                "role_targets": role_targets,
                "industries": industries,
                "dealbreakers": dealbreakers,
                "comp_min": 180000,
                "work_auth": "H1B_ELIGIBLE",
            },
        )
        
        prefs = db.get_candidate_preferences("cand-prefs")
        self.assertIsNotNone(prefs)
        
        # Verify string fields
        self.assertEqual(prefs.remote_preference, "hybrid")
        self.assertEqual(prefs.work_auth, "H1B_ELIGIBLE")
        
        # Verify array fields (stored as JSON strings)
        stored_locations = json.loads(prefs.locations)
        stored_roles = json.loads(prefs.role_targets)
        stored_industries = json.loads(prefs.industries)
        stored_dealbreakers = json.loads(prefs.dealbreakers)
        
        self.assertEqual(stored_locations, locations)
        self.assertEqual(stored_roles, role_targets)
        self.assertEqual(stored_industries, industries)
        self.assertEqual(stored_dealbreakers, dealbreakers)
        self.assertEqual(prefs.comp_min, 180000)


if __name__ == "__main__":
    unittest.main()

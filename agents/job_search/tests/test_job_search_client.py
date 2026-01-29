"""Tests for job_search client helpers and mapping logic."""
import os
import sys
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
AGENTS_DIR = BASE_DIR.parent
if str(BASE_DIR) in sys.path:
    sys.path.remove(str(BASE_DIR))
if str(AGENTS_DIR) in sys.path:
    sys.path.remove(str(AGENTS_DIR))
sys.path.insert(0, str(BASE_DIR))
sys.path.append(str(AGENTS_DIR))

from job_search_client import clean_text, sha256_text, map_job


class JobSearchClientTests(unittest.TestCase):
    def test_clean_text_collapses_whitespace(self) -> None:
        """Normalize whitespace to a single-space string."""
        self.assertEqual(clean_text(" a  b\n c "), "a b c")

    def test_sha256_text_is_deterministic(self) -> None:
        """Ensure hashing is stable and returns a 64-char digest."""
        first = sha256_text("hello")
        second = sha256_text("hello")
        self.assertEqual(first, second)
        self.assertEqual(len(first), 64)

    def test_map_job_basic_fields(self) -> None:
        """Map core fields from provider payload into normalized schema."""
        payload = {
            "id": 123,
            "job_title": "Engineer",
            "company": "Acme",
            "final_url": "https://example.com/job",
            "short_location": "Remote",
            "employment_statuses": ["full_time"],
            "date_posted": "2026-01-01",
            "date_reposted": "2026-01-02",
            "discovered_at": "2026-01-03",
            "description": "A role",
        }
        mapped = map_job(payload, "theirstack")
        self.assertEqual(mapped["source"], "theirstack")
        self.assertEqual(mapped["title"], "Engineer")
        self.assertEqual(mapped["location"], "Remote")
        self.assertEqual(mapped["employment_type"], "full_time")
        self.assertTrue(mapped["job_id"])


if __name__ == "__main__":
    unittest.main()

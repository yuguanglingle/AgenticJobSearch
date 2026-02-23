"""Tests for candidate profile agent normalization helpers."""
import os
import sys
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
AGENTS_DIR = BASE_DIR.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))
if str(AGENTS_DIR) not in sys.path:
    sys.path.insert(0, str(AGENTS_DIR))

from src.agent import _normalize_envelope
from src.models import (
    CandidateProfileEnvelope,
    CandidateProfileResult,
    CandidateProfile,
    ExperienceHighlight,
    ToneStyle,
)


class NormalizeEnvelopeTests(unittest.TestCase):
    def test_normalize_envelope_caps_lists_and_confidence(self) -> None:
        """Ensure normalization caps list sizes and clamps confidence.

        Args:
            None.

        Returns:
            None.
        """
        highlights = [
            ExperienceHighlight(
                company=f"Company {i}",
                role="Engineer",
                impact_bullets=[f"Impact {j}" for j in range(10)],
            )
            for i in range(7)
        ]
        profile = CandidateProfile(
            headline="Test",
            seniority_estimate="mid",
            core_skills=[f"Skill {i}" for i in range(40)],
            domains=[f"Domain {i}" for i in range(20)],
            experience_highlights=highlights,
            keywords_for_search=[f"Keyword {i}" for i in range(30)],
            tone_style=ToneStyle(voice="warm", length="short"),
        )
        envelope = CandidateProfileEnvelope(
            ok=False,
            agent="",
            run_id="",
            timestamp="",
            result=CandidateProfileResult(candidate_profile=profile),
            confidence=2.5,
        )

        normalized = _normalize_envelope(envelope)

        self.assertEqual(len(normalized.result.candidate_profile.core_skills), 25)
        self.assertEqual(len(normalized.result.candidate_profile.domains), 10)
        self.assertEqual(len(normalized.result.candidate_profile.keywords_for_search), 20)
        self.assertEqual(len(normalized.result.candidate_profile.experience_highlights), 5)
        for highlight in normalized.result.candidate_profile.experience_highlights:
            self.assertEqual(len(highlight.impact_bullets), 4)
        self.assertEqual(normalized.confidence, 1.0)


if __name__ == "__main__":
    unittest.main()

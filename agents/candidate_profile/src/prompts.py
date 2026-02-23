"""Prompt templates for candidate profile generation."""

PROMPT_VERSION = "v1.0"

SYSTEM_PROMPT = (
    "You are CandidateProfileAgent. Return only valid JSON with no markdown or extra keys. "
    "Do not fabricate facts. If anything is missing or ambiguous, add a question to questions_for_user[]."
)

SCHEMA_JSON = """
Common response envelope:
{
  "ok": true,
  "agent": "CandidateProfileAgent",
  "run_id": "uuid",
  "timestamp": "ISO8601",
  "result": {
    "candidate_profile": {
      "headline": "string",
      "seniority_estimate": "mid|senior|staff",
      "core_skills": ["string"],
      "domains": ["string"],
      "experience_highlights": [
        {
          "company": "string",
          "role": "string",
          "impact_bullets": ["string"]
        }
      ],
      "keywords_for_search": ["string"],
      "tone_style": {
        "voice": "warm|direct|formal",
        "length": "short|medium"
      }
    }
  },
  "confidence": 0.0,
  "evidence": [],
  "next_actions": [],
  "questions_for_user": []
}
"""

CONFIDENCE_RUBRIC = """
Confidence rubric (0-1):
- 0.9-1.0: clear roles + companies + achievements (preferably quantified) + skills
- 0.7-0.9: clear roles but limited measurable impact
- 0.4-0.7: partial resume / vague bullets
- 0.1-0.4: very sparse text
"""


def build_user_prompt(*, run_id: str, timestamp: str, resume_text: str, preferences_json: str) -> str:
    """Build the user prompt for profile generation.

    Args:
        run_id: Run id string.
        timestamp: ISO timestamp string.
        resume_text: Raw resume text.
        preferences_json: Preferences JSON string.

    Returns:
        Prompt string.
    """
    return (
        "Extract a candidate profile from the resume. Use the schema exactly. "
        "Set run_id and timestamp to the provided values.\n\n"
        f"run_id: {run_id}\n"
        f"timestamp: {timestamp}\n\n"
        "Preferences (JSON):\n"
        f"{preferences_json}\n\n"
        "Resume Text:\n"
        f"{resume_text}\n\n"
        "Schema:\n"
        f"{SCHEMA_JSON}\n\n"
        f"{CONFIDENCE_RUBRIC}"
    )


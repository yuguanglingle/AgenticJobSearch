"""Candidate profile generation agent."""

import json
import uuid
from typing import Optional, Tuple, Dict, Any
from pydantic import ValidationError

from src.models import (
    CandidateProfileRequest,
    CandidateProfileEnvelope,
)
from src.llm_client import LLMClient
from src.prompts import SYSTEM_PROMPT, build_user_prompt, PROMPT_VERSION
from src.utils import now_utc_iso, clamp, unique_sorted
from src import db


AGENT_NAME = "CandidateProfileAgent"


def _normalize_envelope(envelope: CandidateProfileEnvelope) -> CandidateProfileEnvelope:
    """Normalize and cap fields in the candidate profile envelope.

    Args:
        envelope: CandidateProfileEnvelope instance.

    Returns:
        Normalized CandidateProfileEnvelope.
    """
    profile = envelope.result.candidate_profile
    profile.core_skills = unique_sorted(profile.core_skills, 25)
    profile.domains = unique_sorted(profile.domains, 10)
    profile.keywords_for_search = unique_sorted(profile.keywords_for_search, 20)
    profile.experience_highlights = profile.experience_highlights[:5]
    for exp in profile.experience_highlights:
        exp.impact_bullets = exp.impact_bullets[:4]

    envelope.confidence = clamp(envelope.confidence)
    return envelope


def generate_candidate_profile(
    input: CandidateProfileRequest,
) -> Tuple[CandidateProfileEnvelope, str, Optional[Dict[str, Any]]]:
    """Generate candidate profile via LLM and persist results.

    Args:
        input: CandidateProfileRequest payload.

    Returns:
        Tuple of (CandidateProfileEnvelope, usage_summary, usage_raw).
    """
    candidate_id = input.candidate_id or str(uuid.uuid4())
    run_id = str(uuid.uuid4())
    timestamp = now_utc_iso()

    preferences_json = json.dumps(input.preferences.dict(), ensure_ascii=True)
    user_prompt = build_user_prompt(
        run_id=run_id,
        timestamp=timestamp,
        resume_text=input.resume_text,
        preferences_json=preferences_json,
    )

    client = LLMClient()
    raw_response = client.generate(system_prompt=SYSTEM_PROMPT, user_prompt=user_prompt)
    usage_summary = client.usage_summary()
    usage_raw = client.last_usage

    def parse_response(payload: str) -> CandidateProfileEnvelope:
        data = json.loads(payload)
        return CandidateProfileEnvelope.parse_obj(data)

    try:
        envelope = parse_response(raw_response)
    except (json.JSONDecodeError, ValidationError):
        fixed = client.fix_json(system_prompt=SYSTEM_PROMPT, bad_json=raw_response)
        usage_summary = client.usage_summary()
        usage_raw = client.last_usage
        try:
            envelope = parse_response(fixed)
            raw_response = fixed
        except (json.JSONDecodeError, ValidationError) as exc:
            raise ValueError("LLM returned invalid JSON.") from exc

    envelope.ok = True
    envelope.agent = AGENT_NAME
    envelope.run_id = run_id
    envelope.timestamp = timestamp
    envelope = _normalize_envelope(envelope)

    db.save_candidate(
        candidate_id=candidate_id,
        resume_raw=input.resume_text,
        candidate_profile_json=envelope.json(),
        llm_model=client.model,
        prompt_version=PROMPT_VERSION,
        created_at=timestamp,
        updated_at=timestamp,
        preferences=input.preferences.dict(),
    )

    db.save_agent_run(
        id=str(uuid.uuid4()),
        candidate_id=candidate_id,
        run_id=run_id,
        agent_name=AGENT_NAME,
        input_json=json.dumps(
            {
                "request": input.dict(),
                "system_prompt": SYSTEM_PROMPT,
                "user_prompt": user_prompt,
                "prompt_version": PROMPT_VERSION,
                "usage": client.last_usage,
            },
            ensure_ascii=True,
        ),
        output_json=envelope.json(),
        raw_llm_response=raw_response,
        created_at=timestamp,
    )

    return envelope, usage_summary, usage_raw

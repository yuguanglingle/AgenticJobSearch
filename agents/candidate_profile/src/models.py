"""Pydantic models for candidate profile generation."""

from typing import List, Optional, Literal
from pydantic import BaseModel, Field, validator


class CandidatePreferences(BaseModel):
    """Candidate preferences payload.

    Args:
        locations: Preferred locations.
        remote_preference: Remote preference.
        role_targets: Target roles.
        industries: Target industries.
        dealbreakers: Dealbreakers list.
        comp_min: Minimum compensation.
        work_auth: Work authorization.

    Returns:
        None.
    """
    locations: List[str] = Field(default_factory=list)
    remote_preference: Optional[Literal["remote", "hybrid", "onsite", "any"]] = None
    role_targets: List[str] = Field(default_factory=list)
    industries: List[str] = Field(default_factory=list)
    dealbreakers: List[str] = Field(default_factory=list)
    comp_min: Optional[int] = None
    work_auth: Optional[str] = None


class CandidateProfileRequest(BaseModel):
    """Candidate profile generation request.

    Args:
        candidate_id: Optional candidate id.
        resume_text: Raw resume text.
        preferences: CandidatePreferences payload.

    Returns:
        None.
    """
    candidate_id: Optional[str] = None
    resume_text: str
    preferences: CandidatePreferences = Field(default_factory=CandidatePreferences)


class ExperienceHighlight(BaseModel):
    """Experience highlight summary.

    Args:
        company: Company name.
        role: Role title.
        impact_bullets: Impact bullet list.

    Returns:
        None.
    """
    company: str
    role: str
    impact_bullets: List[str] = Field(default_factory=list)


class ToneStyle(BaseModel):
    """Tone and style preferences.

    Args:
        voice: Voice style.
        length: Desired length.

    Returns:
        None.
    """
    voice: Optional[Literal["warm", "direct", "formal", ""]] = ""
    length: Optional[Literal["short", "medium", ""]] = ""


class CandidateProfile(BaseModel):
    """Generated candidate profile.

    Args:
        headline: Profile headline.
        seniority_estimate: Seniority level.
        core_skills: Core skills list.
        domains: Domain list.
        experience_highlights: Experience highlights.
        keywords_for_search: Keywords list.
        tone_style: ToneStyle payload.

    Returns:
        None.
    """
    headline: str
    seniority_estimate: Optional[Literal["mid", "senior", "staff", "junior"]] = "mid"
    core_skills: List[str] = Field(default_factory=list)
    domains: List[str] = Field(default_factory=list)
    experience_highlights: List[ExperienceHighlight] = Field(default_factory=list)
    keywords_for_search: List[str] = Field(default_factory=list)
    tone_style: ToneStyle


class CandidateProfileResult(BaseModel):
    """Profile result wrapper.

    Args:
        candidate_profile: CandidateProfile payload.

    Returns:
        None.
    """
    candidate_profile: CandidateProfile


class CandidateProfileEnvelope(BaseModel):
    """Envelope for profile generation output.

    Args:
        ok: Success flag.
        agent: Agent name.
        run_id: Run id.
        timestamp: ISO timestamp string.
        result: CandidateProfileResult payload.
        confidence: Confidence score.
        evidence: Evidence list.
        next_actions: Suggested next actions.
        questions_for_user: Questions list.

    Returns:
        None.
    """
    ok: bool
    agent: str
    run_id: str
    timestamp: str
    result: CandidateProfileResult
    confidence: float
    evidence: List[str] = Field(default_factory=list)
    next_actions: List[str] = Field(default_factory=list)
    questions_for_user: List[str] = Field(default_factory=list)


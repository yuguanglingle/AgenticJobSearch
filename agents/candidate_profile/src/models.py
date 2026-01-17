from typing import List, Optional, Literal
from pydantic import BaseModel, Field, validator


class CandidatePreferences(BaseModel):
    locations: List[str] = Field(default_factory=list)
    remote_preference: Optional[Literal["remote", "hybrid", "onsite", "any"]] = None
    role_targets: List[str] = Field(default_factory=list)
    industries: List[str] = Field(default_factory=list)
    dealbreakers: List[str] = Field(default_factory=list)
    comp_min: Optional[int] = None
    work_auth: Optional[str] = None


class CandidateProfileRequest(BaseModel):
    candidate_id: Optional[str] = None
    resume_text: str
    preferences: CandidatePreferences = Field(default_factory=CandidatePreferences)

    @validator("resume_text")
    def resume_text_min_length(cls, v: str) -> str:
        if not v or len(v.strip()) < 200:
            raise ValueError("Resume text must be at least 200 characters.")
        return v


class ExperienceHighlight(BaseModel):
    company: str
    role: str
    impact_bullets: List[str] = Field(default_factory=list)


class ToneStyle(BaseModel):
    voice: Literal["warm", "direct", "formal"]
    length: Literal["short", "medium"]


class CandidateProfile(BaseModel):
    headline: str
    seniority_estimate: Literal["mid", "senior", "staff"]
    core_skills: List[str] = Field(default_factory=list)
    domains: List[str] = Field(default_factory=list)
    experience_highlights: List[ExperienceHighlight] = Field(default_factory=list)
    keywords_for_search: List[str] = Field(default_factory=list)
    tone_style: ToneStyle


class CandidateProfileResult(BaseModel):
    candidate_profile: CandidateProfile


class CandidateProfileEnvelope(BaseModel):
    ok: bool
    agent: str
    run_id: str
    timestamp: str
    result: CandidateProfileResult
    confidence: float
    evidence: List[str] = Field(default_factory=list)
    next_actions: List[str] = Field(default_factory=list)
    questions_for_user: List[str] = Field(default_factory=list)


"""Shared Pydantic models for probe tooling."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class JobPosting(BaseModel):
    """Job listing summary extracted from a source.

    Args:
        job_id: Stable job identifier.
        title: Job title.
        location: Job location.
        url: Job listing URL.
        date: Posting date.
        raw: Raw payload dict.

    Returns:
        None.
    """
    job_id: Optional[str] = None
    title: Optional[str] = None
    location: Optional[str] = None
    url: Optional[str] = None
    date: Optional[str] = None
    raw: Optional[Dict[str, Any]] = None


class JobDetail(BaseModel):
    """Job detail page extraction result.

    Args:
        url: Detail URL.
        text: Extracted text.
        text_length: Length of extracted text.
        sha256: Hash of extracted text.

    Returns:
        None.
    """
    url: str
    text: str
    text_length: int
    sha256: str


class ProbeResult(BaseModel):
    """Probe result for a source and method.

    Args:
        source_name: Source name.
        source_type: Source type.
        list_url: Listings URL.
        status_code: GET status code.
        final_url: Final URL after redirects.
        head_status: HEAD status code.
        response_time_ms: Response latency.
        content_type: Response content type.
        content_length: Response length.
        blocked: Whether blocked.
        requires_js: Whether JS rendering is required.
        listings_found: Count of listings parsed.
        details_ok: Whether details sampling succeeded.
        has_stable_id: Whether stable ids were found.
        has_date: Whether dates were found.
        recommended_method: Recommended fetch method.
        score: Heuristic score.
        notes: Notes list.
        errors: Errors list.
        job_samples: JobPosting samples.
        detail_samples: JobDetail samples.
        bot_signals: Bot detection signals.

    Returns:
        None.
    """
    source_name: str
    source_type: str
    list_url: str
    status_code: Optional[int] = None
    final_url: Optional[str] = None
    head_status: Optional[int] = None
    response_time_ms: Optional[float] = None
    content_type: Optional[str] = None
    content_length: Optional[int] = None
    blocked: bool = False
    requires_js: bool = False
    listings_found: int = 0
    details_ok: bool = False
    has_stable_id: bool = False
    has_date: bool = False
    recommended_method: str = ""
    score: int = 0
    notes: List[str] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)
    job_samples: List[JobPosting] = Field(default_factory=list)
    detail_samples: List[JobDetail] = Field(default_factory=list)
    bot_signals: List[str] = Field(default_factory=list)

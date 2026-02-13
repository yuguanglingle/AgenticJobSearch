"""Shared state helpers for job opportunities."""

from __future__ import annotations

from typing import Optional

from sqlmodel import Session

from job_match import db as job_match_db
from job_match.state_machine import JobState
from job_search import db as job_search_db


def get_or_create_opportunity(candidate_id: str, job_id: str) -> job_match_db.JobOpportunity:
    """Get or create an opportunity for candidate/job.

    Args:
        candidate_id: Candidate primary key.
        job_id: Job primary key.

    Returns:
        JobOpportunity record.
    """
    return job_match_db.get_or_create_opportunity(candidate_id, job_id)


def apply_fit_result(
    candidate_id: str,
    job_id: str,
    score: int,
    decision: str,
    bucket: str,
    *,
    subscores: Optional[dict] = None,
    top_reasons: Optional[list[str]] = None,
    gaps: Optional[list[str]] = None,
    dealbreakers_triggered: Optional[list[str]] = None,
    model: Optional[str] = None,
    raw_response: Optional[str] = None,
    scored_at: Optional[str] = None,
    description_hash: Optional[str] = None,
) -> job_match_db.JobOpportunity:
    """Persist a fit result and mark opportunity as SCREENED.

    Args:
        candidate_id: Candidate primary key.
        job_id: Job primary key.
        score: Overall score 0-100.
        decision: Decision label.
        bucket: Screen bucket label.
        subscores: Optional subscores dict.
        top_reasons: Optional list of reasons.
        gaps: Optional list of gaps.
        dealbreakers_triggered: Optional list of dealbreakers.
        model: Optional model name.
        raw_response: Optional raw LLM response.
        scored_at: Optional ISO timestamp.

    Returns:
        Updated JobOpportunity record.
    """
    opportunity = job_match_db.get_or_create_opportunity(candidate_id, job_id)
    if JobState(opportunity.state) == JobState.CLOSED:
        raise ValueError("Cannot score a closed opportunity.")

    job_match_db.save_job_fit_evaluation(
        candidate_id=candidate_id,
        job_id=job_id,
        overall_score=score,
        decision=decision,
        subscores=subscores or {"manual": True},
        top_reasons=top_reasons or [],
        gaps=gaps or [],
        dealbreakers_triggered=dealbreakers_triggered or [],
        model=model,
        raw_response=raw_response,
    )
    if not description_hash:
        db_path = job_search_db.get_db_path()
        engine = job_search_db.init_db(db_path)
        with Session(engine) as job_session:
            job = job_session.get(job_search_db.Job, job_id)
            if job:
                description_hash = job.description_hash
    return job_match_db.set_opportunity_scored(
        opportunity.id,
        score=score,
        decision=decision,
        screen_bucket=bucket,
        scored_at=scored_at,
        description_hash=description_hash,
    )


def approve(opportunity_id: str) -> job_match_db.JobOpportunity:
    """Approve a screened opportunity.

    Args:
        opportunity_id: JobOpportunity primary key.

    Returns:
        Updated JobOpportunity record.
    """
    return job_match_db.update_opportunity_state(opportunity_id, JobState.APPROVED)


def close(opportunity_id: str, reason: Optional[str] = None) -> job_match_db.JobOpportunity:
    """Close an opportunity and optionally record a reason.

    Args:
        opportunity_id: JobOpportunity primary key.
        reason: Optional close reason.

    Returns:
        Updated JobOpportunity record.
    """
    opportunity = job_match_db.update_opportunity_state(opportunity_id, JobState.CLOSED)
    if reason:
        db_path = job_match_db.get_db_path()
        engine = job_match_db.init_db(db_path)
        with Session(engine) as session:
            record = session.get(job_match_db.JobOpportunity, opportunity_id)
            if record:
                record.skip_reason = reason
                session.add(record)
                session.commit()
                session.refresh(record)
                opportunity = record
    return opportunity


def mark_applied(opportunity_id: str, applied_at: Optional[str] = None) -> job_match_db.JobOpportunity:
    """Mark an opportunity as applied and record dedupe data.

    Args:
        opportunity_id: JobOpportunity primary key.
        applied_at: Optional ISO timestamp.

    Returns:
        Updated JobOpportunity record.
    """
    db_path = job_match_db.get_db_path()
    job_engine = job_search_db.init_db(db_path)
    opp_engine = job_match_db.init_db(db_path)
    with Session(opp_engine) as session:
        opportunity = session.get(job_match_db.JobOpportunity, opportunity_id)
        if not opportunity:
            raise ValueError("Opportunity not found.")
        job = None
        with Session(job_engine) as job_session:
            job = job_session.get(job_search_db.Job, opportunity.job_id)
        if job:
            job_match_db.add_application(
                candidate_id=opportunity.candidate_id,
                dedupe_key_strong=job.dedupe_key_strong,
                canonical_url=job.canonical_url,
                dedupe_key_soft=job.dedupe_key_soft,
                description_hash=job.description_hash,
                applied_at=applied_at,
            )
    return job_match_db.update_opportunity_state(opportunity_id, JobState.APPLIED)


def mark_skipped_recently_applied(
    candidate_id: str,
    job_id: str,
    reason: str = "applied_within_7_days",
) -> job_match_db.JobOpportunity:
    """Mark an opportunity as skipped due to a recent application.

    Args:
        candidate_id: Candidate primary key.
        job_id: Job primary key.
        reason: Skip reason string.

    Returns:
        Updated JobOpportunity record.
    """
    opportunity = job_match_db.get_or_create_opportunity(candidate_id, job_id)
    return job_match_db.mark_skipped_recently_applied(opportunity.id, reason=reason)

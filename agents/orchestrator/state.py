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
) -> job_match_db.JobOpportunity:
    """Persist a fit result and mark opportunity as SCREENED.

    Args:
        candidate_id: Candidate primary key.
        job_id: Job primary key.
        score: Overall score 0-100.
        decision: Decision label.
        bucket: Screen bucket label.

    Returns:
        Updated JobOpportunity record.
    """
    opportunity = job_match_db.get_or_create_opportunity(candidate_id, job_id)
    job_match_db.save_job_fit_evaluation(
        candidate_id=candidate_id,
        job_id=job_id,
        overall_score=score,
        decision=decision,
        subscores={"manual": True},
        top_reasons=[],
        gaps=[],
        dealbreakers_triggered=[],
        model=None,
        raw_response=None,
    )
    return job_match_db.set_opportunity_scored(
        opportunity.id,
        score=score,
        decision=decision,
        screen_bucket=bucket,
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

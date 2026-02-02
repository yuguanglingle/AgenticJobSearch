import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional, Dict, Any
from uuid import uuid4

from sqlmodel import SQLModel, Field, Session, select

from job_match.state_machine import JobState, ensure_transition, next_action_for_state
from db.utils import init_db


class JobOpportunity(SQLModel, table=True):
    id: str = Field(primary_key=True)
    candidate_id: str
    job_id: str = Field(foreign_key="job.id")
    state: str
    fit_score: Optional[int] = None
    fit_decision: Optional[str] = None
    screen_bucket: Optional[str] = None
    next_action: Optional[str] = None
    last_scored_at: Optional[str] = None
    first_seen: str
    last_state_changed_at: str
    is_skipped_recently_applied: bool = False
    skip_reason: Optional[str] = None


class JobFitEvaluation(SQLModel, table=True):
    id: str = Field(primary_key=True)
    candidate_id: str
    job_id: str = Field(foreign_key="job.id")
    overall_score: int
    decision: str
    subscores_json: str
    top_reasons_json: str
    gaps_json: str
    dealbreakers_triggered_json: str
    created_at: str
    model: Optional[str] = None
    raw_response: Optional[str] = None


class Application(SQLModel, table=True):
    id: str = Field(primary_key=True)
    candidate_id: str
    dedupe_key_strong: Optional[str] = None
    canonical_url: Optional[str] = None
    dedupe_key_soft: Optional[str] = None
    description_hash: Optional[str] = None
    applied_at: str


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_db_path() -> str:
    db_path = os.getenv("DB_PATH")
    if not db_path:
        base_dir = Path(__file__).resolve().parents[2]
        db_path = str(base_dir / "data" / "app.db")
    return db_path


def get_or_create_opportunity(candidate_id: str, job_id: str) -> JobOpportunity:
    db_path = get_db_path()
    engine = init_db(db_path)
    with Session(engine) as session:
        stmt = select(JobOpportunity).where(
            JobOpportunity.candidate_id == candidate_id,
            JobOpportunity.job_id == job_id,
        )
        existing = session.exec(stmt).first()
        if existing:
            return existing
        now = utc_now()
        opportunity = JobOpportunity(
            id=str(uuid4()),
            candidate_id=candidate_id,
            job_id=job_id,
            state=JobState.DISCOVERED.value,
            fit_score=None,
            fit_decision=None,
            screen_bucket=None,
            next_action="",
            last_scored_at=None,
            first_seen=now,
            last_state_changed_at=now,
            is_skipped_recently_applied=False,
            skip_reason=None,
        )
        session.add(opportunity)
        session.commit()
        session.refresh(opportunity)
        return opportunity


def update_opportunity_state(opportunity_id: str, new_state: JobState) -> JobOpportunity:
    db_path = get_db_path()
    engine = init_db(db_path)
    with Session(engine) as session:
        opportunity = session.get(JobOpportunity, opportunity_id)
        if not opportunity:
            raise ValueError("Opportunity not found.")
        current = JobState(opportunity.state)
        ensure_transition(current, new_state)
        if current != new_state:
            opportunity.state = new_state.value
            opportunity.last_state_changed_at = utc_now()
            opportunity.next_action = next_action_for_state(new_state)
        session.add(opportunity)
        session.commit()
        session.refresh(opportunity)
        return opportunity


def set_opportunity_scored(
    opportunity_id: str,
    *,
    score: int,
    decision: str,
    screen_bucket: str,
    scored_at: Optional[str] = None,
) -> JobOpportunity:
    db_path = get_db_path()
    engine = init_db(db_path)
    with Session(engine) as session:
        opportunity = session.get(JobOpportunity, opportunity_id)
        if not opportunity:
            raise ValueError("Opportunity not found.")
        current = JobState(opportunity.state)
        if current != JobState.CLOSED:
            ensure_transition(current, JobState.SCREENED)
            opportunity.state = JobState.SCREENED.value
            opportunity.last_state_changed_at = utc_now()
            opportunity.next_action = next_action_for_state(JobState.SCREENED)
        opportunity.fit_score = score
        opportunity.fit_decision = decision
        opportunity.screen_bucket = screen_bucket
        opportunity.last_scored_at = scored_at or utc_now()
        session.add(opportunity)
        session.commit()
        session.refresh(opportunity)
        return opportunity


def add_application(
    *,
    candidate_id: str,
    dedupe_key_strong: Optional[str],
    canonical_url: Optional[str],
    dedupe_key_soft: Optional[str],
    description_hash: Optional[str],
    applied_at: Optional[str] = None,
) -> Application:
    db_path = get_db_path()
    engine = init_db(db_path)
    with Session(engine) as session:
        application = Application(
            id=str(uuid4()),
            candidate_id=candidate_id,
            dedupe_key_strong=dedupe_key_strong,
            canonical_url=canonical_url,
            dedupe_key_soft=dedupe_key_soft,
            description_hash=description_hash,
            applied_at=applied_at or utc_now(),
        )
        session.add(application)
        session.commit()
        session.refresh(application)
        return application


def should_skip_recently_applied(
    candidate_id: str,
    *,
    dedupe_key_strong: Optional[str],
    canonical_url: Optional[str],
    dedupe_key_soft: Optional[str],
    description_hash: Optional[str],
    days: int = 7,
) -> bool:
    db_path = get_db_path()
    engine = init_db(db_path)
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    with Session(engine) as session:
        stmt = select(Application).where(Application.candidate_id == candidate_id)
        applications = session.exec(stmt).all()
        for application in applications:
            try:
                applied_at = datetime.fromisoformat(application.applied_at.replace("Z", "+00:00"))
            except ValueError:
                continue
            if applied_at < cutoff:
                continue
            if dedupe_key_strong and application.dedupe_key_strong == dedupe_key_strong:
                return True
            if canonical_url and application.canonical_url == canonical_url:
                return True
            if dedupe_key_soft and description_hash:
                if (
                    application.dedupe_key_soft == dedupe_key_soft
                    and application.description_hash == description_hash
                ):
                    return True
        return False


def mark_skipped_recently_applied(opportunity_id: str, reason: str = "applied_within_7_days") -> JobOpportunity:
    db_path = get_db_path()
    engine = init_db(db_path)
    with Session(engine) as session:
        opportunity = session.get(JobOpportunity, opportunity_id)
        if not opportunity:
            raise ValueError("Opportunity not found.")
        opportunity.is_skipped_recently_applied = True
        opportunity.skip_reason = reason
        session.add(opportunity)
        session.commit()
        session.refresh(opportunity)
        return opportunity


def save_job_fit_evaluation(
    *,
    candidate_id: str,
    job_id: str,
    overall_score: int,
    decision: str,
    subscores: Dict[str, Any],
    top_reasons: list[str],
    gaps: list[str],
    dealbreakers_triggered: list[str],
    model: Optional[str],
    raw_response: Optional[str],
) -> JobFitEvaluation:
    db_path = get_db_path()
    engine = init_db(db_path)
    with Session(engine) as session:
        evaluation = JobFitEvaluation(
            id=str(uuid4()),
            candidate_id=candidate_id,
            job_id=job_id,
            overall_score=overall_score,
            decision=decision,
            subscores_json=json.dumps(subscores),
            top_reasons_json=json.dumps(top_reasons),
            gaps_json=json.dumps(gaps),
            dealbreakers_triggered_json=json.dumps(dealbreakers_triggered),
            created_at=utc_now(),
            model=model,
            raw_response=raw_response,
        )
        session.add(evaluation)
        session.commit()
        session.refresh(evaluation)
        return evaluation

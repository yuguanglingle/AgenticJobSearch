"""Database access for candidate profiles."""

import os
import json
from pathlib import Path
from typing import Optional, List, Dict, Any
from sqlalchemy import text
from sqlmodel import SQLModel, Field, Session, select

from db.utils import get_engine, init_db, ensure_table_column


class Candidate(SQLModel, table=True):
    """Candidate record stored in the shared database.

    Args:
        id: Candidate primary key.
        name: Candidate name.
        email: Candidate email.
        resume_raw: Raw resume text.
        candidate_profile_json: Serialized profile JSON.
        llm_model: Model name.
        prompt_version: Prompt version.
        created_at: ISO timestamp string.
        updated_at: ISO timestamp string.

    Returns:
        None.
    """
    id: str = Field(primary_key=True)
    __table_args__ = {"extend_existing": True}
    name: Optional[str] = None
    email: Optional[str] = None
    resume_raw: str
    candidate_profile_json: str
    llm_model: str
    prompt_version: str
    created_at: str
    updated_at: str


class CandidatePreferences(SQLModel, table=True):
    """Candidate preferences associated with a candidate.

    Args:
        candidate_id: Candidate primary key.
        locations: JSON list string.
        remote_preference: Remote preference string.
        role_targets: JSON list string.
        industries: JSON list string.
        dealbreakers: JSON list string.
        comp_min: Minimum compensation.
        work_auth: Work authorization.
        updated_at: ISO timestamp string.

    Returns:
        None.
    """
    candidate_id: str = Field(primary_key=True, foreign_key="candidate.id")
    __table_args__ = {"extend_existing": True}
    locations: str = "[]"
    remote_preference: Optional[str] = None
    role_targets: str = "[]"
    industries: str = "[]"
    dealbreakers: str = "[]"
    seniority_preference: str = "[]"
    comp_min: Optional[int] = None
    work_auth: Optional[str] = None
    updated_at: str


class AgentRun(SQLModel, table=True):
    """Log of a single agent run invocation.

    Args:
        id: AgentRun primary key.
        candidate_id: Candidate primary key.
        run_id: Agent run id.
        agent_name: Agent name.
        input_json: Serialized input JSON.
        output_json: Serialized output JSON.
        raw_llm_response: Raw LLM response.
        created_at: ISO timestamp string.

    Returns:
        None.
    """
    id: str = Field(primary_key=True)
    __table_args__ = {"extend_existing": True}
    candidate_id: str = Field(foreign_key="candidate.id")
    run_id: str
    agent_name: str
    input_json: str
    output_json: str
    raw_llm_response: Optional[str] = None
    created_at: str


def get_db_path() -> str:
    """Get database path for candidate profile.

    Args:
        None.

    Returns:
        Database path string.
    """
    db_path = os.getenv("DB_PATH")
    if not db_path:
        base_dir = Path(__file__).resolve().parents[2]
        db_path = str(base_dir / "data" / "app.db")
    print(f"[candidate_profile.db] DB_PATH={db_path}")
    return db_path


def save_candidate(
    *,
    candidate_id: str,
    resume_raw: str,
    candidate_profile_json: str,
    llm_model: str,
    prompt_version: str,
    created_at: str,
    updated_at: str,
    preferences: Dict[str, Any],
) -> None:
    """Create or update candidate and preferences.

    Args:
        candidate_id: Candidate primary key.
        resume_raw: Raw resume text.
        candidate_profile_json: Profile JSON string.
        llm_model: Model name.
        prompt_version: Prompt version.
        created_at: ISO timestamp string.
        updated_at: ISO timestamp string.
        preferences: Preferences dict.

    Returns:
        None.
    """
    db_path = get_db_path()
    engine = init_db(db_path)
    with Session(engine) as session:
        _ensure_candidate_preferences_schema(session)
        existing = session.get(Candidate, candidate_id)
        if existing:
            existing.resume_raw = resume_raw
            existing.candidate_profile_json = candidate_profile_json
            existing.llm_model = llm_model
            existing.prompt_version = prompt_version
            existing.updated_at = updated_at
        else:
            session.add(
                Candidate(
                    id=candidate_id,
                    resume_raw=resume_raw,
                    candidate_profile_json=candidate_profile_json,
                    llm_model=llm_model,
                    prompt_version=prompt_version,
                    created_at=created_at,
                    updated_at=updated_at,
                )
            )
        prefs = session.get(CandidatePreferences, candidate_id)
        if prefs:
            prefs.locations = json.dumps(preferences.get("locations", []))
            prefs.remote_preference = preferences.get("remote_preference")
            prefs.role_targets = json.dumps(preferences.get("role_targets", []))
            prefs.industries = json.dumps(preferences.get("industries", []))
            prefs.dealbreakers = json.dumps(preferences.get("dealbreakers", []))
            prefs.seniority_preference = json.dumps(preferences.get("seniority_preference", []))
            prefs.comp_min = preferences.get("comp_min")
            prefs.work_auth = preferences.get("work_auth")
            prefs.updated_at = updated_at
        else:
            session.add(
                CandidatePreferences(
                    candidate_id=candidate_id,
                    locations=json.dumps(preferences.get("locations", [])),
                    remote_preference=preferences.get("remote_preference"),
                    role_targets=json.dumps(preferences.get("role_targets", [])),
                    industries=json.dumps(preferences.get("industries", [])),
                    dealbreakers=json.dumps(preferences.get("dealbreakers", [])),
                    seniority_preference=json.dumps(preferences.get("seniority_preference", [])),
                    comp_min=preferences.get("comp_min"),
                    work_auth=preferences.get("work_auth"),
                    updated_at=updated_at,
                )
            )
        session.commit()


def _ensure_candidate_preferences_schema(session: Session) -> None:
    """Ensure candidatepreferences table has required columns.

    Args:
        session: Active SQLModel session.

    Returns:
        None.
    """
    ensure_table_column(
        session,
        table_name="candidatepreferences",
        column_name="seniority_preference",
        column_definition="TEXT",
    )


def save_agent_run(
    *,
    id: str,
    candidate_id: str,
    run_id: str,
    agent_name: str,
    input_json: str,
    output_json: str,
    raw_llm_response: Optional[str],
    created_at: str,
) -> None:
    """Create or update candidate and preferences.

    Args:
        candidate_id: Candidate primary key.
        resume_raw: Raw resume text.
        candidate_profile_json: Profile JSON string.
        llm_model: Model name.
        prompt_version: Prompt version.
        created_at: ISO timestamp string.
        updated_at: ISO timestamp string.
        preferences: Preferences dict.

    Returns:
        None.
    """
    db_path = get_db_path()
    engine = init_db(db_path)
    with Session(engine) as session:
        session.add(
            AgentRun(
                id=id,
                candidate_id=candidate_id,
                run_id=run_id,
                agent_name=agent_name,
                input_json=input_json,
                output_json=output_json,
                raw_llm_response=raw_llm_response,
                created_at=created_at,
            )
        )
        session.commit()


def list_candidates() -> List[Candidate]:
    """List candidates ordered by updated_at descending.

    Args:
        None.

    Returns:
        List of Candidate records.
    """
    db_path = get_db_path()
    engine = init_db(db_path)
    with Session(engine) as session:
        stmt = select(Candidate).order_by(Candidate.updated_at.desc())
        return list(session.exec(stmt))


def get_candidate(candidate_id: str) -> Optional[Candidate]:
    """Fetch a candidate by id.

    Args:
        candidate_id: Candidate primary key.

    Returns:
        Candidate record or None.
    """
    db_path = get_db_path()
    engine = init_db(db_path)
    with Session(engine) as session:
        return session.get(Candidate, candidate_id)


def get_candidate_preferences(candidate_id: str) -> Optional[CandidatePreferences]:
    """Fetch candidate preferences by candidate id.

    Args:
        candidate_id: Candidate primary key.

    Returns:
        CandidatePreferences record or None.
    """
    db_path = get_db_path()
    engine = init_db(db_path)
    with Session(engine) as session:
        _ensure_candidate_preferences_schema(session)
        return session.get(CandidatePreferences, candidate_id)

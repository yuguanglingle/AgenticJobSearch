import os
import json
from pathlib import Path
from typing import Optional, List, Dict, Any
from sqlmodel import SQLModel, Field, create_engine, Session, select


class Candidate(SQLModel, table=True):
    id: str = Field(primary_key=True)
    name: Optional[str] = None
    email: Optional[str] = None
    resume_raw: str
    candidate_profile_json: str
    llm_model: str
    prompt_version: str
    created_at: str
    updated_at: str


class CandidatePreferences(SQLModel, table=True):
    candidate_id: str = Field(primary_key=True, foreign_key="candidate.id")
    locations: str = "[]"
    remote_preference: Optional[str] = None
    role_targets: str = "[]"
    industries: str = "[]"
    dealbreakers: str = "[]"
    comp_min: Optional[int] = None
    work_auth: Optional[str] = None
    updated_at: str


class AgentRun(SQLModel, table=True):
    id: str = Field(primary_key=True)
    candidate_id: str = Field(foreign_key="candidate.id")
    run_id: str
    agent_name: str
    input_json: str
    output_json: str
    raw_llm_response: Optional[str] = None
    created_at: str


def get_engine() -> Any:
    db_path = os.getenv("DB_PATH")
    if not db_path:
        base_dir = Path(__file__).resolve().parents[1]
        db_path = str(base_dir / "data" / "app.db")
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    return create_engine(f"sqlite:///{db_path}")


def init_db() -> Any:
    engine = get_engine()
    SQLModel.metadata.create_all(engine)
    return engine


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
    engine = init_db()
    with Session(engine) as session:
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
                    comp_min=preferences.get("comp_min"),
                    work_auth=preferences.get("work_auth"),
                    updated_at=updated_at,
                )
            )
        session.commit()


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
    engine = init_db()
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
    engine = init_db()
    with Session(engine) as session:
        stmt = select(Candidate).order_by(Candidate.updated_at.desc())
        return list(session.exec(stmt))


def get_candidate(candidate_id: str) -> Optional[Candidate]:
    engine = init_db()
    with Session(engine) as session:
        return session.get(Candidate, candidate_id)


def get_candidate_preferences(candidate_id: str) -> Optional[CandidatePreferences]:
    engine = init_db()
    with Session(engine) as session:
        return session.get(CandidatePreferences, candidate_id)

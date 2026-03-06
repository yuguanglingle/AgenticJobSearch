"""Streamlit UI for setup wizard, pipeline runs, and opportunity review."""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from uuid import uuid4

import streamlit as st
from dotenv import dotenv_values, load_dotenv, set_key
from openai import OpenAI
from sqlmodel import Session, select

BASE_DIR = Path(__file__).resolve().parent
AGENTS_DIR = BASE_DIR.parent
ROOT_DIR = AGENTS_DIR.parent
ENV_PATH = ROOT_DIR / ".env"

if str(AGENTS_DIR) not in sys.path:
    sys.path.insert(0, str(AGENTS_DIR))
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

load_dotenv(ENV_PATH)

from app.runtime import run_pipeline_command
from candidate_profile.src import db as candidate_db
from candidate_profile.src.agent import generate_candidate_profile
from candidate_profile.src.models import CandidatePreferences, CandidateProfileRequest
from job_match import db as job_match_db
from job_match.state_machine import JobState
from job_search import db as job_search_db
from job_search.job_search_client import DEFAULT_CONFIG, build_payload, call_theirstack
from orchestrator import state as orchestrator_state
from orchestrator.profile_config import (
    apply_profile_env,
    get_default_profile,
    list_profiles,
    load_profile_config,
    resolve_db_path,
    resolve_logs_dir,
    save_profile_config,
    set_default_profile,
)
from orchestrator.theirstack_overrides import (
    DEFAULT_INDUSTRIES,
    DEFAULT_LOCATION_PATTERNS,
    DEFAULT_ROLE_TARGETS,
    DEFAULT_SENIORITY,
)


st.set_page_config(page_title="Agentic Job Search", layout="wide")
st.title("Agentic Job Search")
st.caption("Setup wizard + local pipeline runner")


def _split_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _candidate_shell_json(headline: str, skills: list[str], domains: list[str]) -> str:
    payload = {
        "ok": True,
        "agent": "CandidateProfileAgent",
        "run_id": str(uuid4()),
        "timestamp": _now_iso(),
        "result": {
            "candidate_profile": {
                "headline": headline or "Candidate profile",
                "seniority_estimate": "mid",
                "core_skills": skills,
                "domains": domains,
                "experience_highlights": [],
                "keywords_for_search": list(dict.fromkeys(skills + domains)),
                "tone_style": {"voice": "direct", "length": "short"},
            }
        },
        "confidence": 0.3,
        "evidence": [],
        "next_actions": [],
        "questions_for_user": [],
    }
    return json.dumps(payload)


def _save_candidate_shell(candidate_id: str, resume_text: str, prefs: CandidatePreferences) -> None:
    candidate_db.save_candidate(
        candidate_id=candidate_id,
        resume_raw=resume_text,
        candidate_profile_json=_candidate_shell_json(
            headline="Candidate generated from setup wizard",
            skills=prefs.role_targets or ["python"],
            domains=prefs.industries or ["general"],
        ),
        llm_model="manual",
        prompt_version="manual",
        created_at=_now_iso(),
        updated_at=_now_iso(),
        preferences=prefs.model_dump(),
    )


def _load_candidates() -> list[str]:
    return [candidate.id for candidate in candidate_db.list_candidates()]


def _save_keys_to_env(openai_key: str, theirstack_key: str) -> None:
    ENV_PATH.touch(exist_ok=True)
    if openai_key:
        set_key(str(ENV_PATH), "OPENAI_API_KEY", openai_key)
    if theirstack_key:
        set_key(str(ENV_PATH), "THEIRSTACK_API_KEY", theirstack_key)
    load_dotenv(ENV_PATH, override=True)


def _test_openai_key(api_key: str) -> tuple[bool, str]:
    if not api_key:
        return False, "Missing OPENAI_API_KEY"
    try:
        client = OpenAI(api_key=api_key)
        models = client.models.list()
        model_count = len(getattr(models, "data", []) or [])
        return True, f"Connected. Model list returned ({model_count} entries in first page)."
    except Exception as exc:
        return False, f"OpenAI connection failed: {exc}"


def _test_theirstack_key(api_key: str) -> tuple[bool, str]:
    if not api_key:
        return False, "Missing THEIRSTACK_API_KEY"
    try:
        payload = build_payload()
        payload["limit"] = 1
        payload["page"] = 0
        response = call_theirstack(api_key, payload)
        count = len(response.get("data", []))
        return True, f"Connected. Retrieved {count} job(s)."
    except Exception as exc:
        return False, f"TheirStack connection failed: {exc}"


def _load_opportunities(candidate_id: str) -> list[job_match_db.JobOpportunity]:
    db_path = job_match_db.get_db_path()
    engine = job_match_db.init_db(db_path)
    with Session(engine) as session:
        stmt = select(job_match_db.JobOpportunity).where(job_match_db.JobOpportunity.candidate_id == candidate_id)
        return list(session.exec(stmt))


def _load_jobs(job_ids: list[str]) -> dict[str, job_search_db.Job]:
    if not job_ids:
        return {}
    db_path = job_search_db.get_db_path()
    engine = job_search_db.init_db(db_path)
    with Session(engine) as session:
        stmt = select(job_search_db.Job).where(job_search_db.Job.id.in_(job_ids))
        return {job.id: job for job in session.exec(stmt)}


def _latest_fit_evaluations(candidate_id: str, job_ids: list[str]) -> dict[str, job_match_db.JobFitEvaluation]:
    if not job_ids:
        return {}
    db_path = job_match_db.get_db_path()
    engine = job_match_db.init_db(db_path)
    latest: dict[str, job_match_db.JobFitEvaluation] = {}
    with Session(engine) as session:
        stmt = select(job_match_db.JobFitEvaluation).where(
            job_match_db.JobFitEvaluation.candidate_id == candidate_id,
            job_match_db.JobFitEvaluation.job_id.in_(job_ids),
        )
        for evaluation in session.exec(stmt):
            current = latest.get(evaluation.job_id)
            if not current or evaluation.created_at > current.created_at:
                latest[evaluation.job_id] = evaluation
    return latest


def _state_rank(value: Optional[str]) -> int:
    order = {
        JobState.SCREENED.value: 0,
        JobState.APPROVED.value: 1,
        JobState.APPLIED.value: 2,
        JobState.DISCOVERED.value: 3,
        JobState.CLOSED.value: 4,
    }
    return order.get(value or "", 99)


profiles = list_profiles()
default_profile = get_default_profile() or "default"
profile_options = sorted(set([default_profile] + profiles))
if "active_profile" not in st.session_state:
    st.session_state.active_profile = default_profile
if st.session_state.active_profile not in profile_options:
    st.session_state.active_profile = default_profile

st.sidebar.header("Profile")
active_profile = st.sidebar.selectbox("Active profile", options=profile_options, key="active_profile")

profile_config: dict = {}
try:
    profile_config = load_profile_config(active_profile) if active_profile in profiles else {}
except Exception as exc:
    st.sidebar.error(f"Profile load failed: {exc}")

try:
    db_path, logs_dir = apply_profile_env(active_profile, profile_config)
    st.sidebar.caption(f"DB: {db_path}")
    st.sidebar.caption(f"Logs: {logs_dir}")
except Exception as exc:
    st.sidebar.error(f"Failed to apply profile env: {exc}")

if st.sidebar.button("Set as default"):
    set_default_profile(active_profile)
    st.sidebar.success(f"Default profile set to {active_profile}")

if "last_run_result" not in st.session_state:
    st.session_state.last_run_result = None

setup_tab, run_tab, review_tab = st.tabs(["Setup Wizard", "Run Pipeline", "Review Jobs"])

with setup_tab:
    st.subheader("1) Create Profile")
    with st.form("profile_form"):
        profile_name = st.text_input("Profile name", value=active_profile)
        candidate_id_for_profile = st.text_input("Default candidate id (optional)", value=str(profile_config.get("candidate_id", "")))
        limit_to_score = st.number_input(
            "Default limit_to_score",
            min_value=1,
            value=int(profile_config.get("limit_to_score", 50)),
        )
        db_path_input = st.text_input(
            "DB path",
            value=str(resolve_db_path(profile_name or "default", profile_config)),
        )
        logs_dir_input = st.text_input(
            "Logs dir",
            value=str(resolve_logs_dir(profile_name or "default", profile_config)),
        )
        provider_json = st.text_area(
            "Provider config JSON",
            value=json.dumps(profile_config.get("provider_config") or DEFAULT_CONFIG, indent=2),
            height=180,
        )
        save_as_default = st.checkbox("Set as default after save", value=True)
        save_profile = st.form_submit_button("Save profile")

    if save_profile:
        if not profile_name.strip():
            st.error("Profile name is required.")
        else:
            try:
                provider_config = json.loads(provider_json)
                new_config = {
                    "candidate_id": candidate_id_for_profile.strip(),
                    "limit_to_score": int(limit_to_score),
                    "provider_config": provider_config,
                    "db_path": db_path_input.strip(),
                    "logs_dir": logs_dir_input.strip(),
                }
                save_profile_config(profile_name.strip(), new_config)
                if save_as_default:
                    set_default_profile(profile_name.strip())
                st.success(f"Saved profile: {profile_name.strip()}")
            except json.JSONDecodeError as exc:
                st.error(f"Invalid provider config JSON: {exc}")

    st.subheader("2) Add API Keys")
    env_values = dotenv_values(ENV_PATH)
    openai_key = st.text_input(
        "OPENAI_API_KEY",
        value=str(env_values.get("OPENAI_API_KEY", os.getenv("OPENAI_API_KEY", ""))),
        type="password",
    )
    theirstack_key = st.text_input(
        "THEIRSTACK_API_KEY",
        value=str(env_values.get("THEIRSTACK_API_KEY", os.getenv("THEIRSTACK_API_KEY", ""))),
        type="password",
    )
    if st.button("Save API keys to .env"):
        _save_keys_to_env(openai_key.strip(), theirstack_key.strip())
        st.success(f"Saved keys to {ENV_PATH}")

    col_openai, col_theirstack = st.columns(2)
    with col_openai:
        if st.button("Test OpenAI connection"):
            ok, message = _test_openai_key(openai_key.strip() or os.getenv("OPENAI_API_KEY", ""))
            if ok:
                st.success(message)
            else:
                st.error(message)
    with col_theirstack:
        if st.button("Test TheirStack connection"):
            ok, message = _test_theirstack_key(theirstack_key.strip() or os.getenv("THEIRSTACK_API_KEY", ""))
            if ok:
                st.success(message)
            else:
                st.error(message)

    st.subheader("3) Create Candidate")
    candidate_options = _load_candidates()
    existing_candidate = st.selectbox("Existing candidate", options=["(new)"] + candidate_options)
    candidate_id = str(uuid4()) if existing_candidate == "(new)" else existing_candidate
    candidate_id = st.text_input("Candidate id", value=candidate_id)

    resume_text = st.text_area("Resume text", height=220, value="")
    locations = st.text_input("Locations (comma separated)", value=", ".join(DEFAULT_LOCATION_PATTERNS))
    remote_preference = st.selectbox("Remote preference", options=["any", "remote", "hybrid", "onsite"], index=0)
    role_targets = st.text_input("Role targets", value=", ".join(DEFAULT_ROLE_TARGETS))
    industries = st.text_input("Industries", value=", ".join(DEFAULT_INDUSTRIES))
    seniority = st.multiselect(
        "Seniority",
        options=["junior", "mid_level", "senior", "staff", "executive"],
        default=list(DEFAULT_SENIORITY),
    )

    prefs = CandidatePreferences(
        locations=_split_csv(locations),
        remote_preference=None if remote_preference == "any" else remote_preference,
        role_targets=_split_csv(role_targets),
        industries=_split_csv(industries),
        seniority_preference=seniority,
    )

    create_col1, create_col2 = st.columns(2)
    with create_col1:
        if st.button("Create/Update candidate (no LLM)"):
            if not candidate_id.strip():
                st.error("Candidate id is required.")
            else:
                _save_candidate_shell(candidate_id.strip(), resume_text or "", prefs)
                st.success(f"Candidate saved: {candidate_id.strip()}")
    with create_col2:
        if st.button("Generate candidate profile with OpenAI"):
            if not resume_text.strip():
                st.error("Resume text is required for LLM profile generation.")
            elif not candidate_id.strip():
                st.error("Candidate id is required.")
            else:
                try:
                    request = CandidateProfileRequest(
                        candidate_id=candidate_id.strip(),
                        resume_text=resume_text,
                        preferences=prefs,
                    )
                    envelope, _, _ = generate_candidate_profile(request)
                    st.success("Candidate profile generated and saved.")
                    st.json(json.loads(envelope.model_dump_json()))
                except Exception as exc:
                    st.error(f"Profile generation failed: {exc}")

    st.subheader("4) Run Now + Daily Scheduling")
    st.code(f"python -m app run --profile {active_profile}")
    st.code(f"python -m app daily --profile {active_profile}")
    st.markdown("Windows Task Scheduler: create a daily task that runs `python -m app daily --profile <profile>`." )
    st.markdown("macOS/Linux cron: add `0 8 * * * cd <repo> && python -m app daily --profile <profile>`." )

with run_tab:
    st.subheader("Run Pipeline")
    candidate_options = _load_candidates()
    profile_candidate = str(profile_config.get("candidate_id", "")).strip()
    default_candidate = profile_candidate if profile_candidate else (candidate_options[0] if candidate_options else "")
    selected_candidate = st.text_input("Candidate id", value=default_candidate)
    limit_override = st.number_input(
        "limit_to_score override",
        min_value=1,
        value=int(profile_config.get("limit_to_score", 50)),
    )

    if st.button("Run now"):
        try:
            result = run_pipeline_command(
                command_name="run",
                profile_name=active_profile,
                candidate_id=selected_candidate.strip() or None,
                limit_to_score=int(limit_override),
            )
            st.session_state.last_run_result = result
            st.success("Pipeline run completed.")
            st.json(result)
        except Exception as exc:
            st.error(f"Pipeline failed: {exc}")

    if st.session_state.last_run_result:
        st.caption(f"Last log file: {st.session_state.last_run_result.get('log_file')}")

with review_tab:
    st.subheader("Review Opportunities")
    review_candidates = _load_candidates()
    if not review_candidates:
        st.info("No candidates found yet. Create one in Setup Wizard.")
    else:
        review_candidate = st.selectbox("Candidate", options=review_candidates)
        opportunities = _load_opportunities(review_candidate)
        if not opportunities:
            st.info("No opportunities yet for this candidate.")
        else:
            opportunities.sort(key=lambda item: (_state_rank(item.state), -(item.fit_score or -1)))
            job_ids = [item.job_id for item in opportunities]
            jobs = _load_jobs(job_ids)
            evaluations = _latest_fit_evaluations(review_candidate, job_ids)

            for opp in opportunities:
                job = jobs.get(opp.job_id)
                title = job.job_title if job else "Unknown role"
                company = job.company if job else "Unknown company"
                st.markdown(f"### {company} - {title}")
                st.write(f"State: {opp.state} | Score: {opp.fit_score} | Bucket: {opp.screen_bucket}")
                if job:
                    st.write(f"Location: {job.location or 'N/A'}")
                    st.write(f"URL: {job.canonical_url or job.url or 'N/A'}")
                evaluation = evaluations.get(opp.job_id)
                if evaluation:
                    try:
                        reasons = json.loads(evaluation.top_reasons_json)
                    except Exception:
                        reasons = []
                    if reasons:
                        st.write("Top reasons: " + ", ".join(reasons))

                col1, col2, col3 = st.columns(3)
                with col1:
                    if st.button("Approve", key=f"approve_{opp.id}"):
                        orchestrator_state.approve(opp.id)
                        st.rerun()
                with col2:
                    if st.button("Close", key=f"close_{opp.id}"):
                        orchestrator_state.close(opp.id)
                        st.rerun()
                with col3:
                    if st.button("Mark Applied", key=f"applied_{opp.id}"):
                        orchestrator_state.mark_applied(opp.id)
                        st.rerun()

"""Streamlit UI for setup wizard, pipeline runs, and opportunity review."""

from __future__ import annotations

import json
import os
import random
import sys
from datetime import date, datetime, timezone
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
from orchestrator.review_ui import (
    DATE_FIELD_LABELS,
    PRIMARY_STATUS_METRICS,
    build_review_items,
    filter_review_items,
    group_items_by_date,
    group_items_by_state,
    summarize_states,
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
st.markdown(
    """
    <style>
    div[data-baseweb="tab-list"] button,
    button[data-baseweb="tab"],
    button[role="tab"] {
        font-size: 1.15rem !important;
        font-weight: 600 !important;
        min-height: 3rem !important;
        padding: 0.6rem 1rem !important;
    }
    div[data-baseweb="tab-list"] {
        gap: 0.65rem;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


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


def _generate_friendly_name() -> str:
    adjectives = ["Focused", "Curious", "Pragmatic", "Bold", "Strategic", "Steady", "Driven"]
    nouns = ["Builder", "Analyst", "Operator", "Engineer", "Planner", "Scout", "Creator"]
    return f"{random.choice(adjectives)} {random.choice(nouns)}"


def _load_candidate_display_map() -> dict[str, str]:
    try:
        candidates = candidate_db.list_candidates()
    except Exception as exc:
        st.error(f"Failed to load candidates: {exc}")
        return {}
    if not candidates:
        return {}
    used: dict[str, int] = {}
    display_to_id: dict[str, str] = {}
    for index, candidate in enumerate(candidates, start=1):
        base = (candidate.name or "").strip() or f"Candidate {index}"
        used[base] = used.get(base, 0) + 1
        suffix = used[base]
        display_name = base if suffix == 1 else f"{base} ({suffix})"
        display_to_id[display_name] = candidate.id
    return display_to_id


def _set_candidate_friendly_name(candidate_id: str, friendly_name: str) -> None:
    try:
        db_path = candidate_db.get_db_path()
        engine = candidate_db.init_db(db_path)
        with Session(engine) as session:
            candidate = session.get(candidate_db.Candidate, candidate_id)
            if not candidate:
                return
            candidate.name = friendly_name.strip() or None
            candidate.updated_at = _now_iso()
            session.add(candidate)
            session.commit()
    except Exception as exc:
        st.error(f"Failed to save candidate name: {exc}")


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


def _render_status_metrics(opportunities: list[job_match_db.JobOpportunity]) -> None:
    counts = summarize_states(opportunities)
    metric_columns = st.columns(len(PRIMARY_STATUS_METRICS) + 1)
    for index, state in enumerate(PRIMARY_STATUS_METRICS):
        metric_columns[index].metric(state.title(), counts.get(state, 0))
    metric_columns[-1].metric("Total", len(opportunities))


def _render_opportunity_card(item, *, key_prefix: str) -> None:
    opp = item.opportunity
    job = item.job
    evaluation = item.evaluation
    title = job.job_title if job else "Unknown role"
    company = job.company if job else "Unknown company"
    header = f"{company} - {title}"
    with st.expander(header, expanded=False):
        st.write(
            f"State: {opp.state} | Score: {opp.fit_score} | Bucket: {opp.screen_bucket or 'N/A'}"
        )
        st.write(f"{item.selected_date_label}: {item.selected_date_text}")
        if getattr(opp, "skip_reason", None):
            st.write(f"Close reason: {opp.skip_reason}")
        if job:
            st.write(f"Location: {job.location or 'N/A'}")
            st.write(f"URL: {job.canonical_url or job.url or 'N/A'}")
        if evaluation:
            try:
                reasons = json.loads(evaluation.top_reasons_json)
            except Exception:
                reasons = []
            if reasons:
                st.write("Top reasons: " + ", ".join(reasons))

        col1, col2, col3 = st.columns(3)
        with col1:
            if opp.state == JobState.SCREENED.value:
                if st.button("Approve", key=f"{key_prefix}_approve_{opp.id}"):
                    orchestrator_state.approve(opp.id)
                    st.rerun()
        with col2:
            if opp.state != JobState.CLOSED.value:
                if st.button("Close", key=f"{key_prefix}_close_{opp.id}"):
                    orchestrator_state.close(opp.id)
                    st.rerun()
        with col3:
            if opp.state == JobState.APPROVED.value:
                if st.button("Mark Applied", key=f"{key_prefix}_applied_{opp.id}"):
                    orchestrator_state.mark_applied(opp.id)
                    st.rerun()


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
    profile_candidate_map = _load_candidate_display_map()
    profile_candidate_options = ["(none)"] + list(profile_candidate_map.keys())
    profile_candidate_id_current = str(profile_config.get("candidate_id", "")).strip()
    profile_candidate_reverse = {value: key for key, value in profile_candidate_map.items()}
    default_candidate_label = profile_candidate_reverse.get(profile_candidate_id_current, "(none)")
    default_candidate_index = (
        profile_candidate_options.index(default_candidate_label)
        if default_candidate_label in profile_candidate_options
        else 0
    )
    with st.form("profile_form"):
        profile_name = st.text_input("Profile name", value=active_profile)
        default_candidate_label = st.selectbox(
            "Default candidate",
            options=profile_candidate_options,
            index=default_candidate_index,
            help="Friendly names are shown here. IDs are stored internally.",
            key="setup_default_candidate_select",
        )
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
                candidate_id_for_profile = (
                    profile_candidate_map.get(default_candidate_label, "")
                    if default_candidate_label != "(none)"
                    else ""
                )
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
    st.caption(
        "Each candidate is tied to a resume and preferences. One person can keep multiple candidates "
        "(for example different resume versions)."
    )
    candidate_display_map = _load_candidate_display_map()
    candidate_display_options = list(candidate_display_map.keys())
    candidate_mode = st.radio(
        "Candidate mode",
        options=["Create new candidate", "Update existing candidate"],
        horizontal=True,
    )
    if "new_candidate_friendly_name" not in st.session_state:
        st.session_state.new_candidate_friendly_name = _generate_friendly_name()

    active_candidate_id: Optional[str] = None
    friendly_name_default = st.session_state.new_candidate_friendly_name
    resume_default = ""
    if candidate_mode == "Update existing candidate":
        if not candidate_display_options:
            st.info("No candidates available yet. Switch to 'Create new candidate' first.")
        else:
            selected_candidate_display = st.selectbox(
                "Candidate",
                options=candidate_display_options,
                key="setup_existing_candidate_select",
            )
            active_candidate_id = candidate_display_map[selected_candidate_display]
            try:
                existing_candidate = candidate_db.get_candidate(active_candidate_id)
            except Exception as exc:
                existing_candidate = None
                st.error(f"Failed to load candidate: {exc}")
            if existing_candidate:
                friendly_name_default = (existing_candidate.name or "").strip() or selected_candidate_display
                resume_default = existing_candidate.resume_raw or ""

    friendly_name = st.text_input(
        "Candidate friendly name",
        value=friendly_name_default,
        help="Use a memorable label like 'Data Resume v2' or 'Backend Focus'.",
    )
    resume_text = st.text_area("Resume text", height=220, value=resume_default)
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
            if not friendly_name.strip():
                st.error("Candidate friendly name is required.")
            else:
                resolved_candidate_id = active_candidate_id or str(uuid4())
                _save_candidate_shell(resolved_candidate_id, resume_text or "", prefs)
                _set_candidate_friendly_name(resolved_candidate_id, friendly_name)
                st.success(f"Candidate saved: {friendly_name.strip()}")
                if candidate_mode == "Create new candidate":
                    st.session_state.new_candidate_friendly_name = _generate_friendly_name()
                st.rerun()
    with create_col2:
        if st.button("Generate candidate profile with OpenAI"):
            if not resume_text.strip():
                st.error("Resume text is required for LLM profile generation.")
            elif not friendly_name.strip():
                st.error("Candidate friendly name is required.")
            else:
                try:
                    resolved_candidate_id = active_candidate_id or str(uuid4())
                    request = CandidateProfileRequest(
                        candidate_id=resolved_candidate_id,
                        resume_text=resume_text,
                        preferences=prefs,
                    )
                    envelope, _, _ = generate_candidate_profile(request)
                    _set_candidate_friendly_name(resolved_candidate_id, friendly_name)
                    st.success("Candidate profile generated and saved.")
                    st.json(json.loads(envelope.model_dump_json()))
                    if candidate_mode == "Create new candidate":
                        st.session_state.new_candidate_friendly_name = _generate_friendly_name()
                    st.rerun()
                except Exception as exc:
                    st.error(f"Profile generation failed: {exc}")

    st.subheader("4) Run Now + Daily Scheduling")
    st.code(f"python -m app run --profile {active_profile}")
    st.code(f"python -m app daily --profile {active_profile}")
    st.markdown("Windows Task Scheduler: create a daily task that runs `python -m app daily --profile <profile>`." )
    st.markdown("macOS/Linux cron: add `0 8 * * * cd <repo> && python -m app daily --profile <profile>`." )

with run_tab:
    st.subheader("Run Pipeline")
    candidate_display_map = _load_candidate_display_map()
    candidate_options = list(candidate_display_map.keys())
    if not candidate_options:
        st.info("No candidates found. Create one in Setup Wizard first.")
    else:
        profile_candidate = str(profile_config.get("candidate_id", "")).strip()
        reverse_map = {value: key for key, value in candidate_display_map.items()}
        default_label = reverse_map.get(profile_candidate, candidate_options[0])
        selected_candidate_label = st.selectbox(
            "Candidate",
            options=candidate_options,
            index=candidate_options.index(default_label) if default_label in candidate_options else 0,
            key="run_candidate_select",
        )
        selected_candidate = candidate_display_map[selected_candidate_label]
        st.caption("Candidate IDs are hidden in the UI. The selected friendly name maps to an internal candidate ID.")
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
    review_display_map = _load_candidate_display_map()
    review_options = list(review_display_map.keys())
    if not review_options:
        st.info("No candidates found yet. Create one in Setup Wizard.")
    else:
        review_candidate_label = st.selectbox(
            "Candidate",
            options=review_options,
            key="review_candidate_select",
        )
        review_candidate = review_display_map[review_candidate_label]
        opportunities = _load_opportunities(review_candidate)
        if not opportunities:
            st.info("No opportunities yet for this candidate.")
        else:
            opportunities.sort(key=lambda item: (_state_rank(item.state), -(item.fit_score or -1)))
            job_ids = [item.job_id for item in opportunities]
            jobs = _load_jobs(job_ids)
            evaluations = _latest_fit_evaluations(review_candidate, job_ids)
            _render_status_metrics(opportunities)

            all_states = [
                JobState.DISCOVERED.value,
                JobState.SCREENED.value,
                JobState.APPROVED.value,
                JobState.APPLIED.value,
                JobState.CLOSED.value,
            ]
            filter_col1, filter_col2, filter_col3 = st.columns([1.4, 1, 1])
            with filter_col1:
                state_filter = st.multiselect(
                    "Status filter",
                    options=all_states,
                    default=all_states,
                    key="review_status_filter",
                )
            with filter_col2:
                date_field = st.selectbox(
                    "Track jobs by date",
                    options=list(DATE_FIELD_LABELS.keys()),
                    format_func=lambda key: DATE_FIELD_LABELS[key],
                    index=0,
                    key="review_date_field",
                )
            review_items = build_review_items(opportunities, jobs, evaluations, date_field)
            known_dates = sorted(
                {item.selected_date_value for item in review_items if item.selected_date_value is not None}
            )
            default_start = known_dates[0] if known_dates else None
            default_end = known_dates[-1] if known_dates else None
            with filter_col3:
                start_date = st.date_input(
                    "From date",
                    value=default_start,
                    key="review_start_date",
                ) if default_start else None
            end_date = st.date_input(
                "To date",
                value=default_end,
                key="review_end_date",
            ) if default_end else None

            filtered_items = filter_review_items(
                review_items,
                selected_states=state_filter,
                start_date=start_date if isinstance(start_date, date) else None,
                end_date=end_date if isinstance(end_date, date) else None,
            )
            st.caption(
                f"Showing {len(filtered_items)} of {len(opportunities)} opportunities by "
                f"{DATE_FIELD_LABELS[date_field].lower()}."
            )
            if not filtered_items:
                st.info("No opportunities match the current filters.")
            else:
                status_tab, date_tab = st.tabs(["By Status", "By Date"])
                with status_tab:
                    grouped_by_state = group_items_by_state(filtered_items)
                    for state in all_states:
                        items = grouped_by_state.get(state, [])
                        if not items:
                            continue
                        st.markdown(f"### {state} ({len(items)})")
                        for item in items:
                            _render_opportunity_card(item, key_prefix=f"status_{state.lower()}")
                with date_tab:
                    grouped_by_date = group_items_by_date(filtered_items)
                    sortable_dates = sorted(
                        grouped_by_date.keys(),
                        key=lambda value: (value == "Unknown", value),
                        reverse=True,
                    )
                    for date_key in sortable_dates:
                        items = grouped_by_date[date_key]
                        st.markdown(f"### {DATE_FIELD_LABELS[date_field]}: {date_key} ({len(items)})")
                        for item in items:
                            _render_opportunity_card(item, key_prefix=f"date_{date_key}")

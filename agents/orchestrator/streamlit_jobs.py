"""Minimal Streamlit UI for running and reviewing the job pipeline."""

import json
import os
import socket
import subprocess
import sys
from uuid import uuid4
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
import streamlit as st
from sqlmodel import Session, select

BASE_DIR = Path(__file__).resolve().parent
AGENTS_DIR = BASE_DIR.parent
ROOT_DIR = AGENTS_DIR.parent
if str(AGENTS_DIR) not in sys.path:
    sys.path.insert(0, str(AGENTS_DIR))

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
from job_search.job_search_client import DEFAULT_CONFIG, build_payload

load_dotenv(BASE_DIR / ".env")
load_dotenv(AGENTS_DIR / ".env")

st.set_page_config(page_title="Agentic Jobs Search", layout="wide")
st.title("Agentic Jobs Application: Search and Review Your Next Role")
st.caption(f"Server port: {st.get_option('server.port')}")

st.header("Profile")
profiles = list_profiles()
default_profile = get_default_profile()
profile_options = ["(none)"] + profiles
if "selected_profile" not in st.session_state:
    st.session_state.selected_profile = default_profile or "(none)"
if st.session_state.selected_profile not in profile_options:
    st.session_state.selected_profile = "(none)"
if "pending_profile" in st.session_state:
    pending = st.session_state.pop("pending_profile")
    if pending in profile_options:
        st.session_state.selected_profile = pending

selected_profile = st.selectbox(
    "Active profile",
    options=profile_options,
    index=profile_options.index(st.session_state.selected_profile)
    if st.session_state.selected_profile in profile_options
    else 0,
    key="selected_profile",
)

profile_config: dict = {}
if selected_profile != "(none)":
    try:
        profile_config = load_profile_config(selected_profile)
        db_path, logs_dir = apply_profile_env(selected_profile, profile_config)
        st.caption(f"DB: {db_path}")
        st.caption(f"Logs: {logs_dir}")
    except Exception as exc:
        st.error(f"Failed to load profile {selected_profile}: {exc}")
        profile_config = {}

if selected_profile != "(none)":
    col_a, col_b = st.columns(2)
    with col_a:
        if st.button("Set as default"):
            set_default_profile(selected_profile)
            st.success(f"Default profile set to {selected_profile}.")
            st.rerun()
    with col_b:
        if default_profile:
            st.caption(f"Current default: {default_profile}")
        else:
            st.caption("No default profile set.")
else:
    st.info("No profile selected. Create or choose a profile to isolate data and logs.")

with st.expander("Create or Update Profile"):
    name_default = selected_profile if selected_profile != "(none)" else ""
    profile_name = st.text_input("Profile name", value=name_default)
    existing_config = profile_config if profile_name == selected_profile else {}

    db_default = resolve_db_path(profile_name or "default", existing_config)
    logs_default = resolve_logs_dir(profile_name or "default", existing_config)

    limit_default = int(existing_config.get("limit_to_score", 50))
    limit_to_score_input = st.number_input("Limit to score (default)", min_value=1, value=limit_default)
    db_path_input = st.text_input("DB path", value=str(db_default))
    logs_dir_input = st.text_input("Logs dir", value=str(logs_default))
    provider_config_input = st.text_area(
        "Provider config (JSON)",
        value=json.dumps(existing_config.get("provider_config") or DEFAULT_CONFIG, indent=2),
        height=160,
    )
    set_default = st.checkbox("Set as default after save", value=False)

    if st.button("Save profile"):
        if not profile_name.strip():
            st.error("Profile name is required.")
        else:
            try:
                provider_config = json.loads(provider_config_input)
            except json.JSONDecodeError as exc:
                st.error(f"Invalid provider config JSON: {exc}")
            else:
                new_config = {
                    "limit_to_score": int(limit_to_score_input),
                    "provider_config": provider_config,
                    "db_path": db_path_input.strip(),
                    "logs_dir": logs_dir_input.strip(),
                }
                save_profile_config(profile_name.strip(), new_config)
                if set_default:
                    set_default_profile(profile_name.strip())
                st.success(f"Profile saved: {profile_name.strip()}")
                st.session_state.pending_profile = profile_name.strip()
                st.rerun()

if not os.getenv("DB_PATH"):
    os.environ["DB_PATH"] = str(AGENTS_DIR / "data" / "app.db")
    st.info("Using legacy DB at agents/data/app.db. Create/select a profile to isolate data.")

if "legacy_db_warned" not in st.session_state:
    st.session_state.legacy_db_warned = False

legacy_db = AGENTS_DIR / "data" / "app.db"
if legacy_db.exists() and not st.session_state.legacy_db_warned:
    st.warning(f"Legacy DB detected at {legacy_db}. Current DB is {os.environ.get('DB_PATH')}.")
    st.session_state.legacy_db_warned = True

from candidate_profile.src import db as candidate_db
from candidate_profile.src.agent import generate_candidate_profile
from candidate_profile.src.models import CandidateProfileRequest, CandidatePreferences
from job_match import db as job_match_db
from job_match.state_machine import JobState
from job_search import db as job_search_db
from orchestrator import pipeline, state as orchestrator_state
from orchestrator.theirstack_overrides import (
    DEFAULT_INDUSTRIES,
    DEFAULT_LOCATION_PATTERNS,
    DEFAULT_REMOTE,
    DEFAULT_ROLE_TARGETS,
    DEFAULT_SENIORITY,
    apply_theirstack_overrides,
)

if "last_pipeline_stats" not in st.session_state:
    st.session_state.last_pipeline_stats = None
if "loaded_candidate_id" not in st.session_state:
    st.session_state.loaded_candidate_id = None
if "last_theirstack_payload" not in st.session_state:
    st.session_state.last_theirstack_payload = None

# Default options in UI (seeded from TheirStack payload defaults).
if "pref_locations" not in st.session_state:
    st.session_state.pref_locations = ", ".join(DEFAULT_LOCATION_PATTERNS)
if "pref_remote_preference" not in st.session_state:
    st.session_state.pref_remote_preference = DEFAULT_REMOTE or "any"
if "pref_role_targets" not in st.session_state:
    st.session_state.pref_role_targets = ", ".join(DEFAULT_ROLE_TARGETS)
if "pref_industries" not in st.session_state:
    st.session_state.pref_industries = ", ".join(DEFAULT_INDUSTRIES)
if "pref_seniority" not in st.session_state:
    st.session_state.pref_seniority = list(DEFAULT_SENIORITY)


def _load_candidates() -> list[str]:
    candidates = candidate_db.list_candidates()
    return [candidate.id for candidate in candidates]


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
        evaluations = session.exec(stmt).all()
        for evaluation in evaluations:
            current = latest.get(evaluation.job_id)
            if not current or evaluation.created_at > current.created_at:
                latest[evaluation.job_id] = evaluation
    return latest


def _load_opportunities(candidate_id: str, states: Optional[list[str]] = None) -> list[job_match_db.JobOpportunity]:
    db_path = job_match_db.get_db_path()
    engine = job_match_db.init_db(db_path)
    with Session(engine) as session:
        stmt = select(job_match_db.JobOpportunity).where(
            job_match_db.JobOpportunity.candidate_id == candidate_id,
        )
        if states:
            stmt = stmt.where(job_match_db.JobOpportunity.state.in_(states))
        return list(session.exec(stmt))


def _load_jobs(job_ids: list[str]) -> dict[str, job_search_db.Job]:
    if not job_ids:
        return {}
    db_path = job_search_db.get_db_path()
    engine = job_search_db.init_db(db_path)
    with Session(engine) as session:
        stmt = select(job_search_db.Job).where(job_search_db.Job.id.in_(job_ids))
        jobs = session.exec(stmt).all()
        return {job.id: job for job in jobs}


def _bucket_rank(bucket: Optional[str]) -> int:
    order = {"recommended": 0, "borderline": 1, "low_match": 2}
    return order.get(bucket or "", 99)


def _state_rank(state: Optional[str]) -> int:
    order = {
        JobState.SCREENED.value: 0,
        JobState.APPROVED.value: 1,
        JobState.APPLIED.value: 2,
        JobState.DISCOVERED.value: 3,
        JobState.CLOSED.value: 4,
    }
    return order.get(state or "", 99)


def _reset_pref_state() -> None:
    for key in [
        "pref_locations",
        "pref_remote_preference",
        "pref_role_targets",
        "pref_industries",
        "pref_seniority",
    ]:
        st.session_state.pop(key, None)


def _apply_default_prefs() -> None:
    st.session_state.pref_locations = ", ".join(DEFAULT_LOCATION_PATTERNS)
    st.session_state.pref_remote_preference = DEFAULT_REMOTE or "any"
    st.session_state.pref_role_targets = ", ".join(DEFAULT_ROLE_TARGETS)
    st.session_state.pref_industries = ", ".join(DEFAULT_INDUSTRIES)
    st.session_state.pref_seniority = list(DEFAULT_SENIORITY)


def _apply_saved_prefs(candidate_id: str) -> None:
    prefs = candidate_db.get_candidate_preferences(candidate_id)
    candidate = candidate_db.get_candidate(candidate_id)
    if prefs:
        try:
            pref_locations = ", ".join(json.loads(prefs.locations or "[]"))
        except json.JSONDecodeError:
            pref_locations = ", ".join(DEFAULT_LOCATION_PATTERNS)
        try:
            pref_role_targets = ", ".join(json.loads(prefs.role_targets or "[]"))
        except json.JSONDecodeError:
            pref_role_targets = ", ".join(DEFAULT_ROLE_TARGETS)
        try:
            pref_industries = ", ".join(json.loads(prefs.industries or "[]"))
        except json.JSONDecodeError:
            pref_industries = ", ".join(DEFAULT_INDUSTRIES)
        st.session_state.pref_locations = pref_locations or ", ".join(DEFAULT_LOCATION_PATTERNS)
        st.session_state.pref_remote_preference = prefs.remote_preference or DEFAULT_REMOTE or "any"
        st.session_state.pref_role_targets = pref_role_targets or ", ".join(DEFAULT_ROLE_TARGETS)
        st.session_state.pref_industries = pref_industries or ", ".join(DEFAULT_INDUSTRIES)
        if prefs.seniority_preference:
            try:
                seniority_list = json.loads(prefs.seniority_preference or "[]")
            except json.JSONDecodeError:
                seniority_list = [prefs.seniority_preference]
            st.session_state.pref_seniority = seniority_list
        else:
            st.session_state.pref_seniority = list(DEFAULT_SENIORITY)
    if candidate and not st.session_state.pref_seniority:
        try:
            payload = json.loads(candidate.candidate_profile_json)
            estimate = payload.get("result", {}).get("candidate_profile", {}).get("seniority_estimate")
        except json.JSONDecodeError:
            estimate = None
        seniority_map = {
            "junior": "junior",
            "mid": "mid_level",
            "mid_level": "mid_level",
            "senior": "senior",
            "staff": "staff",
        }
        mapped = seniority_map.get(estimate)
        if mapped:
            st.session_state.pref_seniority = [mapped]


def _status_color(state: Optional[str]) -> str:
    if state == JobState.APPROVED.value:
        return "#2B6CB0"  # blue
    if state == JobState.APPLIED.value:
        return "#2F855A"  # green
    if state == JobState.CLOSED.value:
        return "#D69E2E"  # yellow
    return "#718096"  # gray


st.header("Candidate")

candidates = _load_candidates()
selected = st.selectbox("Candidate ID", options=["(new)"] + candidates)
candidate_id = None if selected == "(new)" else selected
if "use_saved_prefs" not in st.session_state:
    st.session_state.use_saved_prefs = False


def _on_saved_prefs_toggle() -> None:
    if candidate_id:
        _reset_pref_state()
        _apply_default_prefs()
        if st.session_state.use_saved_prefs:
            _apply_saved_prefs(candidate_id)


use_saved_prefs = st.checkbox(
    "Use saved candidate preferences",
    value=st.session_state.use_saved_prefs,
    key="use_saved_prefs",
    on_change=_on_saved_prefs_toggle,
)

if selected == "(new)":
    if st.button("Create new candidate"):
        st.session_state.new_candidate_id = str(uuid4())
    candidate_id = st.session_state.get("new_candidate_id")
    if candidate_id:
        st.caption(f"New candidate id: {candidate_id}")
    if st.session_state.loaded_candidate_id is not None:
        st.session_state.loaded_candidate_id = None
else:
    if st.session_state.loaded_candidate_id != candidate_id:
        _reset_pref_state()
        _apply_default_prefs()
        if use_saved_prefs:
            _apply_saved_prefs(candidate_id)
        st.session_state.loaded_candidate_id = candidate_id

with st.expander("Resume (optional)"):
    uploaded_resume = st.file_uploader("Upload resume (.txt)", type=["txt"])
    resume_text = ""
    if uploaded_resume is not None:
        try:
            resume_text = uploaded_resume.getvalue().decode("utf-8")
        except Exception as exc:
            st.error(f"Could not read resume: {exc}")
    resume_text = st.text_area("Resume text", value=resume_text, height=200)

with st.expander("Preferences (optional)"):
    remote_options = ["any", "remote", "hybrid", "onsite"]
    if st.session_state.pref_remote_preference not in remote_options:
        st.session_state.pref_remote_preference = "any"
    seniority_options = ["junior", "mid_level", "senior", "staff", "executive"]
    st.session_state.pref_seniority = [
        value for value in st.session_state.pref_seniority if value in seniority_options
    ]

    locations = st.text_input("Locations (comma-separated)", key="pref_locations")
    remote_preference = st.selectbox(
        "Remote preference",
        options=remote_options,
        key="pref_remote_preference",
    )
    role_targets = st.text_input("Role targets (comma-separated)", key="pref_role_targets")
    industries = st.text_input("Industries (comma-separated)", key="pref_industries")
    seniority = st.multiselect(
        "Seniority (multiple)",
        options=seniority_options,
        key="pref_seniority",
    )

if st.button("Generate/Update Profile"):
    if not candidate_id:
        st.error("Provide a candidate id before generating a profile.")
    elif not resume_text.strip():
        st.error("Provide resume text to generate a profile.")
    else:
        try:
            preferences = CandidatePreferences(
                locations=[item.strip() for item in locations.split(",") if item.strip()],
                remote_preference=None if remote_preference == "any" else remote_preference,
                role_targets=[item.strip() for item in role_targets.split(",") if item.strip()],
                industries=[item.strip() for item in industries.split(",") if item.strip()],
                seniority_preference=seniority,
            )
            request = CandidateProfileRequest(
                candidate_id=candidate_id,
                resume_text=resume_text,
                preferences=preferences,
            )
            envelope, _, _ = generate_candidate_profile(request)
            st.success("Profile generated.")
            st.json(json.loads(envelope.json()))
        except Exception as exc:
            st.error(f"Profile generation failed: {exc}")


st.header("Pipeline")

limit_to_score = st.number_input("Limit to score", min_value=1, value=50)
debug_request = st.checkbox("Debug provider request")

st.subheader("Review (standalone)")
review_port = os.getenv("REVIEW_PORT", "8601")
review_url_default = f"http://localhost:{review_port}"
review_url = st.text_input("Review app URL", value=review_url_default)
st.caption(
    f"Run: `streamlit run agents/orchestrator/streamlit_review.py --server.port {review_port}`"
)
if "8501" in review_url:
    st.warning("Review URL points to the same port as this app. Run the review app on 8601.")


def _is_port_open(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.5):
            return True
    except OSError:
        return False


def _launch_review_app(port: int) -> None:
    subprocess.Popen(
        [
            sys.executable,
            "-m",
            "streamlit",
            "run",
            str(BASE_DIR / "streamlit_review.py"),
            "--server.port",
            str(port),
        ],
        cwd=str(AGENTS_DIR.parent),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
    )


try:
    review_port_int = int(review_port)
except ValueError:
    review_port_int = 8601

if st.button("Review Your Jobs"):
    if _is_port_open(review_port_int):
        st.info(f"Review UI already running on port {review_port_int}.")
    else:
        _launch_review_app(review_port_int)
        st.success("Starting review UI...")
    st.markdown(f"[Open review UI]({review_url})")

if st.button("Run pipeline"):
    if not candidate_id:
        st.error("Select a candidate before running the pipeline.")
    else:
        try:
            provider_config = profile_config.get("provider_config") or DEFAULT_CONFIG
            provider_config = apply_theirstack_overrides(
                provider_config=provider_config,
                role_targets=role_targets,
                seniority=seniority,
            )
            if debug_request:
                os.environ["THEIRSTACK_DEBUG"] = "1"
            payload = None
            for provider in provider_config.get("providers", []):
                if provider.get("type") != "theirstack":
                    continue
                payload = build_payload()
                overrides = provider.get("payload_overrides") or {}
                payload.update(overrides)
                st.session_state.last_theirstack_payload = payload
                if debug_request:
                    st.subheader("Theirstack request payload")
                    st.code(json.dumps(payload, indent=2, ensure_ascii=True), language="json")
                    print(
                        "[ui] theirstack payload overrides:",
                        json.dumps(overrides, ensure_ascii=True),
                    )
            stats = pipeline.run_daily(
                candidate_id=candidate_id,
                provider_config=provider_config,
                limit_to_score=int(limit_to_score),
            )
            st.success("Pipeline run complete.")
            st.json(stats)
            st.session_state.last_pipeline_stats = stats
        except Exception as exc:
            st.error(f"Pipeline failed: {exc}")

if st.session_state.last_pipeline_stats:
    stats = st.session_state.last_pipeline_stats
    st.subheader("Pipeline status")
    st.write(
        "Eligible: "
        f"{stats.get('num_eligible', 0)} | "
        "Skipped (recently applied flag): "
        f"{stats.get('num_skipped_recent_flag', 0)} | "
        "Skipped (state): "
        f"{stats.get('num_skipped_state', 0)}"
    )
    st.write(
        "Pre-ranked: "
        f"{stats.get('num_pre_ranked', 0)} | "
        "Scored: "
        f"{stats.get('num_scored', 0)}"
    )
    if st.session_state.last_theirstack_payload:
        with st.expander("Last Theirstack request payload"):
            st.code(
                json.dumps(st.session_state.last_theirstack_payload, indent=2, ensure_ascii=True),
                language="json",
            )


st.header("Review")

if not candidate_id:
    st.info("Select a candidate to review screened opportunities.")
else:
    opportunities = _load_opportunities(candidate_id)
    if not opportunities:
        st.info("No screened opportunities yet.")
    else:
        opportunities.sort(
            key=lambda opp: (_state_rank(opp.state), _bucket_rank(opp.screen_bucket), -(opp.fit_score or -1))
        )
        job_ids = [opp.job_id for opp in opportunities]
        jobs = _load_jobs(job_ids)
        evaluations = _latest_fit_evaluations(candidate_id, job_ids)

        for opp in opportunities:
            job = jobs.get(opp.job_id)
            evaluation = evaluations.get(opp.job_id)
            title = job.job_title if job else "Unknown role"
            company = job.company if job else "Unknown company"
            header = f"{company} - {title}"
            color = _status_color(opp.state)
            st.markdown(
                f"<div style='background-color:{color};"
                "color:white;padding:10px 12px;border-radius:8px;"
                "margin:8px 0 6px 0;font-weight:600;'>"
                f"{header} — Status: {opp.state}</div>",
                unsafe_allow_html=True,
            )
            with st.expander(header, expanded=False):
                if job:
                    st.write(f"Location: {job.location or 'N/A'}")
                    st.write(f"URL: {job.canonical_url or job.url or 'N/A'}")
                if opp.skip_reason:
                    st.write(f"Close reason: {opp.skip_reason}")
                st.write(f"Score: {opp.fit_score}")
                st.write(f"Decision: {opp.fit_decision}")
                st.write(f"Bucket: {opp.screen_bucket}")

                if evaluation:
                    try:
                        top_reasons = json.loads(evaluation.top_reasons_json)
                    except json.JSONDecodeError:
                        top_reasons = []
                    if top_reasons:
                        st.write("Top reasons:")
                        st.write(", ".join(top_reasons))

                col1, col2, col3 = st.columns(3)
                with col1:
                    if st.button("Approve", key=f"approve_{opp.id}"):
                        orchestrator_state.approve(opp.id)
                        st.success("Approved.")
                        st.rerun()
                with col2:
                    close_reason = st.text_input(
                        "Close reason (optional)",
                        value="",
                        key=f"close_reason_{opp.id}",
                    )
                    if st.button("Close", key=f"close_{opp.id}"):
                        orchestrator_state.close(opp.id, reason=close_reason.strip() or None)
                        st.success("Closed.")
                        st.rerun()
                with col3:
                    if st.button("Mark Applied", key=f"applied_{opp.id}"):
                        orchestrator_state.mark_applied(opp.id)
                        st.success("Marked applied.")
                        st.rerun()

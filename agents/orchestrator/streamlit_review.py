"""Standalone Streamlit UI for reviewing all job opportunities."""

import json
import os
import sys
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
import streamlit as st
from sqlmodel import Session, select

BASE_DIR = Path(__file__).resolve().parent
AGENTS_DIR = BASE_DIR.parent
if str(AGENTS_DIR) not in sys.path:
    sys.path.insert(0, str(AGENTS_DIR))
if not os.getenv("DB_PATH"):
    os.environ["DB_PATH"] = str(AGENTS_DIR / "data" / "app.db")

from candidate_profile.src import db as candidate_db
from job_match import db as job_match_db
from job_match.state_machine import JobState
from job_search import db as job_search_db
from orchestrator import state as orchestrator_state

load_dotenv(BASE_DIR / ".env")
load_dotenv(AGENTS_DIR / ".env")

st.set_page_config(page_title="Jobs Review (Standalone)", layout="wide")
st.title("Jobs Review (Standalone)")
st.caption(f"Server port: {st.get_option('server.port')}")


def _load_candidates() -> list[str]:
    candidates = candidate_db.list_candidates()
    return [candidate.id for candidate in candidates]


def _load_opportunities(candidate_id: str, states: list[str]) -> list[job_match_db.JobOpportunity]:
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


def _state_rank(state: str) -> int:
    order = {
        JobState.SCREENED.value: 0,
        JobState.APPROVED.value: 1,
        JobState.APPLIED.value: 2,
        JobState.DISCOVERED.value: 3,
        JobState.CLOSED.value: 4,
    }
    return order.get(state, 99)


def _status_color(state: Optional[str]) -> str:
    if state == JobState.APPROVED.value:
        return "#2B6CB0"  # blue
    if state == JobState.APPLIED.value:
        return "#2F855A"  # green
    if state == JobState.CLOSED.value:
        return "#D69E2E"  # yellow
    return "#718096"  # gray


st.header("Candidate Profile")
st.caption("A single user can manage multiple candidate profiles.")
candidate_options = _load_candidates()
selected = st.selectbox("Candidate Profile", options=["(select)"] + candidate_options)

if selected == "(select)":
    st.info("Select a candidate profile to review opportunities.")
    st.stop()

state_filter = st.multiselect(
    "States",
    options=[
        JobState.DISCOVERED.value,
        JobState.SCREENED.value,
        JobState.APPROVED.value,
        JobState.APPLIED.value,
        JobState.CLOSED.value,
    ],
    default=[
        JobState.SCREENED.value,
        JobState.APPROVED.value,
        JobState.APPLIED.value,
        JobState.DISCOVERED.value,
        JobState.CLOSED.value,
    ],
)

opps = _load_opportunities(selected, state_filter)
if not opps:
    st.info("No opportunities found for this candidate profile.")
    st.stop()

counts = {}
for opp in opps:
    counts[opp.state] = counts.get(opp.state, 0) + 1
st.caption(
    "Counts: " + ", ".join(f"{state}={count}" for state, count in sorted(counts.items()))
)

opps.sort(key=lambda opp: (_state_rank(opp.state), -(opp.fit_score or -1)))
job_ids = [opp.job_id for opp in opps]
jobs = _load_jobs(job_ids)
evaluations = _latest_fit_evaluations(selected, job_ids)

for opp in opps:
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
        st.write(f"Score: {opp.fit_score}")
        st.write(f"Decision: {opp.fit_decision}")
        st.write(f"Bucket: {opp.screen_bucket}")
        if opp.skip_reason:
            st.write(f"Close reason: {opp.skip_reason}")
        if job:
            st.write(f"Location: {job.location or 'N/A'}")
            st.write(f"URL: {job.canonical_url or job.url or 'N/A'}")

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
            if opp.state == JobState.SCREENED.value:
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
            if opp.state != JobState.CLOSED.value:
                if st.button("Close", key=f"close_{opp.id}"):
                    orchestrator_state.close(opp.id, reason=close_reason.strip() or None)
                    st.success("Closed.")
                    st.rerun()
        with col3:
            if opp.state == JobState.APPROVED.value:
                if st.button("Mark Applied", key=f"applied_{opp.id}"):
                    orchestrator_state.mark_applied(opp.id)
                    st.success("Marked applied.")
                    st.rerun()

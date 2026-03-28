"""Standalone Streamlit UI for reviewing all job opportunities."""

import json
import os
import sys
from datetime import date
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
from orchestrator.review_ui import (
    DATE_FIELD_LABELS,
    PRIMARY_STATUS_METRICS,
    build_review_items,
    filter_review_items,
    group_items_by_date,
    group_items_by_state,
    summarize_states,
)

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
        return "#2B6CB0"
    if state == JobState.APPLIED.value:
        return "#2F855A"
    if state == JobState.CLOSED.value:
        return "#D69E2E"
    return "#718096"


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
    color = _status_color(opp.state)
    st.markdown(
        f"<div style='background-color:{color};"
        "color:white;padding:10px 12px;border-radius:8px;"
        "margin:8px 0 6px 0;font-weight:600;'>"
        f"{header} | Status: {opp.state}</div>",
        unsafe_allow_html=True,
    )
    with st.expander(header, expanded=False):
        st.write(f"Score: {opp.fit_score}")
        st.write(f"Decision: {opp.fit_decision}")
        st.write(f"Bucket: {opp.screen_bucket}")
        st.write(f"{item.selected_date_label}: {item.selected_date_text}")
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
                if st.button("Approve", key=f"{key_prefix}_approve_{opp.id}"):
                    orchestrator_state.approve(opp.id)
                    st.success("Approved.")
                    st.rerun()
        with col2:
            close_reason = st.text_input(
                "Close reason (optional)",
                value="",
                key=f"{key_prefix}_close_reason_{opp.id}",
            )
            if opp.state != JobState.CLOSED.value:
                if st.button("Close", key=f"{key_prefix}_close_{opp.id}"):
                    orchestrator_state.close(opp.id, reason=close_reason.strip() or None)
                    st.success("Closed.")
                    st.rerun()
        with col3:
            if opp.state == JobState.APPROVED.value:
                if st.button("Mark Applied", key=f"{key_prefix}_applied_{opp.id}"):
                    orchestrator_state.mark_applied(opp.id)
                    st.success("Marked applied.")
                    st.rerun()


st.header("Candidate Profile")
st.caption("A single user can manage multiple candidate profiles.")
candidate_options = _load_candidates()
selected = st.selectbox("Candidate Profile", options=["(select)"] + candidate_options)

if selected == "(select)":
    st.info("Select a candidate profile to review opportunities.")
    st.stop()

all_states = [
    JobState.DISCOVERED.value,
    JobState.SCREENED.value,
    JobState.APPROVED.value,
    JobState.APPLIED.value,
    JobState.CLOSED.value,
]

opps = _load_opportunities(selected, all_states)
if not opps:
    st.info("No opportunities found for this candidate profile.")
    st.stop()

opps.sort(key=lambda opp: (_state_rank(opp.state), -(opp.fit_score or -1)))
job_ids = [opp.job_id for opp in opps]
jobs = _load_jobs(job_ids)
evaluations = _latest_fit_evaluations(selected, job_ids)

_render_status_metrics(opps)

filter_col1, filter_col2, filter_col3 = st.columns([1.4, 1, 1])
with filter_col1:
    state_filter = st.multiselect("Status filter", options=all_states, default=all_states)
with filter_col2:
    date_field = st.selectbox(
        "Track jobs by date",
        options=list(DATE_FIELD_LABELS.keys()),
        format_func=lambda key: DATE_FIELD_LABELS[key],
        index=0,
    )

review_items = build_review_items(opps, jobs, evaluations, date_field)
known_dates = sorted({item.selected_date_value for item in review_items if item.selected_date_value is not None})
default_start = known_dates[0] if known_dates else None
default_end = known_dates[-1] if known_dates else None
with filter_col3:
    start_date = st.date_input("From date", value=default_start) if default_start else None
end_date = st.date_input("To date", value=default_end) if default_end else None

filtered_items = filter_review_items(
    review_items,
    selected_states=state_filter,
    start_date=start_date if isinstance(start_date, date) else None,
    end_date=end_date if isinstance(end_date, date) else None,
)
st.caption(
    f"Showing {len(filtered_items)} of {len(opps)} opportunities by {DATE_FIELD_LABELS[date_field].lower()}."
)
if not filtered_items:
    st.info("No opportunities match the current filters.")
    st.stop()

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

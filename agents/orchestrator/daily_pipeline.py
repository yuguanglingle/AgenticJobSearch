"""Legacy daily pipeline runner (uses batch_data input)."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional, Any

BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from job_match.agent import evaluate_and_persist
from job_match import db as job_match_db
from job_match.state_machine import JobState
from job_search import db as job_search_db


def run_daily_pipeline(
    *,
    candidate_id: str,
    batch_data: dict,
    llm_client: Optional[Any] = None,
) -> list[str]:
    """Save jobs with dedup and run JobFitAgent for new/updated jobs.

    Args:
        candidate_id: Candidate primary key.
        batch_data: Retrieval batch payload with jobs.
        llm_client: Optional LLM client.

    Returns:
        List of processed job ids.
    """
    job_ids = job_search_db.save_retrieval_batch(batch_data)
    processed: list[str] = []
    for job_id in job_ids:
        opportunity = job_match_db.get_or_create_opportunity(candidate_id, job_id)
        job = _load_job(job_id)
        if not job:
            continue
        if job_match_db.should_skip_recently_applied(
            candidate_id,
            dedupe_key_strong=job.dedupe_key_strong,
            canonical_url=job.canonical_url,
            dedupe_key_soft=job.dedupe_key_soft,
            description_hash=job.description_hash,
        ):
            job_match_db.mark_skipped_recently_applied(opportunity.id)
            continue
        if JobState(opportunity.state) == JobState.DISCOVERED:
            evaluate_and_persist(candidate_id, job_id, llm_client=llm_client)
            processed.append(job_id)
    return processed


def _load_job(job_id: str):
    """Load a job record by id.

    Args:
        job_id: Job primary key.

    Returns:
        Job record or None.
    """
    db_path = job_search_db.get_db_path()
    engine = job_search_db.init_db(db_path)
    with job_search_db.Session(engine) as session:
        return session.get(job_search_db.Job, job_id)

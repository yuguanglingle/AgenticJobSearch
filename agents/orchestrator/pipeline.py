"""Daily orchestration pipeline: pull jobs, pre-rank, score, and persist results."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Optional

from sqlmodel import Session, select

from candidate_profile.src import db as candidate_db
from job_match import db as job_match_db
from job_match.agent import JobFitAgent
from job_match.pre_ranker import compute_retrieval_score
from job_match.state_machine import JobState
from job_search import db as job_search_db
from job_search.job_search_client import JobSearchClient
from orchestrator import state as orchestrator_state


LLM_SCORE_THRESHOLD = 0.25


@dataclass
class PreRankedOpportunity:
    """Lightweight container for pre-ranked opportunities before scoring.

    Args:
        opportunity_id: JobOpportunity primary key.
        job_id: Job primary key.
        score: Heuristic pre-rank score (0.0-1.0).

    Returns:
        None.
    """
    opportunity_id: str
    job_id: str
    score: float


def _load_llm_client() -> Optional[Any]:
    """Best-effort LLM client loader, gated by OPENAI_API_KEY.

    Args:
        None.

    Returns:
        LLM client instance if configured, otherwise None.
    """
    if not os.getenv("OPENAI_API_KEY"):
        return None
    try:
        from candidate_profile.src.llm_client import LLMClient
    except Exception:
        return None
    return LLMClient()


def _ensure_shared_db_path() -> str:
    """Ensure job_search and job_match use the same DB path.

    Args:
        None.

    Returns:
        Shared DB path string.
    """
    job_match_path = job_match_db.get_db_path()
    job_search_path = job_search_db.get_db_path()
    if os.path.abspath(job_match_path) != os.path.abspath(job_search_path):
        print(
            "[pipeline] warning: DB_PATH mismatch; "
            f"job_match={job_match_path} job_search={job_search_path}. "
            "Forcing shared DB_PATH to job_match."
        )
        os.environ["DB_PATH"] = job_match_path
    return job_match_path


def _get_candidate_or_raise(candidate_id: str):
    """Fetch candidate or raise ValueError if missing.

    Args:
        candidate_id: Candidate primary key.

    Returns:
        Candidate record.
    """
    candidate = candidate_db.get_candidate(candidate_id)
    if not candidate:
        raise ValueError(f"Candidate not found: {candidate_id}")
    return candidate


def _extract_candidate_profile(profile_json: str) -> dict:
    """Parse stored candidate_profile JSON envelope into a dict.

    Args:
        profile_json: Raw JSON string stored in Candidate.candidate_profile_json.

    Returns:
        Candidate profile dict (empty if invalid or missing).
    """
    import json

    try:
        payload = json.loads(profile_json)
    except json.JSONDecodeError:
        return {}
    result = payload.get("result", {})
    profile = result.get("candidate_profile", {})
    return profile if isinstance(profile, dict) else {}


def _extract_preferences(candidate_id: str) -> dict:
    """Load candidate preferences and normalize into Python lists.

    Args:
        candidate_id: Candidate primary key.

    Returns:
        Dict with locations, remote_preference, role_targets, industries, dealbreakers.
    """
    prefs = candidate_db.get_candidate_preferences(candidate_id)
    if not prefs:
        return {
            "locations": [],
            "remote_preference": None,
            "role_targets": [],
            "industries": [],
            "dealbreakers": [],
        }
    import json

    return {
        "locations": json.loads(prefs.locations or "[]"),
        "remote_preference": prefs.remote_preference,
        "role_targets": json.loads(prefs.role_targets or "[]"),
        "industries": json.loads(prefs.industries or "[]"),
        "dealbreakers": json.loads(prefs.dealbreakers or "[]"),
    }


def _candidate_keywords(profile: dict, preferences: dict) -> list[str]:
    """Collect keyword signals used by the pre-ranker.

    Args:
        profile: Parsed candidate profile dict.
        preferences: Parsed candidate preferences dict.

    Returns:
        List of keyword strings.
    """
    keywords: list[str] = []
    keywords.extend(profile.get("keywords_for_search", []))
    keywords.extend(profile.get("core_skills", []))
    keywords.extend(profile.get("domains", []))
    keywords.extend(preferences.get("role_targets", []))
    keywords.extend(preferences.get("industries", []))
    return [str(item) for item in keywords if item]


def _bucket_from_score(score: int) -> str:
    """Map score to screen bucket.

    Args:
        score: Overall score 0-100.

    Returns:
        Screen bucket string.
    """
    if score >= 75:
        return "recommended"
    if score >= 55:
        return "borderline"
    return "low_match"


def _pre_rank_discovered(candidate_id: str, job_ids: list[str]) -> list[PreRankedOpportunity]:
    """Score DISCOVERED opportunities with the heuristic pre-ranker.

    Args:
        candidate_id: Candidate primary key.
        job_ids: List of Job primary keys to consider.

    Returns:
        Sorted list of PreRankedOpportunity items (desc score).
    """
    print(f"[pipeline] pre_rank: start candidate_id={candidate_id} job_ids={len(job_ids)}")
    preferences = _extract_preferences(candidate_id)
    profile = _extract_candidate_profile(_get_candidate_or_raise(candidate_id).candidate_profile_json)
    keywords = _candidate_keywords(profile, preferences)

    db_path = _ensure_shared_db_path()
    print(f"[pipeline] pre_rank: job_match_db_path={db_path}")
    engine = job_match_db.init_db(db_path)
    with Session(engine) as session:
        statement = select(job_match_db.JobOpportunity).where(
            job_match_db.JobOpportunity.candidate_id == candidate_id,
            job_match_db.JobOpportunity.job_id.in_(job_ids),
            job_match_db.JobOpportunity.state == JobState.DISCOVERED.value,
        )
        opportunities = session.exec(statement).all()
    print(f"[pipeline] pre_rank: opportunities_found={len(opportunities)}")

    pre_ranked: list[PreRankedOpportunity] = []
    job_db_path = job_search_db.get_db_path()
    print(f"[pipeline] pre_rank: job_search_db_path={job_db_path} job_ids_sample={job_ids[:5]}")
    job_engine = job_search_db.init_db(job_db_path)
    missing_jobs = 0
    with Session(job_engine) as session:
        for opp in opportunities:
            job = session.get(job_search_db.Job, opp.job_id)
            if not job:
                print(f"[pipeline] pre_rank: missing job record job_id={opp.job_id} - closing opportunity")
                missing_jobs += 1
                try:
                    job_match_db.update_opportunity_state(opp.id, JobState.CLOSED)
                except Exception as e:
                    print(f"[pipeline] pre_rank: could not close opportunity {opp.id} {e}")
                continue
            retrieval_score, _ = compute_retrieval_score(
                job_title=job.job_title,
                job_description=job.description or job.description_text,
                job_location=job.location,
                job_remote=job.remote,
                job_hybrid=job.hybrid,
                keywords=keywords,
                dealbreakers=preferences.get("dealbreakers", []),
                preferred_locations=preferences.get("locations", []),
                remote_preference=preferences.get("remote_preference"),
            )
            pre_ranked.append(
                PreRankedOpportunity(
                    opportunity_id=opp.id,
                    job_id=opp.job_id,
                    score=retrieval_score,
                )
            )
    print(
        "[pipeline] pre_rank: "
        f"pre_ranked_count={len(pre_ranked)} missing_jobs={missing_jobs}"
    )
    pre_ranked.sort(key=lambda item: item.score, reverse=True)
    return pre_ranked


def run_daily(candidate_id: str, provider_config: dict, limit_to_score: int = 50) -> dict:
    """Run one daily cycle: pull jobs, pre-rank, score, and return stats.

    Args:
        candidate_id: Candidate primary key.
        provider_config: JobSearchClient provider configuration.
        limit_to_score: Max number of pre-ranked jobs to score.

    Returns:
        Dict of pipeline stats (batch ids, counts, scoring totals).
    """
    print(f"[pipeline] start run_daily candidate_id={candidate_id} limit_to_score={limit_to_score}")
    shared_db_path = _ensure_shared_db_path()
    _get_candidate_or_raise(candidate_id)

    # 1) Pull jobs from providers and persist (dedupe happens in save).
    print(f"[pipeline] step 1: retrieve jobs from providers db_path={shared_db_path}")
    client = JobSearchClient(provider_config)
    batch_data = client.run()
    job_ids = job_search_db.save_retrieval_batch(batch_data)
    print(f"[pipeline] retrieved_jobs={len(job_ids)}")

    # 2) Load batch stats for reporting (optional).
    batch_id = batch_data.get("retrieval_batch", {}).get("batch_id")
    batch_meta = job_search_db.get_retrieval_batch(batch_id) if batch_id else None

    num_skipped_recent_apply = 0
    num_scored = 0
    num_pre_ranked = 0

    # 3) Ensure opportunities exist and filter eligible DISCOVERED items.
    print("[pipeline] step 3: ensure opportunities and filter eligible")
    eligible_job_ids: list[str] = []
    for job_id in job_ids:
        opp = orchestrator_state.get_or_create_opportunity(candidate_id, job_id)
        if opp.is_skipped_recently_applied:
            print(f"[pipeline] step 3: skip job_id={job_id} reason=recently_applied")
            continue
        if opp.state != JobState.DISCOVERED.value:
            print(f"[pipeline] step 3: skip job_id={job_id} reason=state_{opp.state}")
            continue
        print(f"[pipeline] step 3: eligible job_id={job_id}")
        eligible_job_ids.append(job_id)

    # 4) Pre-rank only eligible DISCOVERED opportunities.
    print(f"[pipeline] step 4: pre-rank eligible_count={len(eligible_job_ids)}")
    pre_ranked = _pre_rank_discovered(candidate_id, eligible_job_ids)
    num_pre_ranked = len(pre_ranked)
    print(f"[pipeline] step 4: pre_ranked_count={num_pre_ranked}")

    # 5) Prepare LLM client if available and reuse DB engine.
    print("[pipeline] step 5: prepare LLM client")
    llm_client = _load_llm_client()
    db_path = _ensure_shared_db_path()
    job_engine = job_search_db.init_db(db_path)
    agent_with_llm = JobFitAgent(llm_client=llm_client)
    agent_no_llm = JobFitAgent(llm_client=None)

    # 6) Score the top-N pre-ranked opportunities.
    print(f"[pipeline] step 6: score top_n={max(0, limit_to_score)}")
    for item in pre_ranked[: max(0, limit_to_score)]:
        with Session(job_engine) as session:
            job_record = session.get(job_search_db.Job, item.job_id)
        if not job_record:
            print(f"[pipeline] score skip missing job_record job_id={item.job_id} - closing opportunity")
            try:
                job_match_db.update_opportunity_state(item.opportunity_id, JobState.CLOSED)
            except Exception as e:
                print(f"[pipeline] score: could not close opportunity {item.opportunity_id} {e}")
            continue
        # Skip jobs that were applied to recently.
        if job_match_db.should_skip_recently_applied(
            candidate_id,
            dedupe_key_strong=job_record.dedupe_key_strong,
            canonical_url=job_record.canonical_url,
            dedupe_key_soft=job_record.dedupe_key_soft,
            description_hash=job_record.description_hash,
        ):
            print(f"[pipeline] skip recently applied job_id={item.job_id}")
            orchestrator_state.mark_skipped_recently_applied(candidate_id, item.job_id)
            num_skipped_recent_apply += 1
            continue

        # Only send to LLM when the heuristic score passes threshold.
        if item.score < LLM_SCORE_THRESHOLD:
            print(f"[pipeline] score job_id={item.job_id} using fallback pre_rank_score={item.score:.2f}")
            result = agent_no_llm.evaluate(candidate_id, item.job_id)
        else:
            print(f"[pipeline] score job_id={item.job_id} using LLM pre_rank_score={item.score:.2f}")
            result = agent_with_llm.evaluate(candidate_id, item.job_id)
        orchestrator_state.apply_fit_result(
            candidate_id,
            item.job_id,
            result.overall_score,
            result.decision,
            _bucket_from_score(result.overall_score),
            subscores=result.subscores,
            top_reasons=result.top_reasons,
            gaps=result.gaps,
            dealbreakers_triggered=result.dealbreakers_triggered,
            model=getattr(llm_client, "model", None) if item.score >= LLM_SCORE_THRESHOLD else None,
        )
        num_scored += 1

    # 7) Return a compact stats payload for logging/UI.
    print("[pipeline] step 7: return stats")
    stats = {
        "candidate_id": candidate_id,
        "batch_id": batch_id,
        "num_new_jobs": batch_meta["stats"]["jobs_new"] if batch_meta else 0,
        "num_updated_jobs": batch_meta["stats"]["jobs_updated"] if batch_meta else 0,
        "num_deduped_jobs": batch_meta["stats"]["jobs_deduped"] if batch_meta else 0,
        "num_pre_ranked": num_pre_ranked,
        "num_scored": num_scored,
        "num_skipped_recent_apply": num_skipped_recent_apply,
        "limit_to_score": limit_to_score,
    }
    return stats


def run_daily_from_batch(
    *,
    candidate_id: str,
    batch_data: dict,
    llm_client: Optional[Any] = None,
    limit_to_score: int = 50,
) -> dict:
    """Run the pipeline using a pre-fetched batch (useful for tests).

    Args:
        candidate_id: Candidate primary key.
        batch_data: Retrieval batch payload with jobs.
        llm_client: Optional LLM client override.
        limit_to_score: Max number of pre-ranked jobs to score.

    Returns:
        Dict of pipeline stats (batch ids, counts, scoring totals).
    """
    print(f"[pipeline] start run_daily_from_batch candidate_id={candidate_id} limit_to_score={limit_to_score}")
    shared_db_path = _ensure_shared_db_path()
    _get_candidate_or_raise(candidate_id)

    print(f"[pipeline] step 1: save retrieval batch db_path={shared_db_path}")
    job_ids = job_search_db.save_retrieval_batch(batch_data)
    batch_id = batch_data.get("retrieval_batch", {}).get("batch_id")
    batch_meta = job_search_db.get_retrieval_batch(batch_id) if batch_id else None

    num_skipped_recent_apply = 0
    num_scored = 0
    num_pre_ranked = 0

    print("[pipeline] step 2: ensure opportunities and filter eligible")
    eligible_job_ids: list[str] = []
    for job_id in job_ids:
        opp = orchestrator_state.get_or_create_opportunity(candidate_id, job_id)
        if opp.is_skipped_recently_applied:
            print(f"[pipeline] step 2: skip job_id={job_id} reason=recently_applied")
            continue
        if opp.state != JobState.DISCOVERED.value:
            print(f"[pipeline] step 2: skip job_id={job_id} reason=state_{opp.state}")
            continue
        print(f"[pipeline] step 2: eligible job_id={job_id}")
        eligible_job_ids.append(job_id)

    print(f"[pipeline] step 3: pre-rank eligible_count={len(eligible_job_ids)}")
    pre_ranked = _pre_rank_discovered(candidate_id, eligible_job_ids)
    num_pre_ranked = len(pre_ranked)
    print(f"[pipeline] step 3: pre_ranked_count={num_pre_ranked}")

    db_path = _ensure_shared_db_path()
    job_engine = job_search_db.init_db(db_path)
    effective_llm_client = llm_client or _load_llm_client()
    agent_with_llm = JobFitAgent(llm_client=effective_llm_client)
    agent_no_llm = JobFitAgent(llm_client=None)

    for item in pre_ranked[: max(0, limit_to_score)]:
        with Session(job_engine) as session:
            job_record = session.get(job_search_db.Job, item.job_id)
        if not job_record:
            print(f"[pipeline] score skip missing job_record job_id={item.job_id} - closing opportunity")
            try:
                job_match_db.update_opportunity_state(item.opportunity_id, JobState.CLOSED)
            except Exception as e:
                print(f"[pipeline] score: could not close opportunity {item.opportunity_id} {e}")
            continue
        if job_match_db.should_skip_recently_applied(
            candidate_id,
            dedupe_key_strong=job_record.dedupe_key_strong,
            canonical_url=job_record.canonical_url,
            dedupe_key_soft=job_record.dedupe_key_soft,
            description_hash=job_record.description_hash,
        ):
            print(f"[pipeline] skip recently applied job_id={item.job_id}")
            orchestrator_state.mark_skipped_recently_applied(candidate_id, item.job_id)
            num_skipped_recent_apply += 1
            continue

        if item.score < LLM_SCORE_THRESHOLD:
            print(f"[pipeline] score job_id={item.job_id} using fallback pre_rank_score={item.score:.2f}")
            result = agent_no_llm.evaluate(candidate_id, item.job_id)
        else:
            print(f"[pipeline] score job_id={item.job_id} using LLM pre_rank_score={item.score:.2f}")
            result = agent_with_llm.evaluate(candidate_id, item.job_id)
        orchestrator_state.apply_fit_result(
            candidate_id,
            item.job_id,
            result.overall_score,
            result.decision,
            _bucket_from_score(result.overall_score),
            subscores=result.subscores,
            top_reasons=result.top_reasons,
            gaps=result.gaps,
            dealbreakers_triggered=result.dealbreakers_triggered,
            model=getattr(effective_llm_client, "model", None)
            if item.score >= LLM_SCORE_THRESHOLD
            else None,
        )
        num_scored += 1

    print("[pipeline] step 4: return stats")
    return {
        "candidate_id": candidate_id,
        "batch_id": batch_id,
        "num_new_jobs": batch_meta["stats"]["jobs_new"] if batch_meta else 0,
        "num_updated_jobs": batch_meta["stats"]["jobs_updated"] if batch_meta else 0,
        "num_deduped_jobs": batch_meta["stats"]["jobs_deduped"] if batch_meta else 0,
        "num_pre_ranked": num_pre_ranked,
        "num_scored": num_scored,
        "num_skipped_recent_apply": num_skipped_recent_apply,
        "limit_to_score": limit_to_score,
    }

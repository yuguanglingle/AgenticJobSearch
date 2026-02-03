import importlib
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from sqlmodel import Session

from job_match import db as job_match_db
from job_match.pre_ranker import compute_retrieval_score
from job_match.state_machine import JobState

_candidate_db = None
_job_search_db = None


def _get_candidate_db():
    """Load candidate_profile db module lazily.

    Args:
        None.

    Returns:
        Imported candidate_profile.src.db module.
    """
    global _candidate_db
    if _candidate_db is None:
        base_dir = Path(__file__).resolve().parents[1]
        if str(base_dir) not in sys.path:
            sys.path.insert(0, str(base_dir))
        module_name = "candidate_profile.src.db"
        _candidate_db = sys.modules.get(module_name) or importlib.import_module(module_name)
    return _candidate_db


def _get_job_search_db():
    """Load job_search db module lazily.

    Args:
        None.

    Returns:
        Imported job_search.db module.
    """
    global _job_search_db
    if _job_search_db is None:
        base_dir = Path(__file__).resolve().parents[1]
        if str(base_dir) not in sys.path:
            sys.path.insert(0, str(base_dir))
        module_name = "job_search.db"
        _job_search_db = sys.modules.get(module_name) or importlib.import_module(module_name)
    return _job_search_db


def _safe_json_loads(payload: Optional[str]) -> dict:
    """Safely parse JSON string into dict.

    Args:
        payload: JSON string or None.

    Returns:
        Parsed dict or empty dict on error.
    """
    if not payload:
        return {}
    try:
        return json.loads(payload)
    except json.JSONDecodeError:
        return {}


def _extract_candidate_profile(profile_json: str) -> dict:
    """Extract candidate_profile dict from stored JSON envelope.

    Args:
        profile_json: Raw JSON string.

    Returns:
        Candidate profile dict (empty if missing).
    """
    data = _safe_json_loads(profile_json)
    result = data.get("result", {})
    candidate_profile = result.get("candidate_profile", {})
    return candidate_profile if isinstance(candidate_profile, dict) else {}


def _extract_preferences(candidate_id: str) -> dict:
    """Load candidate preferences and normalize into lists.

    Args:
        candidate_id: Candidate primary key.

    Returns:
        Dict of preferences with lists and scalar fields.
    """
    candidate_db = _get_candidate_db()
    prefs = candidate_db.get_candidate_preferences(candidate_id)
    if not prefs:
        return {
            "locations": [],
            "remote_preference": None,
            "role_targets": [],
            "industries": [],
            "dealbreakers": [],
        }
    return {
        "locations": _safe_json_loads(prefs.locations) if isinstance(prefs.locations, str) else [],
        "remote_preference": prefs.remote_preference,
        "role_targets": _safe_json_loads(prefs.role_targets) if isinstance(prefs.role_targets, str) else [],
        "industries": _safe_json_loads(prefs.industries) if isinstance(prefs.industries, str) else [],
        "dealbreakers": _safe_json_loads(prefs.dealbreakers) if isinstance(prefs.dealbreakers, str) else [],
    }


def _candidate_keywords(profile: dict, preferences: dict) -> list[str]:
    """Collect keyword signals for ranking.

    Args:
        profile: Candidate profile dict.
        preferences: Candidate preferences dict.

    Returns:
        List of keyword strings.
    """
    keywords = []
    keywords.extend(profile.get("keywords_for_search", []))
    keywords.extend(profile.get("core_skills", []))
    keywords.extend(profile.get("domains", []))
    keywords.extend(preferences.get("role_targets", []))
    keywords.extend(preferences.get("industries", []))
    return [str(item) for item in keywords if item]


def _decision_from_score(score: int) -> str:
    """Map score to decision bucket.

    Args:
        score: Overall score 0-100.

    Returns:
        Decision string.
    """
    if score >= 75:
        return "strong_yes"
    if score >= 55:
        return "maybe"
    return "no"


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


@dataclass
class JobFitResult:
    """Job fit evaluation output container.

    Args:
        overall_score: Overall score 0-100.
        decision: Decision label.
        subscores: Dict of sub-scores.
        top_reasons: List of reasons.
        gaps: List of gaps.
        dealbreakers_triggered: List of triggered dealbreakers.
        used_llm: True if LLM was used.

    Returns:
        None.
    """
    overall_score: int
    decision: str
    subscores: dict
    top_reasons: list[str]
    gaps: list[str]
    dealbreakers_triggered: list[str]
    used_llm: bool


class JobFitAgent:
    """Evaluates job fit using heuristics and optional LLM.

    Args:
        None.

    Returns:
        None.
    """
    def __init__(self, llm_client: Optional[Any] = None) -> None:
        """Create a JobFitAgent.

        Args:
            llm_client: Optional LLM client instance.

        Returns:
            None.
        """
        self.llm_client = llm_client

    def evaluate(self, candidate_id: str, job_id: str) -> JobFitResult:
        """Evaluate job fit for candidate and job.

        Args:
            candidate_id: Candidate primary key.
            job_id: Job primary key.

        Returns:
            JobFitResult with scores and decision.
        """
        candidate_db = _get_candidate_db()
        candidate = candidate_db.get_candidate(candidate_id)
        if not candidate:
            raise ValueError("Candidate not found.")

        job = self._load_job(job_id)
        if not job:
            raise ValueError("Job not found.")

        profile = _extract_candidate_profile(candidate.candidate_profile_json)
        preferences = _extract_preferences(candidate_id)
        keywords = _candidate_keywords(profile, preferences)
        retrieval_score, reasons = compute_retrieval_score(
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

        self._update_job_retrieval_score(job_id, retrieval_score)

        if retrieval_score < 0.25:
            return self._fallback_eval(retrieval_score, reasons, used_llm=False)

        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key or not self.llm_client:
            return self._fallback_eval(retrieval_score, reasons, used_llm=False)

        try:
            return self._llm_eval(profile, preferences, job, retrieval_score)
        except Exception:
            return self._fallback_eval(retrieval_score, reasons, used_llm=False)

    def _load_job(self, job_id: str) -> Optional[Any]:
        """Load a job record by id.

        Args:
            job_id: Job primary key.

        Returns:
            Job record or None.
        """
        job_search_db = _get_job_search_db()
        db_path = job_search_db.get_db_path()
        engine = job_search_db.init_db(db_path)
        with Session(engine) as session:
            return session.get(job_search_db.Job, job_id)

    def _update_job_retrieval_score(self, job_id: str, retrieval_score: float) -> None:
        """Persist retrieval score on the job.

        Args:
            job_id: Job primary key.
            retrieval_score: Heuristic score 0.0-1.0.

        Returns:
            None.
        """
        job_search_db = _get_job_search_db()
        db_path = job_search_db.get_db_path()
        engine = job_search_db.init_db(db_path)
        with Session(engine) as session:
            job = session.get(job_search_db.Job, job_id)
            if job:
                job.retrieval_score = retrieval_score
                session.add(job)
                session.commit()

    def _fallback_eval(self, retrieval_score: float, reasons: dict, used_llm: bool) -> JobFitResult:
        """Build a fallback evaluation result without LLM.

        Args:
            retrieval_score: Heuristic score 0.0-1.0.
            reasons: Reasons dict from pre-ranker.
            used_llm: Whether LLM was used.

        Returns:
            JobFitResult.
        """
        score = int(round(retrieval_score * 100))
        decision = _decision_from_score(score)
        return JobFitResult(
            overall_score=score,
            decision=decision,
            subscores={"retrieval_score": retrieval_score, **reasons},
            top_reasons=["heuristic_retrieval_score"],
            gaps=[],
            dealbreakers_triggered=reasons.get("dealbreakers", []),
            used_llm=used_llm,
        )

    def _llm_eval(
        self,
        profile: dict,
        preferences: dict,
        job: Any,
        retrieval_score: float,
    ) -> JobFitResult:
        """Call LLM to score job fit.

        Args:
            profile: Candidate profile dict.
            preferences: Candidate preferences dict.
            job: Job record.
            retrieval_score: Heuristic score 0.0-1.0.

        Returns:
            JobFitResult.
        """
        system_prompt = (
            "You are a strict job fit evaluator. Return JSON only with keys: "
            "overall_score (0-100), decision (strong_yes|maybe|no), "
            "subscores, top_reasons, gaps, dealbreakers_triggered."
        )
        user_prompt = json.dumps(
            {
                "candidate_profile": profile,
                "preferences": preferences,
                "job": {
                    "title": job.job_title,
                    "location": job.location,
                    "description": job.description or job.description_text,
                },
                "retrieval_score": retrieval_score,
            }
        )
        raw_response = self.llm_client.generate(system_prompt=system_prompt, user_prompt=user_prompt)
        parsed = _safe_json_loads(raw_response)
        overall_score = int(parsed.get("overall_score") or 0)
        decision = parsed.get("decision") or _decision_from_score(overall_score)
        subscores = parsed.get("subscores") or {"retrieval_score": retrieval_score}
        top_reasons = parsed.get("top_reasons") or []
        gaps = parsed.get("gaps") or []
        dealbreakers = parsed.get("dealbreakers_triggered") or []
        return JobFitResult(
            overall_score=overall_score,
            decision=decision,
            subscores=subscores,
            top_reasons=top_reasons,
            gaps=gaps,
            dealbreakers_triggered=dealbreakers,
            used_llm=True,
        )


def evaluate_and_persist(candidate_id: str, job_id: str, llm_client: Optional[Any] = None) -> JobFitResult:
    """Evaluate job fit and persist evaluation + opportunity updates.

    Args:
        candidate_id: Candidate primary key.
        job_id: Job primary key.
        llm_client: Optional LLM client instance.

    Returns:
        JobFitResult.
    """
    agent = JobFitAgent(llm_client=llm_client)
    opportunity = job_match_db.get_or_create_opportunity(candidate_id, job_id)
    if JobState(opportunity.state) == JobState.CLOSED:
        raise ValueError("Cannot score a closed opportunity.")
    result = agent.evaluate(candidate_id, job_id)
    job_match_db.save_job_fit_evaluation(
        candidate_id=candidate_id,
        job_id=job_id,
        overall_score=result.overall_score,
        decision=result.decision,
        subscores=result.subscores,
        top_reasons=result.top_reasons,
        gaps=result.gaps,
        dealbreakers_triggered=result.dealbreakers_triggered,
        model=getattr(llm_client, "model", None) if llm_client else None,
        raw_response=None,
    )
    job_match_db.set_opportunity_scored(
        opportunity.id,
        score=result.overall_score,
        decision=result.decision,
        screen_bucket=_bucket_from_score(result.overall_score),
    )
    return result

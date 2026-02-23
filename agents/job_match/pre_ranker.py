import re
from typing import Iterable, Optional


def normalize_terms(values: Iterable[str]) -> list[str]:
    """Normalize text terms to lowercase alphanumeric tokens.

    Args:
        values: Iterable of raw strings.

    Returns:
        List of normalized strings.
    """
    normalized = []
    for value in values:
        cleaned = re.sub(r"[^a-z0-9\s]", " ", value.lower())
        cleaned = " ".join(cleaned.split())
        if cleaned:
            normalized.append(cleaned)
    return normalized


def text_contains_any(text: str, terms: Iterable[str]) -> bool:
    """Check whether any term appears in text.

    Args:
        text: Lower/upper case text to search.
        terms: Iterable of normalized terms.

    Returns:
        True if any term is found, otherwise False.
    """
    for term in terms:
        if term and term in text:
            return True
    return False


def count_overlaps(text: str, terms: Iterable[str]) -> int:
    """Count term overlaps in text.

    Args:
        text: Lower/upper case text to search.
        terms: Iterable of normalized terms.

    Returns:
        Count of matching terms.
    """
    hits = 0
    for term in terms:
        if term and term in text:
            hits += 1
    return hits


def location_match(
    *,
    job_location: Optional[str],
    job_remote: Optional[bool],
    job_hybrid: Optional[bool],
    preferred_locations: list[str],
    remote_preference: Optional[str],
) -> bool:
    """Determine whether a job location matches user preference.

    Args:
        job_location: Job location string.
        job_remote: Job remote flag.
        job_hybrid: Job hybrid flag.
        preferred_locations: Preferred locations list.
        remote_preference: One of remote/hybrid/onsite/None.

    Returns:
        True if location matches, otherwise False.
    """
    location_text = (job_location or "").lower()
    preferred_locations = normalize_terms(preferred_locations)
    if preferred_locations and text_contains_any(location_text, preferred_locations):
        return True
    if remote_preference == "remote":
        return bool(job_remote) or "remote" in location_text
    if remote_preference == "hybrid":
        return bool(job_hybrid) or "hybrid" in location_text
    if remote_preference == "onsite":
        return not job_remote and "remote" not in location_text
    return bool(location_text) or job_remote or job_hybrid


def compute_retrieval_score(
    *,
    job_title: Optional[str],
    job_description: Optional[str],
    job_location: Optional[str],
    job_remote: Optional[bool],
    job_hybrid: Optional[bool],
    keywords: Iterable[str],
    dealbreakers: Iterable[str],
    preferred_locations: list[str],
    remote_preference: Optional[str],
) -> tuple[float, dict]:
    """Compute heuristic retrieval score for a job.

    Args:
        job_title: Job title.
        job_description: Job description text.
        job_location: Job location.
        job_remote: Job remote flag.
        job_hybrid: Job hybrid flag.
        keywords: Candidate keywords.
        dealbreakers: Candidate dealbreakers.
        preferred_locations: Preferred locations list.
        remote_preference: Candidate remote preference.

    Returns:
        Tuple of (score 0.0-1.0, reasons dict).
    """
    text = " ".join(filter(None, [job_title or "", job_description or ""])).lower()
    normalized_keywords = normalize_terms(keywords)
    normalized_dealbreakers = normalize_terms(dealbreakers)

    score = 0.0
    reasons = {
        "location_match": False,
        "keyword_hits": 0,
        "dealbreakers": [],
    }

    if location_match(
        job_location=job_location,
        job_remote=job_remote,
        job_hybrid=job_hybrid,
        preferred_locations=preferred_locations,
        remote_preference=remote_preference,
    ):
        score += 0.35
        reasons["location_match"] = True

    if normalized_keywords:
        hits = count_overlaps(text, normalized_keywords)
        reasons["keyword_hits"] = hits
        overlap_ratio = min(1.0, hits / max(1, len(normalized_keywords)))
        score += 0.45 * overlap_ratio

    if normalized_dealbreakers:
        if text_contains_any(text, normalized_dealbreakers):
            score -= 0.20
            reasons["dealbreakers"] = [
                term for term in normalized_dealbreakers if term in text
            ]

    score = max(0.0, min(1.0, score))
    return score, reasons

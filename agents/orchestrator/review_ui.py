"""Shared helpers for opportunity review UIs."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from typing import Iterable, Optional

try:
    from job_match.state_machine import JobState
except ModuleNotFoundError:  # pragma: no cover - package import fallback for tests
    from agents.job_match.state_machine import JobState


DATE_FIELD_LABELS = {
    "first_seen": "First seen",
    "last_state_changed_at": "State changed",
    "last_scored_at": "Last scored",
    "job_discovered_at": "Job discovered",
    "job_date_posted": "Job posted",
    "job_date_reposted": "Job reposted",
}

PRIMARY_STATUS_METRICS = (
    JobState.SCREENED.value,
    JobState.APPROVED.value,
    JobState.APPLIED.value,
    JobState.CLOSED.value,
)


@dataclass(frozen=True)
class OpportunityReviewItem:
    opportunity: object
    job: object | None
    evaluation: object | None
    selected_date_label: str
    selected_date_value: Optional[date]
    selected_date_text: str


def parse_dateish(value: Optional[str]) -> Optional[date]:
    """Parse ISO or yyyy-mm-dd strings into date objects."""
    if not value:
        return None
    text = value.strip()
    if not text:
        return None
    try:
        if "T" in text or text.endswith("Z"):
            return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def resolve_selected_date(opportunity: object, job: object | None, field_name: str) -> tuple[Optional[date], str]:
    """Return the selected date for filtering/grouping plus a UI label."""
    raw_value = None
    if field_name == "job_discovered_at" and job is not None:
        raw_value = getattr(job, "discovered_at", None) or getattr(job, "date_found", None)
    elif field_name == "job_date_posted" and job is not None:
        raw_value = getattr(job, "date_posted", None) or getattr(job, "posted_at", None)
    elif field_name == "job_date_reposted" and job is not None:
        raw_value = getattr(job, "date_reposted", None) or getattr(job, "updated_at", None)
    else:
        raw_value = getattr(opportunity, field_name, None)

    parsed = parse_dateish(raw_value)
    if parsed:
        return parsed, parsed.isoformat()
    return None, "Unknown"


def build_review_items(opportunities: Iterable[object], jobs: dict[str, object], evaluations: dict[str, object], field_name: str) -> list[OpportunityReviewItem]:
    """Build review rows enriched with selected date metadata."""
    items: list[OpportunityReviewItem] = []
    label = DATE_FIELD_LABELS.get(field_name, "Selected date")
    for opportunity in opportunities:
        job = jobs.get(getattr(opportunity, "job_id"))
        selected_date_value, selected_date_text = resolve_selected_date(opportunity, job, field_name)
        items.append(
            OpportunityReviewItem(
                opportunity=opportunity,
                job=job,
                evaluation=evaluations.get(getattr(opportunity, "job_id")),
                selected_date_label=label,
                selected_date_value=selected_date_value,
                selected_date_text=selected_date_text,
            )
        )
    return items


def summarize_states(opportunities: Iterable[object]) -> dict[str, int]:
    """Count opportunities by workflow state."""
    return dict(Counter(getattr(opportunity, "state", None) for opportunity in opportunities if getattr(opportunity, "state", None)))


def filter_review_items(
    items: Iterable[OpportunityReviewItem],
    selected_states: Iterable[str],
    start_date: Optional[date],
    end_date: Optional[date],
) -> list[OpportunityReviewItem]:
    """Apply state and inclusive date-range filters."""
    allowed_states = set(selected_states)
    filtered: list[OpportunityReviewItem] = []
    for item in items:
        if allowed_states and getattr(item.opportunity, "state", None) not in allowed_states:
            continue
        item_date = item.selected_date_value
        if start_date and (item_date is None or item_date < start_date):
            continue
        if end_date and (item_date is None or item_date > end_date):
            continue
        filtered.append(item)
    return filtered


def group_items_by_state(items: Iterable[OpportunityReviewItem]) -> dict[str, list[OpportunityReviewItem]]:
    """Group filtered items by state."""
    grouped: dict[str, list[OpportunityReviewItem]] = defaultdict(list)
    for item in items:
        grouped[getattr(item.opportunity, "state", "UNKNOWN")].append(item)
    return dict(grouped)


def group_items_by_date(items: Iterable[OpportunityReviewItem]) -> dict[str, list[OpportunityReviewItem]]:
    """Group filtered items by selected date text."""
    grouped: dict[str, list[OpportunityReviewItem]] = defaultdict(list)
    for item in items:
        grouped[item.selected_date_text].append(item)
    return dict(grouped)

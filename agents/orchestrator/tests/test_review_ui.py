from datetime import date
from types import SimpleNamespace

from agents.orchestrator.review_ui import (
    DATE_FIELD_LABELS,
    build_review_items,
    filter_review_items,
    group_items_by_date,
    group_items_by_state,
    summarize_states,
)


def _opp(job_id: str, state: str, **extra):
    return SimpleNamespace(job_id=job_id, state=state, **extra)


def _job(**extra):
    return SimpleNamespace(**extra)


def test_build_review_items_uses_selected_job_date_field():
    opportunities = [
        _opp(
            "job-1",
            "SCREENED",
            first_seen="2026-03-10T12:00:00Z",
            last_state_changed_at="2026-03-11T12:00:00Z",
            last_scored_at="2026-03-12T12:00:00Z",
        )
    ]
    jobs = {"job-1": _job(date_posted="2026-03-01", discovered_at="2026-03-05")}

    items = build_review_items(opportunities, jobs, {}, "job_date_posted")

    assert len(items) == 1
    assert items[0].selected_date_label == DATE_FIELD_LABELS["job_date_posted"]
    assert items[0].selected_date_text == "2026-03-01"
    assert items[0].selected_date_value == date(2026, 3, 1)


def test_filter_review_items_applies_state_and_date_range():
    opportunities = [
        _opp("job-1", "SCREENED", first_seen="2026-03-10T12:00:00Z"),
        _opp("job-2", "APPROVED", first_seen="2026-03-15T12:00:00Z"),
        _opp("job-3", "CLOSED", first_seen="2026-03-20T12:00:00Z"),
    ]

    items = build_review_items(opportunities, {}, {}, "first_seen")
    filtered = filter_review_items(
        items,
        selected_states=["SCREENED", "APPROVED"],
        start_date=date(2026, 3, 12),
        end_date=date(2026, 3, 18),
    )

    assert [item.opportunity.job_id for item in filtered] == ["job-2"]


def test_group_and_summary_helpers_return_expected_counts():
    opportunities = [
        _opp("job-1", "SCREENED", first_seen="2026-03-10T12:00:00Z"),
        _opp("job-2", "SCREENED", first_seen="2026-03-10T13:00:00Z"),
        _opp("job-3", "APPLIED", first_seen="2026-03-11T12:00:00Z"),
    ]

    items = build_review_items(opportunities, {}, {}, "first_seen")

    assert summarize_states(opportunities) == {"SCREENED": 2, "APPLIED": 1}
    assert {key: len(value) for key, value in group_items_by_state(items).items()} == {
        "SCREENED": 2,
        "APPLIED": 1,
    }
    assert {key: len(value) for key, value in group_items_by_date(items).items()} == {
        "2026-03-10": 2,
        "2026-03-11": 1,
    }

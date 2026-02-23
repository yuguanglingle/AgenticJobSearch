from enum import Enum
from typing import Dict, Set


class JobState(str, Enum):
    DISCOVERED = "DISCOVERED"
    SCREENED = "SCREENED"
    APPROVED = "APPROVED"
    APPLIED = "APPLIED"
    CLOSED = "CLOSED"


ALLOWED_TRANSITIONS: Dict[JobState, Set[JobState]] = {
    JobState.DISCOVERED: {JobState.SCREENED, JobState.CLOSED},
    JobState.SCREENED: {JobState.APPROVED, JobState.CLOSED},
    JobState.APPROVED: {JobState.APPLIED, JobState.CLOSED},
    JobState.APPLIED: {JobState.CLOSED},
    JobState.CLOSED: set(),
}


def can_transition(current: JobState, target: JobState) -> bool:
    """Check whether a transition is allowed.

    Args:
        current: Current JobState.
        target: Target JobState.

    Returns:
        True if transition is allowed, otherwise False.
    """
    return target in ALLOWED_TRANSITIONS.get(current, set())


def ensure_transition(current: JobState, target: JobState) -> None:
    """Raise if a transition is invalid.

    Args:
        current: Current JobState.
        target: Target JobState.

    Returns:
        None.
    """
    if current == target:
        return
    if not can_transition(current, target):
        raise ValueError(f"Invalid transition {current.value} -> {target.value}")


def next_action_for_state(state: JobState) -> str:
    """Return user-facing next action for a given state.

    Args:
        state: JobState.

    Returns:
        Next action string.
    """
    if state == JobState.SCREENED:
        return "Approve or close"
    if state == JobState.APPROVED:
        return "Apply"
    if state == JobState.APPLIED:
        return "Wait / follow up"
    return ""

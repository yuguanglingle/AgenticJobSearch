"""Utility helpers for candidate profile agent."""

from datetime import datetime, timezone
from typing import List, Iterable


def now_utc_iso() -> str:
    """Return current UTC timestamp in ISO-8601.

    Args:
        None.

    Returns:
        ISO-8601 timestamp string.
    """
    return datetime.now(timezone.utc).isoformat()


def clamp(value: float, min_value: float = 0.0, max_value: float = 1.0) -> float:
    """Clamp a float between min and max.

    Args:
        value: Input value.
        min_value: Minimum allowed.
        max_value: Maximum allowed.

    Returns:
        Clamped value.
    """
    return max(min_value, min(max_value, value))


def unique_sorted(items: Iterable[str], max_items: int) -> List[str]:
    """Return unique, case-insensitive sorted items capped by max_items.

    Args:
        items: Iterable of items.
        max_items: Max number of items to return.

    Returns:
        List of unique items.
    """
    seen = {}
    for item in items:
        if item is None:
            continue
        item_str = str(item).strip()
        if not item_str:
            continue
        key = item_str.lower()
        if key not in seen:
            seen[key] = item_str
    result = [seen[k] for k in sorted(seen.keys())]
    return result[:max_items]


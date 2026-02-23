"""Helpers for applying UI overrides to TheirStack provider config."""

from __future__ import annotations

from copy import deepcopy

from job_search.job_search_client import build_payload

DEFAULT_THEIRSTACK_PAYLOAD = build_payload()
DEFAULT_ROLE_TARGETS = [
    str(item) for item in DEFAULT_THEIRSTACK_PAYLOAD.get("job_title_or", []) if item
]
DEFAULT_LOCATION_PATTERNS = [
    str(item) for item in DEFAULT_THEIRSTACK_PAYLOAD.get("job_location_pattern_or", []) if item
]
DEFAULT_SENIORITY = [
    str(item) for item in DEFAULT_THEIRSTACK_PAYLOAD.get("job_seniority_or", []) if item
]
DEFAULT_REMOTE = DEFAULT_THEIRSTACK_PAYLOAD.get("remote")
DEFAULT_INDUSTRIES = [
    str(item) for item in DEFAULT_THEIRSTACK_PAYLOAD.get("industry_or", []) if item
]


def parse_csv(value: str) -> list[str]:
    """Split a comma-separated string into a list of trimmed values."""
    return [item.strip() for item in value.split(",") if item.strip()]


def same_items(left: list[str], right: list[str]) -> bool:
    """Return True when two lists contain the same items, order-insensitive."""
    return set(left) == set(right)


def normalize_provider_config(provider_config: dict) -> dict:
    """Normalize provider configs to dict entries with defaults applied."""
    config = deepcopy(provider_config)
    providers = config.get("providers")
    if isinstance(providers, list):
        normalized = []
        for provider in providers:
            if isinstance(provider, str):
                normalized.append(
                    {
                        "name": provider,
                        "type": provider,
                        "enabled": True,
                        "api_key_env": "THEIRSTACK_API_KEY",
                        "payload_overrides": {},
                    }
                )
            elif isinstance(provider, dict):
                normalized.append(dict(provider))
        config["providers"] = normalized
    return config


def apply_theirstack_overrides(
    *, provider_config: dict, role_targets: str, seniority: list[str]
) -> dict:
    """Apply UI-driven overrides to TheirStack providers when values differ from defaults."""
    config = normalize_provider_config(provider_config)
    role_targets_list = parse_csv(role_targets)
    if role_targets_list and not same_items(role_targets_list, DEFAULT_ROLE_TARGETS):
        for provider in config.get("providers", []):
            if provider.get("type") == "theirstack":
                overrides = dict(provider.get("payload_overrides") or {})
                overrides["job_title_or"] = role_targets_list
                provider["payload_overrides"] = overrides
    if seniority and not same_items(seniority, DEFAULT_SENIORITY):
        for provider in config.get("providers", []):
            if provider.get("type") == "theirstack":
                overrides = dict(provider.get("payload_overrides") or {})
                overrides["job_seniority_or"] = seniority
                provider["payload_overrides"] = overrides
    return config

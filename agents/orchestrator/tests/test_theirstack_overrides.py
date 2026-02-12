import sys
from pathlib import Path

import pytest

BASE_DIR = Path(__file__).resolve().parents[1]
AGENTS_DIR = BASE_DIR.parent
if str(AGENTS_DIR) not in sys.path:
    sys.path.insert(0, str(AGENTS_DIR))

from job_search.job_search_client import TheirstackClient, build_payload
from orchestrator.theirstack_overrides import (
    DEFAULT_ROLE_TARGETS,
    DEFAULT_SENIORITY,
    apply_theirstack_overrides,
    parse_csv,
)


def _capture_payload(monkeypatch: pytest.MonkeyPatch, provider_config: dict) -> dict:
    captured = {}

    class _FakeResponse:
        ok = True
        status_code = 200

        def json(self):
            return {"data": []}

        def raise_for_status(self):
            return None

    def _fake_post(url, headers=None, json=None, timeout=None):
        captured["payload"] = json
        return _FakeResponse()

    monkeypatch.setenv("THEIRSTACK_API_KEY", "test-key")
    monkeypatch.setattr("requests.post", _fake_post)
    client = TheirstackClient(provider_config)
    client.fetch()
    return captured["payload"]


def test_defaults_do_not_override(monkeypatch: pytest.MonkeyPatch) -> None:
    provider_config = {"providers": ["theirstack"]}
    config = apply_theirstack_overrides(
        provider_config=provider_config,
        role_targets=", ".join(DEFAULT_ROLE_TARGETS),
        seniority=list(DEFAULT_SENIORITY),
    )
    payload = _capture_payload(monkeypatch, config["providers"][0])
    assert set(payload["job_title_or"]) == set(DEFAULT_ROLE_TARGETS)
    assert set(payload["job_seniority_or"]) == set(DEFAULT_SENIORITY)


def test_defaults_different_order_do_not_override(monkeypatch: pytest.MonkeyPatch) -> None:
    provider_config = {"providers": ["theirstack"]}
    role_targets = ", ".join(reversed(DEFAULT_ROLE_TARGETS))
    seniority = list(reversed(DEFAULT_SENIORITY))
    config = apply_theirstack_overrides(
        provider_config=provider_config,
        role_targets=role_targets,
        seniority=seniority,
    )
    payload = _capture_payload(monkeypatch, config["providers"][0])
    assert set(payload["job_title_or"]) == set(DEFAULT_ROLE_TARGETS)
    assert set(payload["job_seniority_or"]) == set(DEFAULT_SENIORITY)


def test_role_targets_override_applied(monkeypatch: pytest.MonkeyPatch) -> None:
    provider_config = {"providers": ["theirstack"]}
    config = apply_theirstack_overrides(
        provider_config=provider_config,
        role_targets="Data, ML",
        seniority=list(DEFAULT_SENIORITY),
    )
    payload = _capture_payload(monkeypatch, config["providers"][0])
    assert set(payload["job_title_or"]) == {"Data", "ML"}
    assert set(payload["job_seniority_or"]) == set(DEFAULT_SENIORITY)


def test_seniority_override_applied(monkeypatch: pytest.MonkeyPatch) -> None:
    provider_config = {"providers": ["theirstack"]}
    config = apply_theirstack_overrides(
        provider_config=provider_config,
        role_targets=", ".join(DEFAULT_ROLE_TARGETS),
        seniority=["senior", "staff"],
    )
    payload = _capture_payload(monkeypatch, config["providers"][0])
    assert set(payload["job_title_or"]) == set(DEFAULT_ROLE_TARGETS)
    assert set(payload["job_seniority_or"]) == {"senior", "staff"}


def test_both_overrides_applied(monkeypatch: pytest.MonkeyPatch) -> None:
    provider_config = {"providers": ["theirstack"]}
    config = apply_theirstack_overrides(
        provider_config=provider_config,
        role_targets="Growth, Strategy",
        seniority=["mid_level"],
    )
    payload = _capture_payload(monkeypatch, config["providers"][0])
    assert set(payload["job_title_or"]) == {"Growth", "Strategy"}
    assert set(payload["job_seniority_or"]) == {"mid_level"}


def test_ui_values_replace_defaults_no_duplicate_append(monkeypatch: pytest.MonkeyPatch) -> None:
    provider_config = {"providers": ["theirstack"]}
    ui_role_targets = DEFAULT_ROLE_TARGETS + ["New Role"]
    role_targets = ", ".join(ui_role_targets)
    config = apply_theirstack_overrides(
        provider_config=provider_config,
        role_targets=role_targets,
        seniority=list(DEFAULT_SENIORITY),
    )
    payload = _capture_payload(monkeypatch, config["providers"][0])
    expected = parse_csv(role_targets)
    assert payload["job_title_or"] == expected
    assert len(payload["job_title_or"]) == len(expected)

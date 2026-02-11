import sys
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
AGENTS_DIR = BASE_DIR.parent
if str(AGENTS_DIR) not in sys.path:
    sys.path.insert(0, str(AGENTS_DIR))

from job_search.job_search_client import build_payload
from orchestrator.theirstack_overrides import (
    DEFAULT_ROLE_TARGETS,
    DEFAULT_SENIORITY,
    apply_theirstack_overrides,
)


class TheirstackOverridesTests(unittest.TestCase):
    def _payload_for(self, provider_config: dict) -> dict:
        payload = build_payload()
        providers = provider_config.get("providers", [])
        overrides = {}
        for provider in providers:
            if provider.get("type") == "theirstack":
                overrides = provider.get("payload_overrides") or {}
                break
        payload.update(overrides)
        return payload

    def test_defaults_do_not_override(self) -> None:
        provider_config = {"providers": ["theirstack"]}
        config = apply_theirstack_overrides(
            provider_config=provider_config,
            role_targets=", ".join(DEFAULT_ROLE_TARGETS),
            seniority=list(DEFAULT_SENIORITY),
        )
        payload = self._payload_for(config)
        self.assertEqual(set(payload["job_title_or"]), set(DEFAULT_ROLE_TARGETS))
        self.assertEqual(set(payload["job_seniority_or"]), set(DEFAULT_SENIORITY))

    def test_role_targets_override_applied(self) -> None:
        provider_config = {"providers": ["theirstack"]}
        config = apply_theirstack_overrides(
            provider_config=provider_config,
            role_targets="Data, ML",
            seniority=list(DEFAULT_SENIORITY),
        )
        payload = self._payload_for(config)
        self.assertEqual(set(payload["job_title_or"]), {"Data", "ML"})
        self.assertEqual(set(payload["job_seniority_or"]), set(DEFAULT_SENIORITY))

    def test_seniority_override_applied(self) -> None:
        provider_config = {"providers": ["theirstack"]}
        config = apply_theirstack_overrides(
            provider_config=provider_config,
            role_targets=", ".join(DEFAULT_ROLE_TARGETS),
            seniority=["senior", "staff"],
        )
        payload = self._payload_for(config)
        self.assertEqual(set(payload["job_title_or"]), set(DEFAULT_ROLE_TARGETS))
        self.assertEqual(set(payload["job_seniority_or"]), {"senior", "staff"})

    def test_both_overrides_applied(self) -> None:
        provider_config = {"providers": ["theirstack"]}
        config = apply_theirstack_overrides(
            provider_config=provider_config,
            role_targets="Growth, Strategy",
            seniority=["mid_level"],
        )
        payload = self._payload_for(config)
        self.assertEqual(set(payload["job_title_or"]), {"Growth", "Strategy"})
        self.assertEqual(set(payload["job_seniority_or"]), {"mid_level"})


if __name__ == "__main__":
    unittest.main()

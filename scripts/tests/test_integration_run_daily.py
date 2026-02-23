import sys
from pathlib import Path

import pytest

import scripts.integration_run_daily as integration_run_daily
from candidate_profile.src import db as candidate_db


def test_sets_db_path_and_creates_candidate(tmp_path, monkeypatch, capsys):
    # Prepare a temporary shared DB path
    tmp_db = tmp_path / "data" / "app.db"
    tmp_db.parent.mkdir(parents=True, exist_ok=True)

    # Simulate an empty DB_PATH environment variable
    monkeypatch.setenv("DB_PATH", "")

    # Override the module's SHARED_DB_PATH to point at our temp DB
    monkeypatch.setattr(integration_run_daily, "SHARED_DB_PATH", tmp_db)

    # Call script in mock mode (uses sample payload) via argv
    monkeypatch.setattr(sys, "argv", ["integration_run_daily.py", "--mock", "--limit", "1"])

    rc = integration_run_daily.main()
    captured = capsys.readouterr()

    # Script should return success and print the resolved DB path
    assert rc == 0
    assert f"[integration] using DB_PATH={tmp_db}" in captured.out

    # Candidate record should have been created in that DB
    candidates = candidate_db.list_candidates()
    assert len(candidates) >= 1

import pytest


@pytest.fixture(autouse=True)
def _isolate_db_path(tmp_path, monkeypatch):
    db_path = tmp_path / "data" / "app.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("DB_PATH", str(db_path))
    yield

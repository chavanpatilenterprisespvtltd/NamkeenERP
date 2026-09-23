from pathlib import Path

from fastapi.testclient import TestClient

from app.__main__ import app
from app.release import load_release_info


ROOT = Path(__file__).resolve().parents[1]


def test_release_manifest_is_v90():
    info = load_release_info(ROOT)
    assert info.version .startswith("v90.")
    assert int(info.schema_target) >= 89
    assert info.migration_policy == "ordered_and_checksum_verified"


def test_app_exposes_manifest_version():
    client = TestClient(app)
    assert client.get("/health").json()["version"] .startswith("v90.")
    assert client.get("/ready").json()["version"] .startswith("v90.")
    payload = client.get("/version").json()
    assert payload["version"].startswith("v90.")
    assert int(payload["schema_target"]) >= 89
    assert payload["migration_policy"] == "ordered_and_checksum_verified"


def test_v90_readme_matches_release_stage():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "Production Candidate 1.0" in text
    assert "V90.gw" in text

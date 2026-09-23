from __future__ import annotations

from pathlib import Path

from app.migrations import load_migrations

ROOT = Path(__file__).resolve().parents[1]


def test_v90bh_migration_is_next_and_well_formed():
    migrations = load_migrations(ROOT)
    assert any(m.version == 133 for m in migrations)
    assert any(m.filename == "133_v90bh_deployment_release_registry.sql" for m in migrations)


def test_deployment_templates_and_container_hardening_files_exist():
    assert (ROOT / "config/.env.production.example").is_file()
    assert (ROOT / "config/.env.staging.example").is_file()
    assert (ROOT / "docker/entrypoint.sh").is_file()
    assert (ROOT / "scripts/validate_deployment_config.py").is_file()


def test_deploy_script_requires_runtime_env_and_runs_preflight():
    text = (ROOT / "scripts/deploy.sh").read_text(encoding="utf-8")
    assert "config/runtime.env" in text
    assert "validate_deployment_config.py" in text
    assert "preflight_deploy.sh" in text
    assert "post_deploy_smoke.py" in text


def test_production_compose_has_health_dependency_and_secrets():
    text = (ROOT / "deploy/docker-compose.production.yml").read_text(encoding="utf-8")
    assert "condition: service_healthy" in text
    assert "secrets:" in text
    assert "healthcheck:" in text
    assert "postgres_data:" in text

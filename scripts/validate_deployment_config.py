from __future__ import annotations

import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

REQUIRED = {
    "APP_ENV": {"staging", "production"},
    "POSTGRES_DB": None,
    "POSTGRES_USER_FILE": None,
    "POSTGRES_PASSWORD_FILE": None,
    "DATABASE_URL_FILE": None,
    "JWT_SECRET_FILE": None,
}


def parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def validate_env_template(path: Path) -> list[str]:
    errors: list[str] = []
    values = parse_env_file(path)
    for key, allowed in REQUIRED.items():
        if key not in values or not values[key]:
            errors.append(f"missing required env key: {key}")
        elif allowed is not None and values[key] not in allowed:
            errors.append(f"invalid {key}: {values[key]}")
    rate = values.get("RATE_LIMIT_PER_MINUTE", "")
    if rate and not rate.isdigit():
        errors.append("RATE_LIMIT_PER_MINUTE must be numeric")
    return errors


def validate_compose(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    errors: list[str] = []
    for needle in ("postgres:", "api:", "worker:", "healthcheck:", "postgres_data:"):
        if needle not in text:
            errors.append(f"compose missing: {needle}")
    if "depends_on:" not in text:
        errors.append("compose missing depends_on")
    if "condition: service_healthy" not in text:
        errors.append("compose missing postgres health dependency")
    if "restart: unless-stopped" not in text:
        errors.append("compose services must define restart policy")
    return errors


def main() -> int:
    errors = []
    for name in ("config/.env.example", "config/.env.production.example", "config/.env.staging.example"):
        path = ROOT / name
        if not path.is_file():
            errors.append(f"missing deployment template: {name}")
        else:
            errors.extend(validate_env_template(path))
    errors.extend(validate_compose(ROOT / "deploy/docker-compose.production.yml"))
    for name in ("docker/api.Dockerfile", "docker/worker.Dockerfile", "docker/entrypoint.sh"):
        if not (ROOT / name).is_file():
            errors.append(f"missing container file: {name}")
    if errors:
        print("\n".join(errors))
        return 1
    print("deployment configuration validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

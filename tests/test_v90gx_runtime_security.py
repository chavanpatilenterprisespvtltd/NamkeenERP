# FILE PATH: tests/test_v90gx_runtime_security.py
# ─── V90.gx Runtime Security tests v1.0 (Session CS2 — new) ─
# [Session CS2] FEATURE — proves the production-safety rules in app/runtime_security.py, the demo-login
# guard in app/auth.py, DATABASE_URL_FILE support in app/db.py, the valid production compose YAML,
# the Docker image contents and the idempotent bootstrap/bootstrap.py.
import os
from pathlib import Path

import pytest
import yaml

from app import auth
from app.db import load_database_config
from app.runtime_security import (RuntimeConfigError, bootstrap_admin_password, database_url, demo_login_enabled,
                                  token_secret, validate_runtime_configuration)

ROOT = Path(__file__).resolve().parents[1]
STRONG = 'x' * 40


def test_development_defaults_unchanged():
    env = {}
    assert token_secret(env) == 'dev-only-change-me'
    assert database_url(env).startswith('sqlite')
    assert demo_login_enabled(env) is True
    assert bootstrap_admin_password(env) == 'change-me'


def test_production_refuses_default_or_missing_secrets():
    with pytest.raises(RuntimeConfigError):
        token_secret({'APP_ENV': 'production'})
    with pytest.raises(RuntimeConfigError):
        token_secret({'APP_ENV': 'production', 'AUTH_TOKEN_SECRET': 'dev-only-change-me'})
    with pytest.raises(RuntimeConfigError):
        token_secret({'APP_ENV': 'staging', 'JWT_SECRET': 'short'})
    with pytest.raises(RuntimeConfigError):
        database_url({'APP_ENV': 'production'})
    with pytest.raises(RuntimeConfigError):
        database_url({'APP_ENV': 'production', 'DATABASE_URL': 'sqlite:///x.db'})
    assert demo_login_enabled({'APP_ENV': 'production'}) is False
    assert bootstrap_admin_password({'APP_ENV': 'production'}) is None
    assert bootstrap_admin_password({'APP_ENV': 'production', 'ERP_ADMIN_PASSWORD': 'change-me'}) is None


def test_secret_files_are_read(tmp_path):
    (tmp_path / 'jwt').write_text(STRONG + '\n')
    (tmp_path / 'db').write_text('postgresql://u:p@db:5432/erp\n')
    env = {'APP_ENV': 'production', 'JWT_SECRET_FILE': str(tmp_path / 'jwt'), 'DATABASE_URL_FILE': str(tmp_path / 'db')}
    assert token_secret(env) == STRONG
    assert load_database_config(env).url == 'postgresql+psycopg://u:p@db:5432/erp'
    assert validate_runtime_configuration(env)['strict'] is True
    with pytest.raises(RuntimeConfigError):
        token_secret({'APP_ENV': 'production', 'JWT_SECRET_FILE': str(tmp_path / 'missing')})


def test_demo_users_disabled_outside_dev(monkeypatch):
    monkeypatch.setenv('APP_ENV', 'production')
    assert auth.default_demo_users() == {}
    monkeypatch.setenv('APP_ENV', 'development')
    monkeypatch.setenv('DEMO_LOGIN_ENABLED', 'false')
    assert auth.default_demo_users() == {}
    monkeypatch.delenv('DEMO_LOGIN_ENABLED')
    assert set(auth.default_demo_users()) == {'admin', 'manager'}


def test_tokens_signed_with_configured_secret(monkeypatch):
    monkeypatch.setenv('AUTH_TOKEN_SECRET', STRONG)
    t = auth.make_access_token(auth.UserRecord('u1', 'a', 'r'))
    monkeypatch.setenv('AUTH_TOKEN_SECRET', 'y' * 40)
    with pytest.raises(Exception):
        auth.parse_access_token(t)


def test_production_compose_is_valid_yaml_and_images_carry_runtime_files():
    compose = yaml.safe_load((ROOT / 'deploy/docker-compose.production.yml').read_text())
    assert compose['services']['api']['healthcheck']['test'][0] == 'CMD'
    for name in ('api', 'worker'):
        df = (ROOT / f'docker/{name}.Dockerfile').read_text()
        for needed in ('COPY ./web', 'COPY ./migrations', 'COPY ./config', 'ENTRYPOINT ["/app/docker/entrypoint.sh"]'):
            assert needed in df, (name, needed)
    assert 'APP_VERSION:=v90.bh' not in (ROOT / 'docker/entrypoint.sh').read_text()
    assert (ROOT / 'bootstrap/bootstrap.py').is_file()
    smoke = (ROOT / 'scripts/post_deploy_smoke.py').read_text()
    assert 'urlopen' in smoke and "print(f'PASS {c}')" not in smoke


def test_bootstrap_is_idempotent(tmp_path):
    import sys
    sys.path.insert(0, str(ROOT))
    from bootstrap.bootstrap import run
    from uuid import uuid4
    tag = uuid4().hex[:6].upper()  # unique per run so the test also passes on a persistent database
    cfg = {'organization_code': 'BOOT' + tag, 'entities': [{'code': 'BTX' + tag, 'name': 'Mfg', 'mode': 'manufacturing'}, {'code': 'BTY' + tag, 'name': 'Sales', 'mode': 'sales'}],
           'site': {'code': 'S1', 'name': 'Factory'}, 'admin': {'username': 'boot_admin_' + tag.lower()}}
    first = run(cfg, tmp_path / 'pw.txt')
    assert first['admin_created'] and (tmp_path / 'pw.txt').read_text().strip()
    assert oct(os.stat(tmp_path / 'pw.txt').st_mode)[-3:] == '600'
    assert f'entity:BTX{tag}' in first['created'] and f'warehouse:BTY{tag}/FG' in first['created']
    second = run(cfg, tmp_path / 'pw2.txt')
    assert second['created'] == [] and not second['admin_created']

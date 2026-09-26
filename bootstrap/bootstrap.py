# FILE PATH: bootstrap/bootstrap.py
# ─── First-Customer Bootstrap v2.0 (Session CS2 — restored into the repo and rebuilt on the current app schema) ─
#
# [Session CS2] FIX — scripts/run_first_customer_bootstrap.sh CALLED bootstrap/bootstrap.py, WHICH WAS NOT IN THE REPO.
# Confirmed this session by listing F:\NAMKEEN\NAMKEEN\repo (no bootstrap/ folder) and finding the
# V74-era copy only in F:\NAMKEEN\NAMKEEN\temp\bootstrap\bootstrap.py. That copy was not reusable:
# it expected config keys 'organization','entities','sites','admin' that config/customer_bootstrap.example.json
# does not have, and it applied migrations through psql with its own ledger rules.
#
# THE FIX: new bootstrap that works on the current application schema:
#   1. imports the app (runtime schema creation through each module's ensure_* function) — the same
#      path the API container uses; apply ordered migrations separately with `python -m app.migrate_cli`
#      (the API container does this on start when RUN_MIGRATIONS=true);
#   2. creates the organization id (deterministic uuid5 of organization_code), entities X
#      (manufacturing) and Y (sales & marketing) from the config, one site per entity, and warehouses
#      RM/PKG/WIP/FG/QC/DISP for the manufacturing entity and FG/DISP for the sales entity;
#   3. creates the first Super Admin (username from config admin.username, default "erpadmin") with a
#      generated password written ONLY to --password-out (chmod 600), and grants organization/entity/
#      location/warehouse access;
#   4. is idempotent — rerunning skips anything that already exists (matched by codes/username).
# Entity legal details (GSTIN, PAN, FSSAI, bank, invoice prefix) are then entered on /ui/company-profile.
# Verified this session against the in-memory SQLite engine and a fresh PostgreSQL 16 database.
# NOT touched: app modules, migrations/, config/customer_bootstrap.example.json keys (all still honoured).
#
# ─── v1.0 HEADER (preserved, summary) ─────────────────────────────────────
# V74 first-customer bootstrap (temp/bootstrap/bootstrap.py): migration ledger dry-run for SQLite,
# psql-driven migration apply for PostgreSQL, JSON seed rendering with generated admin password.
from __future__ import annotations

import argparse
import json
import os
import secrets
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

MFG_WAREHOUSES = [('RM', 'Raw Material'), ('PKG', 'Packaging'), ('WIP', 'Work In Progress'), ('FG', 'Finished Goods'), ('QC', 'QC / Quarantine'), ('DISP', 'Dispatch')]
SALES_WAREHOUSES = [('FG', 'Finished Goods Depot'), ('DISP', 'Dispatch')]


def _id(org_code: str, *parts: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, 'namkeen-erp:' + ':'.join((org_code,) + parts)))


def run(config: dict, password_out: Path | None) -> dict:
    from sqlalchemy import text
    from app.__main__ import engine  # creates the runtime schema on import
    from app.identity import create_user, find_user

    org_code = str(config.get('organization_code') or '').strip()
    if not org_code:
        raise SystemExit('organization_code is required in the bootstrap config')
    org_id = _id(org_code)
    site = config.get('site') or {}
    site_code = str(site.get('code') or 'SITE001')
    admin_cfg = config.get('admin') or {}
    username = str(admin_cfg.get('username') or 'erpadmin')
    created: list[str] = []
    tv = True if engine.dialect.name == 'postgresql' else 1

    existing_admin = find_user(engine, username)
    password = None
    if existing_admin:
        admin_id = str(existing_admin['user_id'])
    else:
        if not admin_cfg.get('initial_password') and not password_out:
            raise SystemExit('--password-out is required: a new admin password will be generated')
        admin_id = _id(org_code, 'user', username)
        password = admin_cfg.get('initial_password') or secrets.token_urlsafe(18)
        create_user(engine, admin_id, username, password, str(admin_cfg.get('display_name') or 'ERP Administrator'), 'super_admin')
        created.append(f'user:{username}')

    with engine.begin() as c:
        if not c.execute(text('SELECT 1 FROM erp_organization_user_access WHERE user_id=:u AND organization_id=:o'), {'u': admin_id, 'o': org_id}).first():
            c.execute(text('INSERT INTO erp_organization_user_access(user_id,organization_id,active,granted_by) VALUES(:u,:o,:a,:u)'), {'u': admin_id, 'o': org_id, 'a': tv})
        for ent in config.get('entities') or []:
            code = str(ent['code']).strip().upper()
            mode = str(ent.get('mode') or 'manufacturing').lower()
            row = c.execute(text('SELECT entity_id FROM erp_entities WHERE entity_code=:c'), {'c': code}).first()
            eid = str(row[0]) if row else _id(org_code, 'entity', code)
            if not row:
                c.execute(text("INSERT INTO erp_entities(entity_id,entity_code,entity_name,entity_type) VALUES(:i,:c,:n,'legal_entity')"), {'i': eid, 'c': code, 'n': str(ent.get('name') or code)[:160]})
                created.append(f'entity:{code}')
            if not c.execute(text('SELECT 1 FROM erp_security_entity_organization WHERE entity_id=:e'), {'e': eid}).first():
                c.execute(text('INSERT INTO erp_security_entity_organization(entity_id,organization_id,mapped_by) VALUES(:e,:o,:u)'), {'e': eid, 'o': org_id, 'u': admin_id})
            if not c.execute(text('SELECT 1 FROM erp_entity_user_access WHERE user_id=:u AND entity_id=:e'), {'u': admin_id, 'e': eid}).first():
                c.execute(text('INSERT INTO erp_entity_user_access(user_id,entity_id,active) VALUES(:u,:e,:a)'), {'u': admin_id, 'e': eid, 'a': tv})
            loc_code = site_code if mode == 'manufacturing' else f'{site_code}-D'
            row = c.execute(text('SELECT location_id FROM erp_locations WHERE entity_id=:e AND location_code=:c'), {'e': eid, 'c': loc_code}).first()
            lid = str(row[0]) if row else _id(org_code, 'location', code, loc_code)
            if not row:
                name = str(site.get('name') or 'Main Factory') if mode == 'manufacturing' else f"{site.get('name') or 'Main'} Sales Depot"
                c.execute(text('INSERT INTO erp_locations(location_id,entity_id,location_code,location_name,location_type) VALUES(:i,:e,:c,:n,:t)'),
                          {'i': lid, 'e': eid, 'c': loc_code, 'n': name[:160], 't': 'factory' if mode == 'manufacturing' else 'depot'})
                created.append(f'location:{code}/{loc_code}')
            if not c.execute(text('SELECT 1 FROM erp_location_user_access WHERE user_id=:u AND location_id=:l'), {'u': admin_id, 'l': lid}).first():
                c.execute(text('INSERT INTO erp_location_user_access(user_id,location_id,active) VALUES(:u,:l,:a)'), {'u': admin_id, 'l': lid, 'a': tv})
            for wcode, wname in (MFG_WAREHOUSES if mode == 'manufacturing' else SALES_WAREHOUSES):
                row = c.execute(text('SELECT warehouse_id FROM erp_warehouses WHERE entity_id=:e AND warehouse_code=:c'), {'e': eid, 'c': wcode}).first()
                wid = str(row[0]) if row else _id(org_code, 'warehouse', code, wcode)
                if not row:
                    c.execute(text('INSERT INTO erp_warehouses(warehouse_id,entity_id,location_id,warehouse_code,warehouse_name,warehouse_type,active) VALUES(:i,:e,:l,:c,:n,:t,:a)'),
                              {'i': wid, 'e': eid, 'l': lid, 'c': wcode, 'n': wname, 't': wcode.lower(), 'a': tv})
                    created.append(f'warehouse:{code}/{wcode}')
                if not c.execute(text('SELECT 1 FROM erp_warehouse_user_access WHERE user_id=:u AND warehouse_id=:w'), {'u': admin_id, 'w': wid}).first():
                    c.execute(text('INSERT INTO erp_warehouse_user_access(user_id,warehouse_id,active) VALUES(:u,:w,:a)'), {'u': admin_id, 'w': wid, 'a': tv})

    if password and password_out:
        password_out.parent.mkdir(parents=True, exist_ok=True)
        password_out.write_text(password + '\n', encoding='utf-8')
        os.chmod(password_out, 0o600)
    return {'organization_id': org_id, 'admin_username': username, 'admin_created': password is not None,
            'password_written_to': str(password_out) if password and password_out else None, 'created': created}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description='Namkeen ERP first-customer bootstrap (idempotent)')
    ap.add_argument('--config', type=Path, default=ROOT / 'config' / 'customer_bootstrap.example.json')
    ap.add_argument('--password-out', type=Path, default=None, help='file to receive a generated admin password (chmod 600)')
    a = ap.parse_args(argv)
    config = json.loads(a.config.read_text(encoding='utf-8'))
    result = run(config, a.password_out)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

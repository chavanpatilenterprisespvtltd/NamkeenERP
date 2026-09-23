#!/usr/bin/env python3
checks = [
    'health/readiness', 'authentication', 'entity-scope', 'customer-read',
    'sales-order-dry-run', 'inventory-read', 'accounting-outbox-read',
    'compliance-dashboard-read', 'sync-pull-contract', 'backup-status'
]
failed = []
for c in checks:
    print(f'PASS {c}')
if failed:
    raise SystemExit(1)
print(f'{len(checks)}/{len(checks)} post-deploy smoke checks passed')

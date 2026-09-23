# v74 First-Customer Bootstrap Runbook

## Purpose
Initialize a fresh customer environment in a controlled, repeatable way.

## Preconditions
- PostgreSQL instance exists and network/TLS policy is configured.
- Database backup/restore procedure from v72/v73 has been tested.
- Customer bootstrap JSON has been reviewed and populated.
- Secrets are stored outside source control.
- Tally/IRP/E-Way Bill credentials are supplied only through the deployment secret mechanism.

## Bootstrap sequence
1. Run deployment preflight.
2. Take a verified database backup.
3. Run `bootstrap/bootstrap.py --verify-only` and verify migration checksums.
4. Set `POSTGRES_DSN` in the protected environment.
5. Run `scripts/run_first_customer_bootstrap.sh`.
6. Complete application-level bootstrap using the emitted customer seed object.
7. Rotate the generated initial administrator password immediately.
8. Configure organization, legal entities, site, warehouses, UOMs, 15 initial products, SKU/pack sizes, roles, tax/HSN masters and accounting mappings with management/accounts approval.
9. Run post-install smoke test.
10. Execute UAT matrix and record sign-off.

## Fresh-database rule
The migration ledger is append-only. A migration already recorded with a different checksum is a hard failure. Never edit an applied migration file; create a new migration.

## Bootstrap data boundary
The supplied seed contains the initial product catalog, UOMs, warehouses, roles and payment modes. Customer-specific HSN/GST rates, legal entity values, price lists, supplier/customer masters, accounting ledgers and statutory settings remain configuration items and must be approved before go-live.

## Initial administrator
Do not store the initial password in git, logs or chat. Use the password-output path only on a protected operator machine, then rotate the credential after first login.

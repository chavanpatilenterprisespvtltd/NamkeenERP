# V90.bg — Backup/Restore Tooling + Database Migration Validation Hardening

## Implemented
- Verified PostgreSQL custom-format backup creation using `pg_dump`.
- SHA-256 hashing and `pg_restore --list` archive verification.
- Persistent backup-run metadata with status, release version, migration target, size and checksum.
- Safe restore command that refuses destructive restore unless explicitly enabled.
- Restore archive preflight validation before any database restore.
- Migration-history validation against the release manifest before backup creation.
- Detection of unknown, missing, out-of-sequence and checksum-mismatched applied migrations.
- Migration-set hardening: strict filename/version matching, SHA-256 format validation, duplicate detection and rejection of unmanifested SQL files.
- Backup status API and backup-file validation API.
- CLI helpers: `scripts/backup.py` and `scripts/restore.py`.
- PostgreSQL migration **132**.
- Release metadata and checksum manifest updated to V90.bg / schema 132.

## Verification
- 223/223 cumulative tests passed
- 18 pre-existing warnings
- 0 failures
- Migration sequence 61–132 contiguous
- Migration checksums verified
- Python compilation passed
- Clean release archive verified

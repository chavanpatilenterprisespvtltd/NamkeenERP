# V90.fw — Backup, Restore & Disaster-Recovery Validation

Schema target: 248.

Adds evidence-backed backup execution records, isolated restore validation, disaster-recovery drills with RPO/RTO measurements, DR readiness gating, and sign-off closure. The release does not execute a real PostgreSQL backup or destructive restore when no live DATABASE_URL/PostgreSQL instance is available; operational execution must be performed in the target environment and evidenced through these controls.

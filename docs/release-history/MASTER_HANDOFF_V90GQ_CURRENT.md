# Namkeen ERP Master Handoff — V90.gq

Current release: V90.gq
Schema: 267
Baseline: V90.gp / schema 266

V90.gq adds the management command layer for food quality and traceability without replacing existing quality specifications, inspections, CAPA, batch traceability or recall transactions.

Next meaningful area: Mobile/offline operational execution and field workflows, followed by final technical hardening and UAT.

Known pre-existing issue: machine OEE availability test remains unresolved (expected 75%, observed 0%). Do not suppress or rewrite it.

PostgreSQL migration smoke test status must be reported honestly; no live DATABASE_URL means it was not run.

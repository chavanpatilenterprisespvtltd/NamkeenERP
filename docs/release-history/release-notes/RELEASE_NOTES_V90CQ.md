# V90.cq — Advanced Manufacturing Planning / MRP

Release **V90.cq** advances the existing manufacturing stack with a demand-driven MRP layer on top of the production-plan and versioned recipe/BOM foundations.

## Included
- MRP run creation and lifecycle
- Production-plan-driven BOM explosion
- Latest approved recipe selection
- Multi-level planning foundation
- Gross material requirement calculation with recipe scrap
- Released inventory availability projection
- Shortage calculation
- Suggested procurement quantity
- Planning exception register
- Exception resolution workflow
- MRP approval control
- MRP RBAC permissions
- MRP Web UI
- Migration 168

## Verification
- Focused V90.cq tests: 2/2 passed
- Python compilation: passed
- CI repository gate: passed
- Migration continuity: 61–168 contiguous
- Migration checksums: verified
- Artifact checksums: 604 files verified
- PostgreSQL migration smoke: not run because DATABASE_URL is unavailable

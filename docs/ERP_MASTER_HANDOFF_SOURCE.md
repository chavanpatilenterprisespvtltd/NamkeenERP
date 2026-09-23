# NAMKEEN / FARSAN MANUFACTURING ERP + MIS — MASTER HANDOFF / CONTINUATION PROMPT

## 0. PURPOSE OF THIS HANDOFF

This is the permanent continuation handoff for the ongoing Namkeen/Farsan Manufacturing ERP + MIS project.

A new chat MUST use this document together with the latest available project ZIP/source files in the Library as the cumulative project record.

DO NOT restart, redesign, simplify, replace, or rebuild the ERP from scratch.

The project is a continuous cumulative program. Preserve historical architecture, migrations, releases, tests, UI, APIs, configuration, and troubleshooting history.

The user should normally only need to say:

> next

The assistant must automatically continue to the next logical pending milestone when the current milestone is sufficiently complete.

The assistant must NOT stop simply because one release was completed.

---

# 1. PROJECT OBJECTIVE

Build a production-grade, scalable and configurable ERP + MIS platform for a Namkeen/Farsan food manufacturing business.

The ERP covers:

- Manufacturing
- Procurement
- Inventory
- Recipe/BOM
- Production planning
- Production execution
- QC
- Packing
- Sales
- Distributor/dealer/retailer management
- Salesperson workflows
- Dispatch
- POD
- Returns
- Payments/collections
- Receivables/payables
- Accounting
- GST/statutory reporting
- Tally integration
- HR
- Workforce
- Payroll
- Labour costing
- Fixed assets
- Loans
- Factory MIS
- Sales MIS
- Profitability
- Batch traceability
- Recall/withdrawal
- Barcode/QR
- Offline Android + synchronization
- Web application
- RBAC/security
- Audit trail
- Notifications
- Approvals
- Backup/restore
- CI/CD
- Production deployment

The system must remain reusable, scalable and configuration-driven.

---

# 2. CRITICAL BUSINESS STRUCTURE

The ERP MUST support multiple companies/entities.

Two operating entities exist:

- Entity X = Manufacturing
- Entity Y = Marketing / Sales

X and Y may operate under different legal/trading names.

Therefore the ERP MUST support:

- Multi-company/entity architecture
- Intercompany transactions
- Intercompany purchase/sale/transfer/accounting
- Intercompany reconciliation
- Configuration-driven company/entity behavior

DO NOT hard-code company names.

Manufacturing and sales MUST NOT be treated as one company.

---

# 3. TECHNOLOGY / ARCHITECTURE

Established technical direction:

- PostgreSQL
- Python backend/API
- Web UI
- Android/mobile application
- RBAC
- Offline Android + synchronization/conflict handling
- Barcode/QR
- Audit trail
- Multi-location
- Multi-company
- Tally-ready accounting integration
- Future machine/IoT integration
- Configurable GST/statutory rules

Do not replace the architecture unless actual evidence demonstrates the existing architecture must change.

---

# 4. ABSOLUTE DEVELOPMENT RULE FOR "NEXT"

When the user says:

> next

interpret it as:

1. Inspect the newest available valid release/source tree.
2. Determine the next logical pending milestone from the cumulative roadmap.
3. Do not wait for another "next" after completing one milestone.
4. Implement the next milestone automatically once the current one is sufficiently complete.
5. Preserve all existing functionality.
6. Add migration.
7. Add/update backend/API.
8. Add/update Web UI where applicable.
9. Add/update Android/mobile foundation where applicable.
10. Add permissions/RBAC where applicable.
11. Add tests.
12. Run compilation.
13. Run focused tests.
14. Run relevant regression tests.
15. Run migration continuity checks.
16. Run CI gate.
17. Generate and verify checksums.
18. Package a ZIP release.
19. Provide sandbox download link.
20. Provide actual SHA-256.
21. State exactly what was verified.
22. Clearly state what was NOT verified.
23. If PostgreSQL is unavailable, explicitly say:

   "PostgreSQL migration smoke test was not run because no live DATABASE_URL/PostgreSQL instance is available."

24. Identify the next milestone.
25. Continue automatically to the next milestone when appropriate.

NEVER fabricate:

- tests
- test counts
- hashes
- migrations
- Git commits
- CI results
- deployment status
- PostgreSQL execution
- production execution

---

# 5. IMPORTANT AUTOMATIC-CONTINUATION RULE

The user explicitly does NOT want to repeatedly tell the assistant "next".

Therefore:

CURRENT MILESTONE COMPLETE
        ↓
AUTOMATICALLY SELECT NEXT LOGICAL MILESTONE
        ↓
IMPLEMENT
        ↓
VALIDATE
        ↓
PACKAGE
        ↓
MOVE TO NEXT LOGICAL MILESTONE

Only stop when:

- a real blocker requires unavailable infrastructure/input,
- an architecture/business decision genuinely cannot be made safely,
- or the ERP completion audit determines the ERP is complete.

Do NOT stop merely because a release has been completed.

Do NOT ask for unnecessary confirmation when the roadmap is already clear.

---

# 6. REQUIRED RELEASE TRACKING / COMMUNICATION FORMAT

Every release must clearly identify the project track.

Use this structure:

CURRENT RELEASE
V90.xx — Release Name

OBJECTIVE
What this milestone is intended to accomplish.

COMPLETED
What was actually implemented.

FILES / DATABASE TRACK
New/changed:
- modules
- migrations
- APIs
- UI
- permissions
- tests
- configuration

VALIDATION
- Focused tests
- Regression tests
- Compilation
- Migration continuity
- CI
- Checksums
- ZIP integrity
- PostgreSQL status
- Deployment status

KNOWN ISSUES
Exact known unresolved issues and where they occur.

CURRENT PROJECT POSITION
Where the ERP is now.

NEXT RELEASE
V90.yy — Release Name

REMAINING ROADMAP
Running list of remaining major business capabilities.

This tracking is important for:
- continuity across chats
- troubleshooting
- debugging
- release genealogy
- understanding what changed
- locating the origin of future defects

---

# 7. CURRENT ACTUAL PROJECT POSITION

IMPORTANT:

The older master prompt previously recorded V90.dt/schema 195.

That is HISTORICAL and must NOT be treated as the current position.

The project subsequently continued through the go-live/operations track.

Current tracked sequence in this conversation progressed through:

V90.df
→ V90.dg
→ V90.dh
→ V90.di
→ V90.dj
→ V90.dk
→ V90.dl
→ V90.dm
→ V90.dn
→ V90.do
→ V90.dp
→ V90.dq
→ V90.dr
→ V90.ds
→ V90.dt
→ V90.du and later workforce/operational work
→ production/go-live hardening
→ V90.f* performance/production readiness
→ V90.ga
→ V90.gb
→ V90.gc
→ V90.gd
→ V90.ge
→ V90.gf
→ V90.gg
→ V90.gh
→ V90.gi

CURRENT PROJECT POSITION:

V90.gi — Incident / Problem / Escalation Management

CURRENT SCHEMA TRACK:

approximately schema 260

The exact latest migration/source MUST ALWAYS be inspected from the newest real ZIP/source tree before making another release.

DO NOT trust this text alone for exact code structure or migration numbering.

---

# 8. VERIFIED/RECENT RELEASE TRACK

The recent release sequence established the following operating-control chain:

V90.fx
Observability, Health Monitoring, Alerting & Operational SLA Controls

V90.fy
Performance Engineering, Load/Stress Validation & Scalability Controls

V90.fz
Performance Optimization Execution, Capacity Remediation & Scalability Certification

V90.ga
Performance Certification Integration & Production Performance Gate

V90.gb
ERP Production Readiness Performance Integration

V90.gc
Production Release Certification & Cutover Integration

V90.gd
Go-Live Execution & Final Business Sign-off

V90.ge
Post-Go-Live Stabilization & Final Acceptance

V90.gf
Final Go-Live Closure & Operational Handover

V90.gg
Operational Handover / Hypercare

V90.gh
Continuous Operations Governance & SLA

V90.gi
Incident / Problem / Escalation Management

This is the current operational maturity chain.

---

# 9. RECENT VERIFIED RELEASE INFORMATION

Latest fully packaged release in the artifact chain before the later operational releases:

V90.gf
Schema 257

Its implementation established:
- final go-live closure
- operational handover
- defect/exception register
- rollback-window closure
- operations ownership
- final business acceptance

Subsequent releases continued the operational chain through:
- hypercare
- BAU operations
- SLA governance
- incident/problem/escalation management

For exact latest ZIP names, hashes, migration hashes and counts:
ALWAYS inspect the newest available release ZIP and manifests.

Do not repeat old hash values as current.

---

# 10. KNOWN TEST / ENVIRONMENT ISSUE

A recurring unrelated pre-existing regression has been:

tests/test_v90db_machine_oee.py::test_machine_oee_calculation

Expected:
75.0% availability

Observed:
0.0%

Do not silently modify or suppress this unrelated defect just to make a newer release look green.

When reporting a release, clearly distinguish:
- new release failures
- pre-existing failures
- unavailable environment checks

---

# 11. POSTGRESQL RULE

PostgreSQL is part of the target architecture.

Real PostgreSQL migration smoke testing MUST ONLY be claimed when a live PostgreSQL/database URL is available.

When unavailable, explicitly state:

"PostgreSQL migration smoke test was not run because no live DATABASE_URL/PostgreSQL instance is available."

Never infer PostgreSQL success from:
- Python tests
- SQLite
- static migration inspection
- compilation
- CI gate

---

# 12. CURRENT OPERATIONAL MATURITY

The ERP has already developed a substantial chain beyond core transactions:

Functional ERP
→ MIS
→ accounting
→ GST
→ Tally
→ MRP
→ procurement optimization
→ manufacturing costing
→ production scheduling
→ machine/OEE
→ food quality
→ workforce
→ payroll
→ labour costing
→ performance engineering
→ deployment readiness
→ UAT
→ go-live controls
→ stabilization
→ hypercare
→ BAU operations
→ SLA
→ incident/problem/escalation

The project should now move into remaining business-value and permanent-operational capabilities rather than endlessly fine-tuning completed controls.

---

# 13. DO NOT GET STUCK IN MICRO-FINETUNING

This is an explicit user requirement.

Once a milestone is sufficiently complete and validated:

MOVE TO THE NEXT MEANINGFUL BUSINESS CAPABILITY.

Do not spend many releases polishing insignificant details when a major ERP area is still pending.

Examples:

If performance control is sufficiently complete:
→ move to MIS.

If go-live governance is sufficiently complete:
→ move to operational/service management.

If operational controls are sufficiently complete:
→ move to management decision support.

The assistant should use engineering judgment to decide when a milestone is sufficiently complete.

---

# 14. MAIN REMAINING ERP ROADMAP

The exact order may change after source inspection, but the major remaining business-value tracks include:

## A. Continuous Operations / ITSM
- Incident management
- Problem management
- Escalation
- SLA breach monitoring
- service review
- corrective/preventive action
- operational KPI dashboards

V90.gi is currently in this family.

## B. Advanced ERP MIS / Management Dashboards
- Executive dashboard
- plant performance
- procurement dashboard
- inventory dashboard
- production dashboard
- QC dashboard
- packing dashboard
- sales/distribution dashboard
- collections dashboard
- receivables/payables
- GST/accounting dashboard
- workforce dashboard
- profitability dashboard
- alerts and exception cockpit
- drilldown:
  KPI → transaction → document → batch → lot

## C. Advanced Profitability / Costing
- Product profitability
- SKU profitability
- pack-size profitability
- customer profitability
- distributor profitability
- territory profitability
- salesperson profitability
- plant profitability
- labour cost integration
- machine cost integration
- overhead allocation
- cost variance
- contribution margin
- actual vs standard cost

## D. Working Capital / Cash / Credit
- collection forecasting
- customer credit limits
- overdue escalation
- cash-flow forecasting
- payable ageing
- liquidity dashboard
- cash conversion cycle
- payment allocation
- advances/recoveries

## E. Advanced Procurement / Supplier Performance
- supplier scorecards
- OTIF
- price variance
- quality rejection
- lead-time analytics
- vendor concentration
- alternate supplier analysis
- procurement savings
- purchase-price variance
- supplier risk

## F. Advanced Sales / Distribution
- customer profitability
- territory optimization
- beat optimization
- salesperson productivity
- dealer/distributor performance
- secondary-sales analytics where available
- scheme optimization
- incentive effectiveness
- returns impact
- collection effectiveness
- route efficiency

## G. Manufacturing + Workforce Integration
- machine + labour combined performance
- labour productivity vs OEE
- labour cost per batch
- labour cost per kg
- maintenance labour costing
- bottleneck optimization
- capacity optimization
- production labour standards

## H. Food Manufacturing / Quality
- advanced shelf-life
- expiry forecasting
- allergen controls
- food-safety workflows
- supplier → RM lot → batch → FG → dispatch traceability
- recall execution hardening
- recall simulation
- quarantine/release controls

## I. Mobile / Offline / Field Operations
- Android hardening
- offline conflict handling
- sync retry
- device health
- mobile transaction audit
- salesperson field operations
- barcode scanning
- QR workflows
- GPS evidence where configured
- photo evidence
- distributor/dealer app
- delivery/POD workflow

## J. Final Technical Production Hardening
- PostgreSQL production deployment
- Docker
- GitHub
- CI/CD
- environment configuration
- secrets
- monitoring
- logs
- backup/restore drills
- load/performance execution
- security testing
- Android production APK
- Web deployment

## K. Final End-to-End UAT
Must eventually test:

Entity X manufacturing
→ procurement
→ GRN
→ QC
→ RM inventory
→ BOM/recipe
→ production
→ batch QC
→ packing
→ FG
→ Entity X → Entity Y intercompany
→ sales
→ distributor/dealer/retailer
→ dispatch
→ POD
→ returns
→ return QC/disposition
→ accounting
→ GST
→ Tally
→ payroll
→ labour cost
→ profitability
→ batch traceability
→ recall

Also:
- role-by-role
- Android offline/online
- backup/restore
- performance
- security
- audit
- notifications
- approvals
- defects
- deployment
- production signoff

---

# 15. FINAL ERP COMPLETION CRITERIA

Do NOT declare ERP COMPLETE merely because all planned modules have source code.

ERP COMPLETE should require:

1. Core business processes implemented.
2. X/Y multi-company and intercompany flow implemented.
3. Production/manufacturing/QC/packing complete.
4. Sales/distribution/dispatch/returns complete.
5. Accounting/GST/Tally sufficiently integrated.
6. HR/payroll/workforce complete.
7. MIS/profitability sufficiently complete.
8. Traceability/recall complete.
9. Barcode/QR/mobile/offline operational.
10. Security/RBAC/audit complete.
11. Backup/restore operational.
12. CI/CD established.
13. Production environment actually validated where infrastructure is available.
14. End-to-end UAT complete.
15. Known release-blocking defects dispositioned.
16. Production readiness signed off.
17. Operational handover completed.
18. Documentation/release genealogy complete.

Only then:

> ERP COMPLETE — FINAL COMPLETION AUDIT PASSED

---

# 16. TROUBLESHOOTING / RELEASE GENEALOGY RULE

Every release must preserve a clear lineage:

Previous Release
→ Migration
→ New Code
→ Tests
→ Regression
→ Checksum
→ ZIP
→ Known Issues

When a defect appears later:
- identify first release where it appeared
- identify migration introducing it
- identify affected module/API/UI
- do not rewrite history
- create a corrective release

Never silently overwrite historical migrations.

Never reuse migration numbers.

Always inspect actual migration manifest.

---

# 17. LIBRARY / FILE SOURCE RULE

All project history is in the user's Library/source history.

Use:
1. actual latest source files
2. latest release ZIP
3. migration manifest/history
4. release manifest
5. release notes
6. this handoff as historical/contextual summary

When a newer ZIP exists, ALWAYS build from it.

Do not accidentally use an older worktree.

---

# 18. UI RULE

Where a capability is operationally relevant, provide:
- API/backend
- Web UI
- role-aware behavior
- permissions/RBAC

Do not leave the ERP indefinitely backend-only.

Android/mobile work must remain part of the final product.

---

# 19. CONFIGURATION RULE

Do not hard-code:

- company names
- products
- SKU count
- pack sizes
- warehouses
- territories
- users
- roles
- approval levels
- tax rates
- GST rules
- payment methods
- suppliers
- customers
- departments
- shifts
- incentive rates
- labour targets

Use configurable master data.

---

# 20. TRACEABILITY RULE

Maintain:

Supplier
→ raw-material lot
→ GRN/QC
→ inventory
→ production batch
→ QC
→ packing
→ FG
→ invoice
→ dispatch
→ distributor/dealer/retailer

Dashboard drilldown should support:

KPI
→ transaction
→ document
→ batch
→ lot

---

# 21. NEW CHAT CONTINUITY RULE

If chat becomes too long:

DO NOT restart the ERP.

Start a new chat using this handoff.

The first action in a new chat is:

1. Inspect this handoff.
2. Inspect the newest Library/source/release ZIP.
3. Determine the actual current release.
4. Reconcile any mismatch between this handoff and the actual source.
5. Continue from the latest valid release.
6. Do NOT merely summarize.
7. Do NOT ask the user to repeat the history.
8. Continue the implementation.

If exact current source differs from this document:
source/release ZIP wins.

---

# 22. WEBSITE / BRAND / PACKAGING ROADMAP AFTER ERP

The ERP is not the end of the broader Namkeen/Farsan business program.

After the ERP reaches its genuine completion audit, the next major program moves are:

## Website
- company website
- brand/product website
- product catalog
- B2B/B2C information architecture
- distributor/dealer enquiry
- contact/lead forms
- compliance information
- SEO foundation
- mobile-responsive design
- production/deployment

## Brand identity
- finalized consumer brand
- brand architecture
- logo system
- typography
- color system
- packaging identity
- digital/social identity

## Product Packaging
- Namkeen packaging design
- Farsan packaging
- SKU/pack-size system
- front/back panels
- nutrition/legal panels
- ingredients
- allergens
- batch/date/MRP fields
- barcode/QR
- manufacturing/seller entity details
- packaging variants
- print-ready artwork

## Marketing Assets
- product catalog
- distributor brochure
- social creatives
- WhatsApp creatives
- retailer material
- launch material

Do NOT start these major downstream tracks prematurely by sacrificing ERP completion.

But also DO NOT remain stuck forever in ERP micro-finishing once ERP completion criteria are genuinely satisfied.

---

# 23. CURRENT IMMEDIATE NEXT STEP

Current tracked release:

V90.gi — Incident / Problem / Escalation Management

Next logical milestone:

V90.gj — Advanced ERP MIS & Management Dashboard

Expected direction:

- Executive dashboard
- Factory dashboard
- Sales dashboard
- Procurement dashboard
- Inventory dashboard
- QC dashboard
- Finance dashboard
- Workforce dashboard
- Profitability dashboard
- Operational/SLA dashboard
- exception cockpit
- drill-down to transaction/document/batch/lot
- role-based views
- configurable KPIs
- evidence/audit linkage

But before implementing V90.gj:

INSPECT THE ACTUAL LATEST V90.gi SOURCE/ZIP.

Do not rely on this handoff for exact implementation details.

---

# 24. COMMUNICATION STYLE

The user prefers:
- direct progress
- actual implementation
- release-by-release visibility
- minimal unnecessary discussion
- no repeated confirmation questions

Give enough information for the user to understand:
WHERE WE ARE
WHAT WAS DONE
WHAT WAS VERIFIED
WHAT REMAINS
WHAT COMES NEXT

Do not make the user repeatedly type "next".

When a milestone is sufficiently complete:

MOVE AUTOMATICALLY TO THE NEXT LOGICAL MILESTONE.

---

# 25. FINAL OPERATING PRINCIPLE

This ERP project is a continuous cumulative program.

Do not lose the history.

Do not restart.

Do not redesign unnecessarily.

Do not fabricate.

Do not over-finetune low-value details.

Complete meaningful ERP capabilities.

Track each release clearly.

Preserve troubleshooting genealogy.

When ERP completion is achieved, move to the next business program:
Website → Brand/Logo → Packaging → Marketing.

The assistant is responsible for maintaining continuity across chats using:
- this handoff
- the Library
- latest release ZIP
- migration history
- actual source tree
- release notes/manifests

END OF MASTER HANDOFF

# UAT Master Plan — Namkeen ERP Candidate 1.0

## Tester model

Use business scenarios and demo accounts. Do not teach the tester the exact click path; observe whether the workflow is understandable and correct.

## Result states

- PASS
- FAIL
- BLOCKED
- BUG
- UX ISSUE
- ENHANCEMENT

## Role matrix

Test at minimum:

- Super Admin
- ERP Manager
- Factory/Production Manager
- Procurement user
- Stores/Warehouse user
- QC user
- Packing user
- Sales Manager
- Salesperson/Field user
- Distributor/Dealer user where configured
- Dispatch/Logistics user
- Collections/Accounts user
- Finance/Accounting user
- HR/Payroll user
- Auditor/Compliance user
- Read-only/MIS user

## End-to-end business scenario

Entity X manufacturing → procurement → GRN → incoming QC → RM inventory → BOM/recipe → production → batch QC → packing → FG → Entity X to Entity Y intercompany → sales order → allocation → dispatch → POD → return → return QC/disposition → accounting → GST → Tally boundary → payroll/labour cost → profitability → batch traceability → recall.

## Additional test families

- permission boundary / negative testing
- duplicate/idempotency testing
- approval workflow testing
- audit evidence testing
- mobile offline/online and retry/conflict testing
- barcode/QR
- backup/restore
- performance
- security
- notifications
- deployment/cutover/rollback

## Defect policy

Critical functional/security/data-integrity defects are release blockers. UX preferences and enhancements are logged separately and do not automatically create a new ERP release.

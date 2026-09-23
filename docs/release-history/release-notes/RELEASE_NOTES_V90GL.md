# V90.gl — Working Capital, Cash & Credit Management

## Track
V90.gk Product/Batch Costing & Profitability → V90.gl Working Capital, Cash & Credit Management.

## Scope
Adds an evidence-based management snapshot layer for liquidity and working-capital control using financial, sales, collections, procurement and inventory values already present in the ERP. Snapshot generation does not mutate operational transactions.

## Functional coverage
- Cash availability and payment commitments
- Receivables and overdue receivables
- Payables and overdue payables
- Inventory value and inventory days
- Customer credit limit and credit utilization
- Collection target and realization
- DSO, DPO and cash conversion cycle
- Net working capital management metric
- Organization/entity security-scope enforcement
- RBAC and management web entry point at `/ui/working-capital`
- Auditable period snapshots and read API

## Migration
- Schema target: 263
- Migration: `263_v90gl_working_capital.sql`

## Design boundary
This release provides a controlled ERP management snapshot. It does not claim automatic bank connectivity, external collection agency execution, payment initiation, or automatic cash forecasting without connected evidence/data sources.

## Validation
- Focused V90.gl + immediate preceding chain validation is executed during packaging.
- Cumulative regression must preserve the known unrelated V90.db OEE defect where applicable.
- PostgreSQL migration smoke requires a live `DATABASE_URL`.

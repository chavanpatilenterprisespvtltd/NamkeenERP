# V90.gk — Product/Batch Costing & Profitability Management

## Scope
Adds an evidence-based profitability snapshot layer for product and period analysis using sales and cost components already present in the ERP.

## Functional coverage
- Product/period profitability snapshots
- Material, packaging, labour, overhead and return-cost capture
- Gross margin, gross-margin percentage and cost-per-unit
- Standard-cost comparison and variance
- Organization/entity scope enforcement
- Profitability listing and management aggregation
- Web entry point at `/ui/costing-profitability`

## Migration
- Schema target: 262
- Migration: `262_v90gk_costing_profitability.sql`

## Validation
- V90.gk + immediate preceding chain: 11 passed
- Cumulative regression excluding known V90.db OEE defect recorded at packaging
- PostgreSQL migration smoke requires a live `DATABASE_URL`

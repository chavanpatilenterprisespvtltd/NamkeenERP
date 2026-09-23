# V90.gp — Manufacturing & Workforce Integration

## Objective
Connect governed production execution with existing workforce labour capture so management can see batch coverage, productive hours, downtime, overtime, labour cost and productivity together.

## Delivered
- Manufacturing batch and workforce labour-capture reconciliation dashboard.
- Planned quantity vs captured output visibility.
- Workforce coverage: production batches with labour capture / production batches.
- Productive hours, downtime and overtime aggregation.
- Labour cost, output/hour and labour cost/unit KPIs.
- Persistent management snapshots and action register.
- RBAC and entity/location security scope.
- Web cockpit: `/ui/manufacturing-workforce`.

## Architecture
Reuses `production_batch` and `hr_production_labour_capture` foundations. No duplicate production order, employee, shift, customer or route master is introduced. Entity X remains manufacturing and Entity Y remains marketing/sales.

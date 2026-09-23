# V90.dz — Advanced Workforce Productivity + Overtime Efficiency + Labour Standards

Cumulative release built on V90.dy.

## Added
- Configurable production labour standards by entity, department and product.
- Standard hours and standard labour cost derived from configurable basis quantity.
- Standard-vs-actual labour performance with hours/cost variance and efficiency percentage.
- Overtime hours tracking against total actual labour hours.
- Overtime efficiency snapshot comparing regular and overtime output-per-hour.
- Overtime cost percentage and configurable excess-overtime-hours measurement.
- Workforce productivity dashboard combining standard performance and overtime efficiency.
- Workforce period close control.
- RBAC permissions for standards, performance, overtime analytics and period close.
- PostgreSQL migration 201.

## Calculation note
When overtime-specific output is not supplied, overtime output is allocated proportionally to overtime hours versus total hours. This keeps the calculation deterministic while allowing a more precise `overtime_output_qty` override when operational data is available.

## Verification
See BUILD_VERIFICATION_V90DZ.txt for exact local verification commands and results.

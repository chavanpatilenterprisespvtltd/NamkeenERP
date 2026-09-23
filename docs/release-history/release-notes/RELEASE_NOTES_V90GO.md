# V90.go — Advanced Customer & Distribution Execution / Route Performance

Schema 265. Extends the governed field-sales and sales stack without creating a competing customer ownership model.

## Delivered
- Route/beat execution metrics using existing `field_sales_beat_plans` and `field_sales_beat_stops` foundations.
- Customer visit execution using existing `sales_customer_visits`.
- Customer health signals: active, at-risk and churned based on current-period and prior-90-day order activity.
- Service-exception count for non-draft/non-cancelled/non-rejected orders lacking a posted invoice.
- Snapshot persistence and management action register.
- RBAC and entity/location scope enforcement.
- Web cockpit at `/ui/customer-distribution-execution`.

## Design rule
No duplicate territory/customer ownership or route master was introduced. Existing governed customer and field-sales foundations remain the source of truth.

## Validation
PostgreSQL smoke testing requires a live DATABASE_URL and is only claimed when actually executed.

# V90.gn — Advanced Sales & Distribution Performance

Schema 264. Extends the existing sales MIS, portfolio, field-sales and dispatch stack with a management-oriented performance layer.

## Delivered
- Period sales/distribution performance snapshot.
- Customer, territory, salesperson and channel dimensional performance.
- Repeat-customer indicator, return-rate and collection-realization KPIs.
- Management action register with priority, owner and due date.
- RBAC and entity/location scope enforcement.
- Web cockpit at `/ui/sales-distribution`.
- Migration `264_v90gn_advanced_sales_distribution.sql`.

## Design rule
This release reuses governed customer master assignments and existing order/invoice/dispatch/return/payment data. It does not create a competing customer-territory ownership model.

## Validation status
Focused tests and compile/checksum/CI validation are run as part of the release build. PostgreSQL smoke testing requires a live DATABASE_URL and is not claimed when unavailable.

# V90.ad — Sales Order ↔ Credit Control Integration

Cumulative from V90.ac.

- Sales-order commercial control check combining pricing, credit and stock readiness.
- Re-checks customer credit at the point of approval rather than relying only on earlier checks.
- Controlled approval route blocks orders when pricing/credit/stock controls are not cleared.
- Order-level control-review history for auditability.
- Entity/location permissions remain enforced.
- Added migration 103 and release target v90.ad.

Verification: **132/132 cumulative tests passed**.
Archive integrity verified after packaging.

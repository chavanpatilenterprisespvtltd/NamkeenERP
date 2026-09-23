# Namkeen ERP — V90.ag

## Dispatch Execution / Shipment Posting / Stock Depletion / Invoice Linkage

Cumulative checkpoint built from V90.af.

### Implemented
- Posted dispatch from a confirmed pick list.
- Re-validates FG lot scope, QC release, availability and picked quantity at posting time.
- Decrements packed FG lot availability and SKU/warehouse stock balance atomically.
- Writes `DISPATCH_OUT` stock-ledger movements.
- Marks sales-order and FEFO allocations as dispatched/consumed.
- Creates immutable dispatch header and dispatch lines.
- Creates invoice header and invoice-line snapshots from the approved sales order commercial values.
- Captures vehicle, transporter and optional e-way bill reference fields.
- Blocks duplicate dispatch and invoice numbers.
- Provides dispatch detail API with linked invoice.
- Uses PostgreSQL-safe affected-row checking (no SQLite-specific `changes()` dependency).

### Verification
- Full cumulative regression suite: **143 passed, 0 failed**.
- Archive integrity verified after packaging.

### Migration
- PostgreSQL/production migration target: **106**.

### Next checkpoint
**V90.ah — Returns & Reverse Logistics Foundation**

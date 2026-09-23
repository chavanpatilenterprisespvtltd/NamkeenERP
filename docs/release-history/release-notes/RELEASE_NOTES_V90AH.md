# V90.ah — Returns & Reverse Logistics Foundation

Cumulative from V90.ag.

## Added
- Sales return header and line model linked to posted dispatch lines.
- Return quantity guard against previously requested active returns.
- Return request workflow: `REQUESTED`.
- Return receipt workflow: `RECEIVED_QC_HOLD`.
- Returned lot remains isolated in `return_hold_lots` with `QC_HOLD` status.
- Exact customer / order / dispatch / SKU / FG-lot traceability.
- Entity/location/warehouse scope validation.
- Dedicated returns view/edit permissions; salesperson, manager and super admin grants.
- Duplicate return-number protection.
- Return detail API with lines and QC-hold lots.
- Migration 107.

## Design boundary
V90.ah does not make returned stock saleable automatically. It deliberately places received returns into QC HOLD. Disposition to Saleable / Repack / Rework / Damage / Expired / Dispose, accounting reversals and claims are later checkpoints.

## Verification
- Full cumulative test suite: **145/145 passed**.
- ZIP integrity verified after packaging.

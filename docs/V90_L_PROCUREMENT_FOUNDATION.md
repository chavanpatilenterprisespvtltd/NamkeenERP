# V90.l Release Notes

## Scope
Procurement foundation: purchase requisition, supplier quotation/rate capture, purchase order with maker/checker approval, and GRN preparation.

## Controls
- Entity/location scoped procurement permissions.
- Supplier and product references must be active and inside entity scope.
- PO can reference an eligible requisition/quote.
- PO approval is separate from creation; self-approval is blocked.
- GRN preparation can only start from an approved PO and authorized warehouse.
- Planned receipt cannot exceed ordered quantity.
- Lot capture is enabled by default in GRN preparation.

## Compatibility
Cumulative from V90.k. Earlier checkpoints remain recoverable.

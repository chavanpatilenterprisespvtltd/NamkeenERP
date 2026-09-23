# V90.aj Release Notes

Return Accounting / Credit Note & Incentive Reversal.

## Implemented
- Credit note can be posted only after the return is fully `DISPOSITIONED`.
- Credit note lines are linked back to the original invoice lines through the dispatch/return trace.
- Returned quantity is checked against the original invoiced quantity.
- Taxable value, GST and grand total are calculated proportionally from the original invoice line.
- Customer receivable impact is recorded explicitly as a `RETURN_CREDIT_NOTE` adjustment rather than mutating the original invoice.
- Salesperson incentive accruals linked to the original sales order/SKU are reversed proportionally to returned quantity.
- Incentive reversal is duplicate-safe and supports multiple accrual rows for the same order/SKU.
- Credit-note posting is idempotent for an already-accounted return.
- New permission: `returns.accounting` (manager and super_admin by default).
- Return accounting detail endpoint exposes credit note, customer adjustment and incentive-reversal history.
- Migration 109 added.

## Control boundary
This release creates an accounting-ready transaction layer. It does not silently change the original invoice, and it does not hard-code a third-party accounting package. Posting to Tally or another accounting system remains an adapter/integration step.

## Verification
Full cumulative test suite: 150 passed.

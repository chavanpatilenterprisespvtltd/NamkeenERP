# V90.q Release Notes

- Added material reservation persistence and approval workflow.
- Added reservation stock-availability guard for released/available RM lots.
- Added controlled reservation release.
- Added production order header and material requirement snapshot tables.
- Added production order draft -> pending approval -> approved workflow.
- Added scaling of V90.p material requirements to the production order quantity.
- Added entity/location authorization on q workflows.
- Added migration 090 with checksum manifest update.
- Updated release manifest to v90.q / schema 90.
- Updated cumulative test suite to 93/93 passing and made prior-stage assertions forward-compatible with later maintenance releases.

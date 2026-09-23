# V90.bp — Packing / FG UI + Sales UI

## Scope
- Packing and finished-goods operational UI with packing-run, packed-lot and packing-QC views.
- Sales/customer order UI with sales-order queue, status/credit/pricing/stock visibility and customer directory.
- Entity/location scope enforcement on UI APIs.
- Role-aware permissions for packing/sales UI and user screen preferences.
- Web routes: `/ui/packing`, `/ui/sales` and supporting `/v90bp/*` APIs.
- Migration 141 registers the new transaction screens.

## Compatibility
Built cumulatively from V90.bo. Existing APIs, migrations and tests are preserved.

## Verification
- Cumulative tests: 256 passed, 18 pre-existing warnings, 0 failed.
- Migration range: 61–141 contiguous.
- Migration checksums validated.
- CI repository gate and artifact checksum verification required before release.
- Python compilation and ZIP integrity verified.

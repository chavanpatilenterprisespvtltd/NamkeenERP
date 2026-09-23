# V90.j — Product / SKU / Pack Size / UOM Workflows

## Baseline
Cumulative from V90.i.

## Added
- Structured workflows for PRODUCT, VARIANT, PACK_SIZE, SKU, and UOM_CONVERSION.
- Parent-reference validation for variants and SKUs.
- Active SKU barcode uniqueness protection within organization/entity scope.
- Positive pack-size quantity and UOM validation.
- Positive UOM conversion factor and distinct source/target UOM validation.
- SKU configuration endpoint returning its product/variant/pack-size references.
- Product hierarchy lookup endpoint.

## Controls
- Authentication and masters.edit/masters.view permissions remain mandatory.
- Entity scope is enforced.
- Changes continue through the existing maker/checker approval workflow; V90.j does not bypass approval.
- Product count and pack-size count are not hard-coded limits.

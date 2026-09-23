# V90.z — Sales Order Foundation

Cumulative from V90.y.

## Added
- Customer/SKU/entity/location/warehouse-scoped sales order creation.
- Sales order lines with quantity, unit price, discount and configurable GST rate.
- Tax calculation: subtotal, discount, taxable value, GST and grand total.
- Draft → Submitted → Approved workflow with separate sales.approve permission.
- Hold workflow with reason and scope enforcement.
- Order detail endpoint.
- Duplicate order and duplicate SKU line protections.
- Migration 099 and release metadata target 99.

## Verification
- Full cumulative test suite: 122 passed, 0 failed.
- ZIP archive integrity verified.

## Next
V90.aa continues the cumulative ERP build. V90.z is not final.

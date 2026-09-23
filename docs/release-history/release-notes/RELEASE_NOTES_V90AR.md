# V90.ar — Production Variance Analysis

## Implemented
- Batch-level yield variance versus recipe expected-loss policy
- Wastage variance
- BOM/raw-material consumption variance
- Packaging-material consumption variance
- Component-wise variance quantities, rates and costs
- Total material/packaging variance cost
- Persistent batch variance report
- Entity/location scoped costing access
- Variance summary endpoint
- PostgreSQL migration 117

## Verification
- Full cumulative pytest suite: 176 passed, 0 failed
- Migration sequence validated: 61–117 contiguous
- Migration checksums validated
- Python compilation passed
- ZIP integrity verified

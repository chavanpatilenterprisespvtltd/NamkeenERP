# V90.em — Preventive Maintenance ROI + Reliability Cost Optimization

Adds auditable preventive-maintenance ROI and reliability-cost optimization snapshots. Compares preventive and breakdown maintenance costs against a configurable baseline, calculates avoided breakdown cost, net reliability benefit, preventive-maintenance ROI, breakdown-hour reduction, OEE improvement and an optimization score. Includes dashboard, comparison API, period close, RBAC and web UI. Schema target 214.

Verification: focused maintenance regression 16 passed; full pytest 399 passed, 27 warnings, 0 failures; Python compilation passed; CI repository gate passed; migration continuity through 214 passed; checksum verification passed for 852 files; ZIP integrity passed. PostgreSQL migration smoke testing was not run because no live DATABASE_URL/PostgreSQL instance was available.

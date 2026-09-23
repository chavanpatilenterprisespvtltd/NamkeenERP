# V90.cl — Advanced Accounting Completion

Adds configurable chart of accounts, balanced journal vouchers, general-ledger query, balanced opening balances, and controlled financial-period close/reopen. Preserves multi-company/entity scoping and RBAC.

Schema target: 163
Migration: 163_v90cl_accounting_completion.sql
Focused tests: 2/2 passed
Python compilation: passed
CI repository gate: passed
Database migration smoke: not run; DATABASE_URL unavailable in build environment.
Known recursive legacy release-integrity test remains excluded because it can hang.

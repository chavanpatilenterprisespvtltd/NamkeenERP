# V90.e — Persistent Identity, Roles & Permission Enforcement

Adds persistent ERP users, roles, permissions, role grants, authenticated permission introspection, and protected user administration while preserving the V90 authentication API and legacy demo-login compatibility.

This stage does not advance the V90.c migration manifest; identity tables are bootstrapped idempotently at runtime and can be promoted into the production migration stream at the next schema-governance gate.

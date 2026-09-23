# Namkeen ERP v90.d — Authentication & Security Foundation

## Goal
Add a dependency-light authentication foundation on top of the v90.c runtime/migration baseline without changing the historical release contract.

## Added
- PBKDF2-SHA256 password hashing and verification.
- Signed bearer access tokens with expiry.
- `/auth/login` and `/auth/me` endpoints.
- Reusable role-check dependency helper for later endpoint protection.
- `/build` endpoint identifying maintenance stage `v90.d` while the base release contract remains `v90`.
- Demo credentials are environment-configurable and intended for local/dev use only.

## Production hardening still required
A production deployment should use the persistent ERP user/role store, strong secret management, session revocation/refresh strategy, rate limiting/brute-force protection, and any required MFA/SSO controls before go-live.

## Compatibility
Cumulative from v90.c. Existing v80-v90 release components and migrations are retained.

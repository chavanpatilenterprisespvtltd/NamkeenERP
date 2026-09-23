# V90.bf — User/Device/Session Security Hardening + API Security Controls

## Implemented
- Persistent security session registry for newly issued login tokens
- Logout and per-session revocation
- Device registration, listing and revocation
- Device revocation cascades to its active sessions
- Login-attempt persistence and configurable failure throttling
- API security headers and request correlation ID
- `Cache-Control: no-store` on authentication/security endpoints
- Backward-compatible validation for legacy stateless tokens not present in the persisted session registry
- Security permissions: `security.view`, `security.manage`
- PostgreSQL migration 131

## Verification
- 218/218 cumulative tests passed
- 18 pre-existing warnings
- 0 failures
- Migration sequence 61–131 contiguous
- Migration checksums verified
- Python compilation passed
- Clean release archive excludes transient SQLite/bytecode artifacts

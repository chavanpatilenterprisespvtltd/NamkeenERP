# Namkeen ERP v80 — PostgreSQL Master Data UI Integration

v80 connects the persistent v77 master-data service to a working Web admin surface and an Android integration contract.

Features: master list/search, change requests, approval queue, history, optimistic-lock/effective-date controls, bulk-preview endpoint, PostgreSQL read indexes.

Demo API defaults to SQLite unless `DATABASE_URL` is set. Production deployments should use PostgreSQL and the existing auth/reverse-proxy/security stack.

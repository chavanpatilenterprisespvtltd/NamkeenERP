#!/usr/bin/env bash
set -euo pipefail
cat <<'MSG'
ROLLBACK POLICY
1. Stop application traffic.
2. Preserve logs/deployment evidence.
3. Restore the last VERIFIED PostgreSQL backup.
4. Redeploy the previous immutable artifact set.
5. Run health/readiness + post-deploy smoke tests.
6. Record the rollback release and reason.
No destructive migration-down is performed by this script.
MSG

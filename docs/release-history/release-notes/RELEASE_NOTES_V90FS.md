# V90.fs — Governance Remediation Execution & UAT Evidence

Schema target: **245**

This release turns V90.fr governance coverage gaps into controlled remediation work and adds evidence-backed UAT/readiness controls.

## Included
- Remediation records linked to governance coverage gaps.
- Controlled lifecycle: REQUESTED, IN_PROGRESS, COMPLETED, BLOCKED, CANCELLED.
- Owner, due date, plan, completion evidence and supplemental evidence.
- UAT cases tied to the governed critical action, with PASS/FAIL/BLOCKED/WAIVED outcomes.
- PASS/WAIVED UAT requires evidence.
- Certification-readiness API and period-close gate.
- Force close remains explicit and auditable; no operational transaction is mutated automatically.
- Web UI for remediation/UAT/readiness.

## Safety
Operational transactions are not auto-executed by remediation. Existing V90.fn security scope and V90.fo/fp/fq/fr governance controls remain the source of authorization and certification.

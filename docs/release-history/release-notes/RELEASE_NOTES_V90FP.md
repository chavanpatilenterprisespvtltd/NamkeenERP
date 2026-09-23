# V90.fp — ERP-wide Transaction Governance Integration

Schema target: 242

V90.fp integrates the V90.fo governed-action/audit framework with the core transactional route surface. Twelve core transactional domains receive policy coverage: procurement, receiving/QC, inventory, production, process QC, batch/packing, finished-goods dispatch, sales, returns, return disposition, accounting, and intercompany.

Default integration policies are AUDIT_ONLY to preserve backward compatibility. Administrators can create more specific REQUIRE_APPROVAL policies. When a mandatory policy matches a transaction route, the request must provide X-Governed-Action-Id referencing an APPROVED, evidence-complete governed action with matching module/action code and security scope. A successful governed transaction marks the action EXECUTED. Blocked and successful integration events are recorded.

No transaction is automatically mutated merely by being covered by the default policies, and no causal/financial result is inferred by this release.

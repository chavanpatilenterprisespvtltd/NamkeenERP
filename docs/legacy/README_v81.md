# Namkeen ERP v81 — Structured Master Data Screens

v81 upgrades the v80 generic master JSON editor to structured administration forms for all 15 core master types.

## Added
- Master-type-specific field definitions
- Required-field validation
- Basic numeric validation
- Structured create/update forms
- Existing v77 approval/audit path reused
- Effective-date UI enforcement for effective-dated masters
- Optimistic-lock base-version support in edit forms
- History viewing retained
- No direct writes from the UI

## Validation
Run the inherited suite plus `tests/test_v81_structured_ui.py`.

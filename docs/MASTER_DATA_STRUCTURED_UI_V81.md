# v81 — Structured Master Data UI

v81 replaces the generic JSON editor with master-type-specific forms for Product, Variant, Pack Size, SKU, UOM Conversion, Customer, Supplier, Warehouse, Bin, Tax Profile, HSN, Price List, Territory, Role and Accounting Ledger Mapping.

The UI submits the same audited master-change-request path as v77/v80. It never writes authoritative masters directly. Effective-dated types require an effective start date, update requests carry a base version, and approval remains separate from request creation.

The schema registry is intentionally extensible. Customer-specific statutory fields may be added as extra payload fields without changing the approval architecture.

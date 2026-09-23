# Android v75 Master Data Screens

Screens: Master Dashboard, Product/SKU, Pack Size/UOM, Customer, Supplier, Warehouse/Bin, Tax/HSN, Price/Territory, Roles, Accounting Mapping, Change Request, Approval Queue, Audit History.

Offline behavior: CREATE/UPDATE/DEACTIVATE requests are queued locally with `client_event_id`. The server remains authoritative; approval-required changes are never silently committed offline.

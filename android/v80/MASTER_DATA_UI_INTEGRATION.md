# v80 Android/Web Master Data UI Integration Contract

Screens: Master List, Master Editor, Approval Queue, Version History, Bulk Import Preview.

All mutations call `/v80/master-data/changes` and therefore remain subject to approval, optimistic locking, effective-date validation and audit rules from v77/v78/v79.

The client never directly writes master tables. Offline requests retain `client_event_id`; server remains authoritative.

# Android v86 — Validation-aware Approval UI

Approval row fields:
- request_id
- master_type
- action
- validation_status
- validation_version
- validated_at
- warning_count
- requested_by

Actions:
- View validation errors/warnings
- Approve only when server returns success
- Reject with mandatory reason

The device never performs the authoritative master write.

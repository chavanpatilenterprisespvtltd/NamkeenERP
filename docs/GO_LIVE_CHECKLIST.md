# v72 Go-Live Checklist

## Mandatory gates
- [ ] Production PostgreSQL created and hardened
- [ ] Database backup completed before migration
- [ ] Backup restore has been verified
- [ ] Migrations 001–061 checksum-verified
- [ ] TLS/secret/KMS references validated
- [ ] Admin bootstrap completed and temporary credentials rotated
- [ ] Object storage encryption and private access validated
- [ ] Notification provider configured
- [ ] Tally/IRP/EWB credentials configured and tested in target environment
- [ ] Android APKs signed and versioned
- [ ] Full UAT matrix passed
- [ ] Accounts sign-off
- [ ] Factory/QC sign-off
- [ ] Management sign-off
- [ ] Support/backup owner assigned
- [ ] Rollback plan tested or restore procedure verified

## Blockers
Any failed security gate, checksum mismatch, unresolved critical UAT defect, failed restore verification, broken accounting/tax integration, or unauthorized data-scope issue blocks go-live.

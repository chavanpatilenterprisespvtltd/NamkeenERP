# V90.m — GRN Receiving + Incoming QC + Raw-Material Lot Inventory

Builds on V90.l. The flow is PO → GRN receipt → incoming QC disposition → authorized release → lot inventory + stock receipt ledger.

Controls include approved-PO-only receiving, entity/location/warehouse scope, receipt quantity <= PO quantity, supplier consistency, QC disposition before release, lot-level traceability, and posted receipt ledger records.

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable
from uuid import UUID, uuid4

from sqlalchemy import JSON, DateTime, Integer, String, Text, and_, select, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.v77.persistent_master import (
    Base,
    ChangeRequest,
    MasterChangeRequestORM,
    MasterRecordORM,
    PersistentMasterAdmin,
    MasterAuditSnapshotORM,
)
from app.v84.rules import validate_cross_field


class MasterValidationRunORM(Base):
    __tablename__ = "master_validation_run"
    validation_id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(index=True)
    request_id: Mapped[UUID | None] = mapped_column(index=True, nullable=True)
    master_id: Mapped[UUID | None] = mapped_column(index=True, nullable=True)
    master_type: Mapped[str] = mapped_column(String(64), index=True)
    action: Mapped[str] = mapped_column(String(32))
    stage: Mapped[str] = mapped_column(String(32), default="REQUEST")
    status: Mapped[str] = mapped_column(String(16))
    errors: Mapped[list[str]] = mapped_column(JSON, default=list)
    warnings: Mapped[list[str]] = mapped_column(JSON, default=list)
    payload_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    validator_version: Mapped[str] = mapped_column(String(32), default="v86")
    validated_by: Mapped[UUID] = mapped_column(index=True)
    validated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    outcome: Mapped[str | None] = mapped_column(String(32), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)


class ValidationResult:
    def __init__(self, status: str, errors: list[str] | tuple[str, ...], warnings: list[str] | tuple[str, ...], validation_version: str = "v86"):
        self.status = status
        self.errors = tuple(errors)
        self.warnings = tuple(warnings)
        self.validation_version = validation_version

    @property
    def can_submit(self) -> bool:
        return not self.errors


VALIDATION_VERSION = "v86"


def build_warnings(master_type: str, payload: dict[str, Any]) -> list[str]:
    warnings: list[str] = []
    if master_type in {"CUSTOMER", "SUPPLIER"} and not payload.get("gstin"):
        warnings.append("gstin: not supplied; verify applicability before activation")
    if master_type == "SKU" and not payload.get("barcode"):
        warnings.append("barcode: not supplied; assign one before barcode-driven operations")
    if master_type == "PRICE_LIST" and payload.get("maximum_discount_pct") in (None, ""):
        warnings.append("maximum_discount_pct: not configured; confirm bargaining policy")
    return warnings


def validate_payload(master_type: str, action: str, payload: dict[str, Any], existing: dict[str, Any] | None = None) -> ValidationResult:
    errors = validate_cross_field(master_type, payload, existing=existing)
    if action == "DEACTIVATE" and not str(payload.get("reason") or "").strip():
        errors.append("reason: required for deactivation")
    effective = dict(existing or {})
    effective.update(payload)
    warnings = build_warnings(master_type, effective)
    status = "BLOCKED" if errors else ("WARNING" if warnings else "PASS")
    return ValidationResult(status, errors, warnings, VALIDATION_VERSION)


class ProductionMasterAdminV86:
    """Persistent master workflow with validation stored on the request itself.

    The key invariant is that request submission and the first validation stamp are
    written in one database transaction. Approval re-validates while holding a row
    lock on the request and the target master, then writes the final validation stamp
    and authoritative master mutation in the same transaction.
    """

    def __init__(self, session_factory):
        self.session_factory = session_factory
        self.persistence = PersistentMasterAdmin(session_factory)

    @staticmethod
    def _effective_payload(req: MasterChangeRequestORM, existing: dict[str, Any] | None = None) -> dict[str, Any]:
        merged = dict(existing or {})
        merged.update(req.payload)
        return merged

    def _record_validation_row(self, session, *, organization_id, request_id, master_id, master_type, action,
                               result: ValidationResult, payload: dict[str, Any], validator_id, stage, outcome=None, note=None):
        row = MasterValidationRunORM(
            organization_id=organization_id, request_id=request_id, master_id=master_id,
            master_type=master_type, action=action, stage=stage, status=result.status,
            errors=list(result.errors), warnings=list(result.warnings), payload_snapshot=dict(payload),
            validator_version=result.validation_version, validated_by=validator_id,
            outcome=outcome, note=note,
        )
        session.add(row)
        return row

    @staticmethod
    def _stamp_request(req: MasterChangeRequestORM, row: MasterValidationRunORM):
        req.validation_id = row.validation_id
        req.validation_status = row.status
        req.validation_version = row.validator_version
        req.validated_at = row.validated_at

    def submit(self, req: ChangeRequest) -> tuple[UUID, ValidationResult]:
        if not req.payload:
            raise ValueError("Payload is required")
        with self.session_factory() as s:
            existing = None
            if req.action in {"UPDATE", "DEACTIVATE"}:
                if not req.master_id:
                    raise ValueError("master_id is required")
                row = s.scalar(select(MasterRecordORM).where(and_(MasterRecordORM.master_id == req.master_id,
                                                                  MasterRecordORM.organization_id == req.organization_id)).with_for_update())
                if not row:
                    raise ValueError("Master not found in organization scope")
                existing = dict(row.data)
            result = validate_payload(req.master_type, req.action, req.payload, existing)
            if not result.can_submit:
                audit = self._record_validation_row(s, organization_id=req.organization_id, request_id=None, master_id=req.master_id,
                    master_type=req.master_type, action=req.action, result=result,
                    payload=self._effective_change_payload(req.payload, existing), validator_id=req.requested_by, stage="REQUEST_BLOCKED")
                s.commit()
                raise ValueError("Master validation failed: " + " | ".join(result.errors))

            if req.client_event_id:
                existing_req = s.scalar(select(MasterChangeRequestORM).where(MasterChangeRequestORM.client_event_id == req.client_event_id).with_for_update())
                if existing_req:
                    return existing_req.request_id, result_from_request(existing_req)

            obj = MasterChangeRequestORM(
                organization_id=req.organization_id, master_type=req.master_type, action=req.action,
                requested_by=req.requested_by, master_id=req.master_id, entity_id=req.entity_id,
                payload=req.payload, effective_from=req.effective_from, effective_to=req.effective_to,
                base_version_no=req.base_version_no, client_event_id=req.client_event_id,
            )
            s.add(obj)
            s.flush()
            audit = self._record_validation_row(s, organization_id=req.organization_id, request_id=obj.request_id, master_id=req.master_id,
                master_type=req.master_type, action=req.action, result=result,
                payload=self._effective_change_payload(req.payload, existing), validator_id=req.requested_by, stage="REQUEST")
            s.flush()
            self._stamp_request(obj, audit)
            s.commit()
            return obj.request_id, result

    @staticmethod
    def _effective_change_payload(payload: dict[str, Any], existing: dict[str, Any] | None):
        merged = dict(existing or {})
        merged.update(payload)
        return merged

    def approve(self, organization_id: UUID, request_id: UUID, approver_id: UUID,
                reason: str = "", allowed_entity_ids: Iterable[UUID] | None = None) -> tuple[UUID, ValidationResult]:
        with self.session_factory() as s:
            req = s.scalar(select(MasterChangeRequestORM).where(MasterChangeRequestORM.request_id == request_id,
                                                               MasterChangeRequestORM.organization_id == organization_id).with_for_update())
            if not req:
                raise ValueError("Request not found in organization scope")
            if allowed_entity_ids is not None and req.entity_id is not None and req.entity_id not in set(allowed_entity_ids):
                raise ValueError("Entity access denied")
            if req.status != "PENDING_APPROVAL":
                raise ValueError("Only pending requests can be approved")
            if approver_id == req.requested_by:
                raise ValueError("Self-approval is not allowed")

            existing_row = None
            if req.master_id:
                existing_row = s.scalar(select(MasterRecordORM).where(and_(MasterRecordORM.master_id == req.master_id,
                                                                          MasterRecordORM.organization_id == organization_id)).with_for_update())
                if not existing_row:
                    raise ValueError("Master not found in organization scope")
            existing = dict(existing_row.data) if existing_row else None
            result = validate_payload(req.master_type, req.action, dict(req.payload), existing)
            if not result.can_submit:
                audit = self._record_validation_row(s, organization_id=organization_id, request_id=req.request_id,
                    master_id=req.master_id, master_type=req.master_type, action=req.action, result=result,
                    payload=self._effective_change_payload(dict(req.payload), existing), validator_id=approver_id,
                    stage="APPROVAL_BLOCKED", outcome="REJECTED_BY_VALIDATION")
                s.flush(); self._stamp_request(req, audit)
                req.status = "PENDING_APPROVAL"  # unchanged, explicit for clarity
                s.commit()
                raise ValueError("Approval blocked by master validation: " + " | ".join(result.errors))

            # Re-run all persistent workflow constraints while the target rows are locked.
            if req.action == "UPDATE":
                merged = dict(existing_row.data)
                merged.update(req.payload)
                candidate_key = self.persistence.make_key(req.master_type, existing_row.entity_id, merged)
                self.persistence._check_duplicate(s, existing_row, candidate_key)
                temp = MasterRecordORM(master_id=existing_row.master_id, organization_id=existing_row.organization_id,
                    master_type=existing_row.master_type, entity_id=existing_row.entity_id, data=merged,
                    normalized_key=candidate_key, version_no=existing_row.version_no, active=existing_row.active,
                    effective_from=req.effective_from or existing_row.effective_from, effective_to=req.effective_to or existing_row.effective_to)
                self.persistence._check_overlap(s, temp, existing_row.master_id)
            elif req.action == "CREATE":
                candidate = MasterRecordORM(organization_id=organization_id, master_type=req.master_type,
                    entity_id=req.entity_id, data=dict(req.payload),
                    normalized_key=self.persistence.make_key(req.master_type, req.entity_id, dict(req.payload)),
                    effective_from=req.effective_from, effective_to=req.effective_to, version_no=1, active=True)
                self.persistence._check_duplicate(s, candidate)
                self.persistence._check_overlap(s, candidate, None)

            if req.action == "UPDATE":
                assert existing_row is not None
                if req.base_version_no is not None and existing_row.version_no != req.base_version_no:
                    raise ValueError("Optimistic lock conflict: master version changed")
                s.add(MasterAuditSnapshotORM(
                    organization_id=existing_row.organization_id, master_id=existing_row.master_id,
                    master_type=existing_row.master_type, version_no=existing_row.version_no,
                    data=dict(existing_row.data), active=existing_row.active,
                    effective_from=existing_row.effective_from, effective_to=existing_row.effective_to,
                    changed_by=approver_id))
                existing_row.data = merged
                existing_row.normalized_key = candidate_key
                existing_row.effective_from = req.effective_from or existing_row.effective_from
                existing_row.effective_to = req.effective_to or existing_row.effective_to
                existing_row.version_no += 1
                existing_row.updated_at = datetime.now(timezone.utc)
                master_id = existing_row.master_id
            elif req.action == "CREATE":
                existing_row = candidate
                s.add(existing_row); s.flush(); master_id = existing_row.master_id
            else:
                assert existing_row is not None
                if req.base_version_no is not None and existing_row.version_no != req.base_version_no:
                    raise ValueError("Optimistic lock conflict: master version changed")
                s.add(MasterAuditSnapshotORM(
                    organization_id=existing_row.organization_id, master_id=existing_row.master_id,
                    master_type=existing_row.master_type, version_no=existing_row.version_no,
                    data=dict(existing_row.data), active=existing_row.active,
                    effective_from=existing_row.effective_from, effective_to=existing_row.effective_to,
                    changed_by=approver_id))
                existing_row.active = False
                existing_row.version_no += 1
                existing_row.updated_at = datetime.now(timezone.utc)
                master_id = existing_row.master_id

            s.flush()
            # Final validation stamp is part of the SAME transaction as the master write.
            audit = self._record_validation_row(s, organization_id=organization_id, request_id=req.request_id,
                master_id=master_id, master_type=req.master_type, action=req.action, result=result,
                payload=self._effective_change_payload(dict(req.payload), existing), validator_id=approver_id,
                stage="APPROVAL", outcome="APPROVED", note="Approved after locked re-validation")
            s.flush(); self._stamp_request(req, audit)
            req.status = "APPROVED"; req.decided_at = datetime.now(timezone.utc)
            s.commit()
            return master_id, result

    def reject(self, organization_id: UUID, request_id: UUID, approver_id: UUID, reason: str, allowed_entity_ids=None):
        if not reason.strip():
            raise ValueError("Rejection reason is required")
        with self.session_factory() as s:
            req = s.scalar(select(MasterChangeRequestORM).where(MasterChangeRequestORM.request_id == request_id,
                                                               MasterChangeRequestORM.organization_id == organization_id).with_for_update())
            if not req or req.status != "PENDING_APPROVAL":
                raise ValueError("Only pending requests can be rejected")
            if approver_id == req.requested_by:
                raise ValueError("Self-approval is not allowed")
            if allowed_entity_ids is not None and req.entity_id is not None and req.entity_id not in set(allowed_entity_ids):
                raise ValueError("Entity access denied")
            req.status = "REJECTED"; req.rejection_reason = reason; req.decided_at = datetime.now(timezone.utc)
            s.commit()


def result_from_request(req: MasterChangeRequestORM) -> ValidationResult:
    return ValidationResult(req.validation_status or "WARNING", [], [], req.validation_version or VALIDATION_VERSION)

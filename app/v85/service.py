from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import JSON, DateTime, Integer, String, Text, and_, select
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.v77.persistent_master import (
    ChangeRequest,
    MasterChangeRequestORM,
    MasterRecordORM,
    PersistentMasterAdmin,
)
from app.v84.rules import validate_cross_field


class Base(DeclarativeBase):
    pass


class MasterValidationRunORM(Base):
    __tablename__ = "master_validation_run"
    validation_id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(index=True)
    request_id: Mapped[UUID | None] = mapped_column(index=True, nullable=True)
    master_id: Mapped[UUID | None] = mapped_column(index=True, nullable=True)
    master_type: Mapped[str] = mapped_column(String(64), index=True)
    action: Mapped[str] = mapped_column(String(32))
    stage: Mapped[str] = mapped_column(String(32), default="REQUEST")
    status: Mapped[str] = mapped_column(String(16))  # PASS / WARNING / BLOCKED
    errors: Mapped[list[str]] = mapped_column(JSON, default=list)
    warnings: Mapped[list[str]] = mapped_column(JSON, default=list)
    payload_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    validator_version: Mapped[str] = mapped_column(String(32), default="v84")
    validated_by: Mapped[UUID] = mapped_column(index=True)
    validated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    outcome: Mapped[str | None] = mapped_column(String(32), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)


@dataclass(frozen=True)
class ValidationResult:
    status: str
    errors: tuple[str, ...]
    warnings: tuple[str, ...]

    @property
    def can_submit(self) -> bool:
        return not self.errors


def build_warnings(master_type: str, payload: dict[str, Any]) -> list[str]:
    """Warnings are advisory and never block submission."""
    warnings: list[str] = []
    if master_type in {"CUSTOMER", "SUPPLIER"} and not payload.get("gstin"):
        warnings.append("gstin: not supplied; verify whether GSTIN is applicable before activation")
    if master_type == "SKU" and not payload.get("barcode"):
        warnings.append("barcode: not supplied; assign a barcode before barcode-driven warehouse operations")
    if master_type == "PRICE_LIST" and not payload.get("maximum_discount_pct"):
        warnings.append("maximum_discount_pct: not configured; confirm discount policy before bargaining")
    if master_type in {"TAX_PROFILE", "HSN", "PRICE_LIST", "UOM_CONVERSION", "ACCOUNTING_LEDGER_MAPPING"} and not payload.get("effective_to"):
        warnings.append("effective_to: open-ended validity; confirm this is intentional")
    return warnings


class ValidatedMasterAdmin:
    """v85 gate around v77 persistence.

    Request path blocks invalid changes before they enter approval. Approval path
    re-runs validation against the current persisted record to catch drift.
    """

    def __init__(self, session_factory):
        self.session_factory = session_factory
        self.persistence = PersistentMasterAdmin(session_factory)

    @staticmethod
    def _effective_payload(req: ChangeRequest, existing: dict[str, Any] | None = None) -> dict[str, Any]:
        merged = dict(existing or {})
        merged.update(req.payload)
        return merged

    def validate(
        self,
        master_type: str,
        action: str,
        payload: dict[str, Any],
        *,
        existing: dict[str, Any] | None = None,
    ) -> ValidationResult:
        errors = validate_cross_field(master_type, payload, existing=existing)
        if action == "DEACTIVATE" and not (payload.get("reason") or "").strip():
            errors.append("reason: required for deactivation")
        warnings = build_warnings(master_type, self._effective_payload(
            ChangeRequest(UUID(int=0), master_type, action, UUID(int=0), payload), existing
        ))
        return ValidationResult(
            status="BLOCKED" if errors else ("WARNING" if warnings else "PASS"),
            errors=tuple(errors),
            warnings=tuple(warnings),
        )

    def _record_validation(self, *, organization_id: UUID, request_id: UUID | None,
                           master_id: UUID | None, master_type: str, action: str,
                           result: ValidationResult, payload: dict[str, Any], validator_id: UUID,
                           stage: str, outcome: str | None = None, note: str | None = None) -> UUID:
        with self.session_factory() as s:
            row = MasterValidationRunORM(
                organization_id=organization_id, request_id=request_id, master_id=master_id,
                master_type=master_type, action=action, stage=stage, status=result.status,
                errors=list(result.errors), warnings=list(result.warnings), payload_snapshot=dict(payload),
                validated_by=validator_id, outcome=outcome, note=note,
            )
            s.add(row)
            s.commit()
            return row.validation_id

    def request(self, req: ChangeRequest) -> tuple[UUID, ValidationResult]:
        existing = None
        if req.action in {"UPDATE", "DEACTIVATE"} and req.master_id:
            with self.session_factory() as s:
                row = s.scalar(select(MasterRecordORM).where(and_(MasterRecordORM.master_id == req.master_id,
                                                                  MasterRecordORM.organization_id == req.organization_id)))
                if not row:
                    raise ValueError("Master not found in organization scope")
                existing = dict(row.data)
        result = self.validate(req.master_type, req.action, req.payload, existing=existing)
        if not result.can_submit:
            self._record_validation(organization_id=req.organization_id, request_id=None, master_id=req.master_id,
                                     master_type=req.master_type, action=req.action, result=result,
                                     payload=self._effective_payload(req, existing), validator_id=req.requested_by, stage="REQUEST_BLOCKED")
            raise ValueError("Master validation failed: " + " | ".join(result.errors))
        request_id = self.persistence.request(req)
        self._record_validation(organization_id=req.organization_id, request_id=request_id, master_id=req.master_id,
                                 master_type=req.master_type, action=req.action, result=result,
                                 payload=self._effective_payload(req, existing), validator_id=req.requested_by, stage="REQUEST")
        return request_id, result

    def approve(self, organization_id: UUID, request_id: UUID, approver_id: UUID,
                reason: str = "", allowed_entity_ids=None) -> tuple[UUID, ValidationResult]:
        with self.session_factory() as s:
            req = s.scalar(select(MasterChangeRequestORM).where(MasterChangeRequestORM.request_id == request_id))
            if not req or req.organization_id != organization_id:
                raise ValueError("Request not found in organization scope")
            existing = None
            if req.master_id:
                row = s.scalar(select(MasterRecordORM).where(and_(MasterRecordORM.master_id == req.master_id,
                                                                  MasterRecordORM.organization_id == organization_id)))
                if row:
                    existing = dict(row.data)
            result = self.validate(req.master_type, req.action, dict(req.payload), existing=existing)
        if not result.can_submit:
            self._record_validation(organization_id=organization_id, request_id=request_id, master_id=req.master_id,
                                     master_type=req.master_type, action=req.action, result=result,
                                     payload=self._effective_payload(ChangeRequest(organization_id, req.master_type, req.action, req.requested_by, dict(req.payload), req.master_id), existing),
                                     validator_id=approver_id, stage="APPROVAL_BLOCKED", outcome="REJECTED_BY_VALIDATION")
            raise ValueError("Approval blocked by master validation: " + " | ".join(result.errors))
        master_id = self.persistence.approve(organization_id, request_id, approver_id, reason, allowed_entity_ids)
        self._record_validation(organization_id=organization_id, request_id=request_id, master_id=master_id,
                                 master_type=req.master_type, action=req.action, result=result,
                                 payload=self._effective_payload(ChangeRequest(organization_id, req.master_type, req.action, req.requested_by, dict(req.payload), req.master_id), existing),
                                 validator_id=approver_id, stage="APPROVAL", outcome="APPROVED")
        return master_id, result

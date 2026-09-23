from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable
from uuid import UUID, uuid4

from sqlalchemy import JSON, Boolean, DateTime, Integer, String, Text, create_engine, select, func, and_
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, Session

VALID_TYPES = {
    "PRODUCT", "VARIANT", "PACK_SIZE", "SKU", "UOM_CONVERSION", "CUSTOMER", "SUPPLIER", "WAREHOUSE", "BIN",
    "TAX_PROFILE", "HSN", "PRICE_LIST", "TERRITORY", "ROLE", "ACCOUNTING_LEDGER_MAPPING"
}
VALID_ACTIONS = {"CREATE", "UPDATE", "DEACTIVATE"}
EFFECTIVE_TYPES = {"TAX_PROFILE", "HSN", "PRICE_LIST", "UOM_CONVERSION", "ACCOUNTING_LEDGER_MAPPING"}

class Base(DeclarativeBase):
    pass

class MasterRecordORM(Base):
    __tablename__ = "master_record"
    master_id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(index=True)
    master_type: Mapped[str] = mapped_column(String(64), index=True)
    entity_id: Mapped[UUID | None] = mapped_column(index=True, nullable=True)
    data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    normalized_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    version_no: Mapped[int] = mapped_column(Integer, default=1)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    effective_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    effective_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

class MasterChangeRequestORM(Base):
    __tablename__ = "master_change_request"
    request_id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(index=True)
    master_type: Mapped[str] = mapped_column(String(64), index=True)
    action: Mapped[str] = mapped_column(String(32))
    requested_by: Mapped[UUID] = mapped_column(index=True)
    master_id: Mapped[UUID | None] = mapped_column(nullable=True, index=True)
    entity_id: Mapped[UUID | None] = mapped_column(nullable=True, index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    effective_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    effective_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    base_version_no: Mapped[int | None] = mapped_column(Integer, nullable=True)
    client_event_id: Mapped[str | None] = mapped_column(String(128), nullable=True, unique=True)
    status: Mapped[str] = mapped_column(String(32), default="PENDING_APPROVAL", index=True)
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    validation_status: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    validation_id: Mapped[UUID | None] = mapped_column(nullable=True)
    validation_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    validated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

class MasterAuditSnapshotORM(Base):
    __tablename__ = "master_audit_snapshot"
    snapshot_id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(index=True)
    master_id: Mapped[UUID] = mapped_column(index=True)
    master_type: Mapped[str] = mapped_column(String(64))
    version_no: Mapped[int] = mapped_column(Integer)
    data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    active: Mapped[bool] = mapped_column(Boolean)
    effective_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    effective_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    changed_by: Mapped[UUID] = mapped_column(index=True)

@dataclass(frozen=True)
class ChangeRequest:
    organization_id: UUID
    master_type: str
    action: str
    requested_by: UUID
    payload: dict[str, Any]
    master_id: UUID | None = None
    entity_id: UUID | None = None
    effective_from: datetime | None = None
    effective_to: datetime | None = None
    base_version_no: int | None = None
    client_event_id: str | None = None

class PersistentMasterAdmin:
    def __init__(self, session_factory):
        self.session_factory = session_factory

    @staticmethod
    def make_key(master_type: str, entity_id: UUID | None, payload: dict[str, Any]) -> str:
        code = payload.get("code") or payload.get("sku") or payload.get("gstin") or payload.get("name")
        return f"{master_type}|{entity_id or ''}|{str(code).strip().lower() if code is not None else ''}"

    def request(self, req: ChangeRequest) -> UUID:
        if req.master_type not in VALID_TYPES: raise ValueError("Unsupported master type")
        if req.action not in VALID_ACTIONS: raise ValueError("Unsupported master action")
        if not req.payload: raise ValueError("Payload is required")
        if req.action == "DEACTIVATE" and not (req.payload.get("reason") or "").strip(): raise ValueError("Deactivation reason is required")
        if req.action in {"UPDATE", "DEACTIVATE"} and not req.master_id: raise ValueError("master_id is required")
        if req.master_type in EFFECTIVE_TYPES and req.effective_from is None: raise ValueError("effective_from is required for this master type")
        with self.session_factory() as s:
            if req.client_event_id:
                existing = s.scalar(select(MasterChangeRequestORM).where(MasterChangeRequestORM.client_event_id == req.client_event_id))
                if existing: return existing.request_id
            obj = MasterChangeRequestORM(organization_id=req.organization_id, master_type=req.master_type, action=req.action,
                requested_by=req.requested_by, master_id=req.master_id, entity_id=req.entity_id, payload=req.payload,
                effective_from=req.effective_from, effective_to=req.effective_to, base_version_no=req.base_version_no,
                client_event_id=req.client_event_id)
            s.add(obj); s.commit(); return obj.request_id

    def _ensure_scope(self, organization_id: UUID, entity_id: UUID | None, allowed_entity_ids: Iterable[UUID] | None):
        if allowed_entity_ids is not None and entity_id is not None and entity_id not in set(allowed_entity_ids):
            raise ValueError("Entity access denied")

    def approve(self, organization_id: UUID, request_id: UUID, approver_id: UUID, reason: str = "", allowed_entity_ids: Iterable[UUID] | None = None) -> UUID:
        with self.session_factory() as s:
            req = s.scalar(select(MasterChangeRequestORM).where(MasterChangeRequestORM.request_id == request_id).with_for_update())
            if not req or req.organization_id != organization_id: raise ValueError("Request not found in organization scope")
            self._ensure_scope(organization_id, req.entity_id, allowed_entity_ids)
            if req.status != "PENDING_APPROVAL": raise ValueError("Only pending requests can be approved")
            if approver_id == req.requested_by: raise ValueError("Self-approval is not allowed")
            if req.action == "DEACTIVATE" and not (req.payload.get("reason") or reason).strip(): raise ValueError("Deactivation reason is required")
            rec = None
            if req.action == "CREATE":
                rec = MasterRecordORM(organization_id=req.organization_id, master_type=req.master_type, entity_id=req.entity_id,
                    data=dict(req.payload), normalized_key=self.make_key(req.master_type, req.entity_id, req.payload),
                    effective_from=req.effective_from, effective_to=req.effective_to, version_no=1, active=True)
                self._check_duplicate(s, rec)
                self._check_overlap(s, rec, None)
                s.add(rec)
            else:
                rec = s.scalar(select(MasterRecordORM).where(and_(MasterRecordORM.master_id == req.master_id, MasterRecordORM.organization_id == organization_id)).with_for_update())
                if not rec: raise ValueError("Master not found in organization scope")
                if req.base_version_no is not None and rec.version_no != req.base_version_no: raise ValueError("Optimistic lock conflict: master version changed")
                s.add(MasterAuditSnapshotORM(organization_id=rec.organization_id, master_id=rec.master_id, master_type=rec.master_type,
                    version_no=rec.version_no, data=dict(rec.data), active=rec.active, effective_from=rec.effective_from, effective_to=rec.effective_to, changed_by=approver_id))
                if req.action == "UPDATE":
                    merged = dict(rec.data); merged.update(req.payload)
                    candidate_key = self.make_key(rec.master_type, rec.entity_id, merged)
                    self._check_duplicate(s, rec, candidate_key)
                    temp = MasterRecordORM(master_id=rec.master_id, organization_id=rec.organization_id, master_type=rec.master_type, entity_id=rec.entity_id,
                        data=merged, normalized_key=candidate_key, version_no=rec.version_no, active=rec.active,
                        effective_from=req.effective_from or rec.effective_from, effective_to=req.effective_to or rec.effective_to)
                    self._check_overlap(s, temp, rec.master_id)
                    rec.data=merged; rec.normalized_key=candidate_key; rec.effective_from=temp.effective_from; rec.effective_to=temp.effective_to; rec.version_no += 1; rec.updated_at=datetime.now(timezone.utc)
                else:
                    rec.active=False; rec.version_no += 1; rec.updated_at=datetime.now(timezone.utc)
            req.status="APPROVED"; req.decided_at=datetime.now(timezone.utc); s.commit(); return rec.master_id

    def reject(self, organization_id: UUID, request_id: UUID, approver_id: UUID, reason: str, allowed_entity_ids: Iterable[UUID] | None = None):
        if not reason.strip(): raise ValueError("Rejection reason is required")
        with self.session_factory() as s:
            req=s.scalar(select(MasterChangeRequestORM).where(MasterChangeRequestORM.request_id==request_id).with_for_update())
            if not req or req.organization_id!=organization_id: raise ValueError("Request not found in organization scope")
            self._ensure_scope(organization_id, req.entity_id, allowed_entity_ids)
            if req.status!="PENDING_APPROVAL": raise ValueError("Only pending requests can be rejected")
            if approver_id==req.requested_by: raise ValueError("Self-approval is not allowed")
            req.status="REJECTED"; req.rejection_reason=reason; req.decided_at=datetime.now(timezone.utc); s.commit()

    def _check_duplicate(self, s: Session, rec: MasterRecordORM, candidate_key: str | None = None):
        key=candidate_key or rec.normalized_key
        if not key or key.endswith("||"): return
        q=select(MasterRecordORM.master_id).where(and_(MasterRecordORM.organization_id==rec.organization_id, MasterRecordORM.master_type==rec.master_type,
            MasterRecordORM.entity_id==rec.entity_id, MasterRecordORM.normalized_key==key, MasterRecordORM.active==True))
        if rec.master_id: q=q.where(MasterRecordORM.master_id!=rec.master_id)
        if s.scalar(q): raise ValueError("Duplicate active master detected")

    def _check_overlap(self, s: Session, candidate: MasterRecordORM, exclude: UUID | None):
        if candidate.master_type not in EFFECTIVE_TYPES or not candidate.effective_from: return
        rows=s.scalars(select(MasterRecordORM).where(and_(MasterRecordORM.organization_id==candidate.organization_id,
            MasterRecordORM.master_type==candidate.master_type, MasterRecordORM.active==True))).all()
        for r in rows:
            if exclude and r.master_id==exclude: continue
            if r.entity_id!=candidate.entity_id: continue
            if not r.effective_from: continue
            start_a,end_a=candidate.effective_from,candidate.effective_to
            start_b,end_b=r.effective_from,r.effective_to
            if (end_a is None or start_b <= end_a) and (end_b is None or start_a <= end_b):
                raise ValueError("Effective-date period overlaps active master")

    def list(self, organization_id: UUID, master_type: str, q: str="", active_only: bool=True, entity_id: UUID|None=None, offset:int=0, limit:int=50, allowed_entity_ids: Iterable[UUID]|None=None):
        if master_type not in VALID_TYPES: raise ValueError("Unsupported master type")
        self._ensure_scope(organization_id, entity_id, allowed_entity_ids)
        limit=max(1,min(limit,200)); offset=max(0,offset)
        with self.session_factory() as s:
            stmt=select(MasterRecordORM).where(MasterRecordORM.organization_id==organization_id, MasterRecordORM.master_type==master_type)
            if active_only: stmt=stmt.where(MasterRecordORM.active==True)
            if entity_id is not None: stmt=stmt.where(MasterRecordORM.entity_id==entity_id)
            total=s.scalar(select(func.count()).select_from(stmt.subquery()))
            rows=s.scalars(stmt.order_by(MasterRecordORM.updated_at.desc()).offset(offset).limit(limit)).all()
            return rows,total

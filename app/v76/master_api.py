from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

VALID_TYPES = {
    "PRODUCT", "VARIANT", "PACK_SIZE", "SKU", "UOM_CONVERSION",
    "CUSTOMER", "SUPPLIER", "WAREHOUSE", "BIN", "TAX_PROFILE",
    "HSN", "PRICE_LIST", "TERRITORY", "ROLE", "ACCOUNTING_LEDGER_MAPPING"
}
VALID_ACTIONS = {"CREATE", "UPDATE", "DEACTIVATE"}

@dataclass
class MasterRecord:
    organization_id: UUID
    master_type: str
    master_id: UUID = field(default_factory=uuid4)
    entity_id: UUID | None = None
    data: dict[str, Any] = field(default_factory=dict)
    version_no: int = 1
    active: bool = True
    effective_from: datetime | None = None
    effective_to: datetime | None = None
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

@dataclass
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
    request_id: UUID = field(default_factory=uuid4)
    status: str = "PENDING_APPROVAL"
    requested_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

class MasterAdminRegistry:
    def __init__(self) -> None:
        self.records: dict[UUID, MasterRecord] = {}
        self.requests: dict[UUID, ChangeRequest] = {}
        self.snapshots: dict[UUID, list[dict[str, Any]]] = {}
        self.audit: list[dict[str, Any]] = []

    def _validate(self, master_type: str, action: str, payload: dict[str, Any]) -> None:
        if master_type not in VALID_TYPES:
            raise ValueError("Unsupported master type")
        if action not in VALID_ACTIONS:
            raise ValueError("Unsupported master action")
        if not payload:
            raise ValueError("Payload is required")

    def _duplicate_key(self, r: MasterRecord) -> tuple:
        code = r.data.get("code") or r.data.get("sku") or r.data.get("gstin") or r.data.get("name")
        return (r.organization_id, r.master_type, str(r.entity_id or ""), str(code).strip().lower() if code is not None else "")

    def _ensure_no_duplicate(self, candidate: MasterRecord, exclude: UUID | None = None) -> None:
        key = self._duplicate_key(candidate)
        if not key[-1]:
            return
        for mid, rec in self.records.items():
            if exclude and mid == exclude:
                continue
            if rec.active and self._duplicate_key(rec) == key:
                raise ValueError("Duplicate active master detected")

    def request(self, req: ChangeRequest) -> ChangeRequest:
        self._validate(req.master_type, req.action, req.payload)
        if req.action == "DEACTIVATE" and not (req.payload.get("reason") or "").strip():
            raise ValueError("Deactivation reason is required")
        if req.action in {"UPDATE", "DEACTIVATE"} and not req.master_id:
            raise ValueError("master_id is required for update/deactivate")
        if req.master_type in {"TAX_PROFILE", "HSN", "PRICE_LIST", "UOM_CONVERSION", "ACCOUNTING_LEDGER_MAPPING"} and req.effective_from is None:
            raise ValueError("effective_from is required for this master type")
        self.requests[req.request_id] = req
        return req

    def approve(self, request_id: UUID, approver_id: UUID, reason: str = "") -> MasterRecord:
        req = self.requests[request_id]
        if req.status != "PENDING_APPROVAL":
            raise ValueError("Only pending requests can be approved")
        if approver_id == req.requested_by:
            raise ValueError("Self-approval is not allowed")
        if req.action == "DEACTIVATE" and not (req.payload.get("reason") or reason).strip():
            raise ValueError("Deactivation reason is required")
        if req.action == "CREATE":
            rec = MasterRecord(req.organization_id, req.master_type, data=dict(req.payload), entity_id=req.entity_id,
                               effective_from=req.effective_from, effective_to=req.effective_to)
            self._ensure_no_duplicate(rec)
            self.records[rec.master_id] = rec
        else:
            rec = self.records.get(req.master_id)
            if not rec or rec.organization_id != req.organization_id:
                raise ValueError("Master not found in organization scope")
            self.snapshots.setdefault(rec.master_id, []).append({"version_no": rec.version_no, "data": dict(rec.data), "active": rec.active, "at": rec.updated_at.isoformat()})
            if req.action == "UPDATE":
                candidate = MasterRecord(rec.organization_id, rec.master_type, rec.master_id, rec.entity_id, dict(rec.data), rec.version_no + 1, rec.active, req.effective_from or rec.effective_from, req.effective_to or rec.effective_to)
                candidate.data.update(req.payload)
                self._ensure_no_duplicate(candidate, exclude=rec.master_id)
                rec.data = candidate.data
                rec.effective_from = candidate.effective_from
                rec.effective_to = candidate.effective_to
                rec.version_no += 1
                rec.updated_at = datetime.now(timezone.utc)
            else:
                rec.active = False
                rec.version_no += 1
                rec.updated_at = datetime.now(timezone.utc)
        req.status = "APPROVED"
        self.audit.append({"request_id": str(req.request_id), "master_type": req.master_type, "action": req.action, "approver_id": str(approver_id), "reason": reason, "at": datetime.now(timezone.utc).isoformat()})
        return self.records[rec.master_id] if req.action != "CREATE" else rec

    def search(self, organization_id: UUID, master_type: str, q: str = "", active_only: bool = True, entity_id: UUID | None = None) -> list[MasterRecord]:
        out=[]
        ql=q.strip().lower()
        for rec in self.records.values():
            if rec.organization_id != organization_id or rec.master_type != master_type:
                continue
            if active_only and not rec.active:
                continue
            if entity_id and rec.entity_id != entity_id:
                continue
            if ql and ql not in str(rec.data).lower():
                continue
            out.append(rec)
        return sorted(out, key=lambda r: r.updated_at, reverse=True)

    def history(self, master_id: UUID) -> list[dict[str, Any]]:
        return list(self.snapshots.get(master_id, []))

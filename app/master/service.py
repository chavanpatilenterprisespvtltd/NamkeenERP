from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

@dataclass
class MasterChangeRequest:
    organization_id: UUID
    master_type: str
    action: str
    requested_by: UUID
    payload: dict[str, Any]
    entity_id: UUID | None = None
    master_id: UUID | None = None
    client_event_id: str | None = None
    request_id: UUID = field(default_factory=uuid4)
    status: str = "PENDING_APPROVAL"
    requested_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

class MasterAdminService:
    VALID_TYPES = {
        "PRODUCT", "VARIANT", "PACK_SIZE", "SKU", "UOM_CONVERSION",
        "CUSTOMER", "SUPPLIER", "WAREHOUSE", "BIN", "TAX_PROFILE",
        "HSN", "PRICE_LIST", "TERRITORY", "ROLE", "ACCOUNTING_LEDGER_MAPPING"
    }

    def request(self, req: MasterChangeRequest) -> MasterChangeRequest:
        if req.master_type not in self.VALID_TYPES:
            raise ValueError("Unsupported master type")
        if req.action not in {"CREATE", "UPDATE", "DEACTIVATE"}:
            raise ValueError("Unsupported master action")
        if not req.payload:
            raise ValueError("Payload is required")
        return req

    def approve(self, req: MasterChangeRequest, approver_id: UUID, reason: str = "") -> dict[str, Any]:
        if req.status != "PENDING_APPROVAL":
            raise ValueError("Only pending master changes can be approved")
        if approver_id == req.requested_by:
            raise ValueError("Self-approval is not allowed")
        return {"request_id": str(req.request_id), "status": "APPROVED", "approved_by": str(approver_id), "reason": reason, "decided_at": datetime.now(timezone.utc).isoformat()}

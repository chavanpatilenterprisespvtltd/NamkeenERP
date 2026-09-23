from dataclasses import dataclass
from typing import Any
@dataclass(frozen=True)
class ApprovalView:
    request_id:str; status:str; validation_status:str|None; warnings:list[str]; errors:list[str]; changed_fields:list[str]; effective_from:str|None; can_approve:bool
def build_approval_view(request:dict[str,Any], actor_id:str)->ApprovalView:
    return ApprovalView(str(request["request_id"]),request.get("status","PENDING_APPROVAL"),request.get("validation_status"),list(request.get("warnings",[])),list(request.get("errors",[])),sorted(request.get("changed_fields",[])),request.get("effective_from"),request.get("status")=="PENDING_APPROVAL" and actor_id!=request.get("requested_by") and not request.get("errors"))

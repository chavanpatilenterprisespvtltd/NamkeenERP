from uuid import uuid4
import pytest
from app.master.service import MasterAdminService, MasterChangeRequest

def make_req(action="CREATE"):
    return MasterChangeRequest(uuid4(), "PRODUCT", action, uuid4(), {"name":"Demo"})

def test_supported_master_types_and_request():
    s=MasterAdminService(); r=make_req(); assert s.request(r).status == "PENDING_APPROVAL"

def test_rejects_unknown_master_type():
    s=MasterAdminService(); r=make_req(); r.master_type="UNKNOWN"
    with pytest.raises(ValueError): s.request(r)

def test_self_approval_blocked():
    s=MasterAdminService(); r=make_req()
    with pytest.raises(ValueError): s.approve(r, r.requested_by)

def test_other_approver_allowed():
    s=MasterAdminService(); r=make_req(); out=s.approve(r, uuid4(), "verified")
    assert out["status"] == "APPROVED"

def test_payload_required():
    s=MasterAdminService(); r=make_req(); r.payload={}
    with pytest.raises(ValueError): s.request(r)

def test_actions_are_restricted():
    s=MasterAdminService(); r=make_req("DELETE")
    with pytest.raises(ValueError): s.request(r)

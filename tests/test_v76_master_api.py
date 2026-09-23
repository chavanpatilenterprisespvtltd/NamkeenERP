from uuid import uuid4
from app.v76.master_api import MasterAdminRegistry, ChangeRequest

def test_create_search_update_history():
    s=MasterAdminRegistry(); org=uuid4(); user=uuid4(); approver=uuid4()
    req=s.request(ChangeRequest(org,"PRODUCT","CREATE",user,{"code":"P001","name":"Demo"}))
    rec=s.approve(req.request_id, approver, "verified")
    assert len(s.search(org,"PRODUCT",q="P001"))==1
    upd=s.request(ChangeRequest(org,"PRODUCT","UPDATE",user,{"name":"Demo 2"},master_id=rec.master_id))
    rec2=s.approve(upd.request_id, approver)
    assert rec2.version_no==2 and len(s.history(rec.master_id))==1

def test_duplicate_active_master_blocked():
    s=MasterAdminRegistry(); org=uuid4(); u=uuid4(); a=uuid4()
    for _ in range(2):
        req=s.request(ChangeRequest(org,"PRODUCT","CREATE",u,{"code":"DUP"}))
        if _==0: s.approve(req.request_id,a)
        else:
            try: s.approve(req.request_id,a)
            except ValueError as e: assert "Duplicate" in str(e)
            else: raise AssertionError("duplicate accepted")

def test_effective_dated_master_requires_start():
    s=MasterAdminRegistry(); req=ChangeRequest(uuid4(),"TAX_PROFILE","CREATE",uuid4(),{"rate":5})
    try: s.request(req)
    except ValueError as e: assert "effective_from" in str(e)
    else: raise AssertionError("missing effective date accepted")

def test_self_approval_blocked():
    s=MasterAdminRegistry(); u=uuid4(); req=s.request(ChangeRequest(uuid4(),"PRODUCT","CREATE",u,{"name":"X"}))
    try: s.approve(req.request_id,u)
    except ValueError as e: assert "Self-approval" in str(e)
    else: raise AssertionError("self approval accepted")

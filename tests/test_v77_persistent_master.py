from datetime import datetime, timezone, timedelta
from uuid import uuid4
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.v77.persistent_master import Base, PersistentMasterAdmin, ChangeRequest

def svc():
    e=create_engine("sqlite:///:memory:", connect_args={"check_same_thread":False})
    Base.metadata.create_all(e)
    return PersistentMasterAdmin(sessionmaker(bind=e, expire_on_commit=False))

def test_persistent_create_update_history_and_optimistic_lock():
    s=svc(); org=uuid4(); u=uuid4(); a=uuid4()
    rid=s.request(ChangeRequest(org,"PRODUCT","CREATE",u,{"code":"P1","name":"A"}))
    mid=s.approve(org,rid,a)
    rows,total=s.list(org,"PRODUCT"); assert total==1 and rows[0].version_no==1
    rid2=s.request(ChangeRequest(org,"PRODUCT","UPDATE",u,{"name":"B"},master_id=mid,base_version_no=1))
    s.approve(org,rid2,a)
    rows,_=s.list(org,"PRODUCT"); assert rows[0].version_no==2
    rid3=s.request(ChangeRequest(org,"PRODUCT","UPDATE",u,{"name":"C"},master_id=mid,base_version_no=1))
    try: s.approve(org,rid3,a)
    except ValueError as e: assert "Optimistic lock" in str(e)
    else: raise AssertionError("stale update accepted")

def test_duplicate_and_effective_overlap_blocked():
    s=svc(); org=uuid4(); u=uuid4(); a=uuid4()
    r=s.request(ChangeRequest(org,"SKU","CREATE",u,{"code":"S1"})); s.approve(org,r,a)
    r2=s.request(ChangeRequest(org,"SKU","CREATE",u,{"code":"S1"}))
    try: s.approve(org,r2,a)
    except ValueError as e: assert "Duplicate" in str(e)
    else: raise AssertionError("duplicate accepted")
    t0=datetime.now(timezone.utc)
    r3=s.request(ChangeRequest(org,"TAX_PROFILE","CREATE",u,{"code":"T1"},effective_from=t0,effective_to=t0+timedelta(days=30))); s.approve(org,r3,a)
    r4=s.request(ChangeRequest(org,"TAX_PROFILE","CREATE",u,{"code":"T2"},effective_from=t0+timedelta(days=10),effective_to=t0+timedelta(days=40)))
    try: s.approve(org,r4,a)
    except ValueError as e: assert "overlaps" in str(e)
    else: raise AssertionError("overlap accepted")

def test_entity_scope_restriction_and_client_idempotency():
    s=svc(); org=uuid4(); entity=uuid4(); blocked=uuid4(); u=uuid4()
    event="evt-1"; req=ChangeRequest(org,"CUSTOMER","CREATE",u,{"code":"C1"},entity_id=entity,client_event_id=event)
    r1=s.request(req); r2=s.request(req); assert r1==r2
    try: s.list(org,"CUSTOMER",entity_id=entity,allowed_entity_ids=[blocked])
    except ValueError as e: assert "access denied" in str(e).lower()
    else: raise AssertionError("entity access bypassed")

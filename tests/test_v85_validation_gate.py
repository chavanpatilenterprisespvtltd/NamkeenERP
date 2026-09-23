from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.v77.persistent_master import Base as V77Base
from app.v85.service import Base as V85Base, ValidatedMasterAdmin
from app.v77.persistent_master import ChangeRequest, MasterRecordORM


def make_admin():
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    V77Base.metadata.create_all(engine)
    V85Base.metadata.create_all(engine)
    Session = sessionmaker(engine)
    return Session, ValidatedMasterAdmin(Session)


def test_blocking_validation_never_enters_approval():
    Session, admin = make_admin()
    org, user = uuid4(), uuid4()
    req = ChangeRequest(org, "PRICE_LIST", "CREATE", user,
                        {"price": 100, "minimum_price": 120, "maximum_discount_pct": 10, "sku": "A"},
                        client_event_id="v85-block")
    try:
        admin.request(req)
        assert False, "expected validation block"
    except ValueError as exc:
        assert "minimum_price" in str(exc)
    with Session() as s:
        assert s.query(__import__("app.v77.persistent_master", fromlist=["MasterChangeRequestORM"]).MasterChangeRequestORM).count() == 0


def test_warning_can_submit_and_is_recorded():
    Session, admin = make_admin()
    org, user = uuid4(), uuid4()
    req = ChangeRequest(org, "SKU", "CREATE", user,
                        {"product_id": str(uuid4()), "pack_size_id": str(uuid4())},
                        client_event_id="v85-warning")
    request_id, result = admin.request(req)
    assert result.status == "WARNING"
    assert any("barcode" in w for w in result.warnings)
    with Session() as s:
        rows = s.query(__import__("app.v85.service", fromlist=["MasterValidationRunORM"]).MasterValidationRunORM).all()
        assert any(r.request_id == request_id and r.stage == "REQUEST" and r.status == "WARNING" for r in rows)


def test_approval_revalidates_current_record_and_blocks_drift():
    Session, admin = make_admin()
    org, requester, approver = uuid4(), uuid4(), uuid4()
    master_id = uuid4()
    with Session() as s:
        s.add(MasterRecordORM(master_id=master_id, organization_id=org, master_type="PRICE_LIST", entity_id=None,
                              data={"price": 100, "minimum_price": 90, "maximum_discount_pct": 5, "sku": "A"},
                              normalized_key="PRICE_LIST||a", version_no=1, active=True,
                              effective_from=datetime(2026, 1, 1, tzinfo=timezone.utc)))
        s.commit()
    req = ChangeRequest(org, "PRICE_LIST", "UPDATE", requester,
                        {"minimum_price": 95}, master_id=master_id, base_version_no=1,
                        effective_from=datetime(2026, 1, 1, tzinfo=timezone.utc), client_event_id="v85-drift")
    rid, _ = admin.request(req)
    # Simulate an independent concurrent edit after submission: current price drops below requested floor.
    with Session() as s:
        row = s.get(MasterRecordORM, master_id)
        row.data = {**row.data, "price": 80}
        s.commit()
    try:
        admin.approve(org, rid, approver)
        assert False, "approval should be blocked by re-validation"
    except ValueError as exc:
        assert "minimum_price" in str(exc)
    with Session() as s:
        row = s.get(MasterRecordORM, master_id)
        assert row.data["minimum_price"] == 90

from uuid import uuid4
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.v77.persistent_master import Base, ChangeRequest
from app.v86.service import ProductionMasterAdminV86, MasterChangeRequestORM, MasterValidationRunORM


def setup():
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)


def test_submit_persists_validation_on_request():
    SF = setup(); svc = ProductionMasterAdminV86(SF)
    org = uuid4(); user = uuid4()
    rid, res = svc.submit(ChangeRequest(org, "PRODUCT", "CREATE", user, {"code":"P86", "name":"Product 86"}))
    with SF() as s:
        req = s.scalar(select(MasterChangeRequestORM).where(MasterChangeRequestORM.request_id == rid))
        runs = s.scalars(select(MasterValidationRunORM).where(MasterValidationRunORM.request_id == rid)).all()
        assert req.validation_status in {"PASS", "WARNING"}
        assert req.validation_id is not None
        assert req.validation_version == "v86"
        assert len(runs) == 1 and runs[0].stage == "REQUEST"


def test_blocked_never_enters_approval():
    SF = setup(); svc = ProductionMasterAdminV86(SF)
    with __import__('pytest').raises(ValueError):
        svc.submit(ChangeRequest(uuid4(), "PACK_SIZE", "CREATE", uuid4(), {"quantity":1, "uom":"bad"}))
    with SF() as s:
        assert s.scalar(select(MasterChangeRequestORM)) is None
        run = s.scalar(select(MasterValidationRunORM))
        assert run.status == "BLOCKED"


def test_approval_revalidates_and_stamps_final_validation():
    SF = setup(); svc = ProductionMasterAdminV86(SF)
    org = uuid4(); user = uuid4(); approver = uuid4()
    rid, _ = svc.submit(ChangeRequest(org, "PRODUCT", "CREATE", user, {"code":"P87", "name":"Product 87"}))
    mid, res = svc.approve(org, rid, approver)
    with SF() as s:
        req = s.get(MasterChangeRequestORM, rid)
        runs = s.scalars(select(MasterValidationRunORM).where(MasterValidationRunORM.request_id == rid).order_by(MasterValidationRunORM.validated_at)).all()
        assert req.status == "APPROVED"
        assert req.validation_status in {"PASS", "WARNING"}
        assert req.validation_id == runs[-1].validation_id
        assert runs[-1].stage == "APPROVAL"


def test_optimistic_lock_checked_in_atomic_approval_path():
    SF = setup(); svc = ProductionMasterAdminV86(SF)
    org = uuid4(); user = uuid4(); approver = uuid4()
    rid, _ = svc.submit(ChangeRequest(org, "PRODUCT", "CREATE", user, {"code":"P88", "name":"Product 88"}))
    mid, _ = svc.approve(org, rid, approver)
    rid2, _ = svc.submit(ChangeRequest(org, "PRODUCT", "UPDATE", user, {"name":"Updated 88"}, master_id=mid, base_version_no=1))
    with SF() as s:
        row = s.get(__import__('app.v77.persistent_master', fromlist=['MasterRecordORM']).MasterRecordORM, mid)
        row.version_no = 2
        s.commit()
    with __import__('pytest').raises(ValueError, match='Optimistic lock conflict'):
        svc.approve(org, rid2, approver)

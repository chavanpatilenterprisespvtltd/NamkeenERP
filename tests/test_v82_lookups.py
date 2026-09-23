from uuid import uuid4
from datetime import datetime, timezone
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.v77.persistent_master import Base, MasterRecordORM
from app.v82.lookups import lookup, lookup_relationships

def seeded():
    e=create_engine("sqlite:///:memory:", connect_args={"check_same_thread":False})
    Base.metadata.create_all(e); S=sessionmaker(bind=e); org=uuid4(); product=uuid4(); variant=uuid4(); pack=uuid4(); wh=uuid4(); tax=uuid4();
    with S() as s:
        now=datetime.now(timezone.utc)
        s.add_all([
          MasterRecordORM(master_id=product,organization_id=org,master_type="PRODUCT",data={"code":"P1","name":"Namkeen"},normalized_key="PRODUCT||p1",updated_at=now),
          MasterRecordORM(master_id=variant,organization_id=org,master_type="VARIANT",data={"code":"V1","name":"Regular","product_id":str(product)},normalized_key="VARIANT||v1",updated_at=now),
          MasterRecordORM(master_id=pack,organization_id=org,master_type="PACK_SIZE",data={"code":"PK500","name":"500g","quantity":500,"uom":"g"},normalized_key="PACK_SIZE||pk500",updated_at=now),
          MasterRecordORM(organization_id=org,master_type="SKU",data={"sku":"P1-V1-500","name":"Regular 500g","product_id":str(product),"variant_id":str(variant),"pack_size_id":str(pack)},normalized_key="SKU||p1-v1-500",updated_at=now),
          MasterRecordORM(master_id=wh,organization_id=org,master_type="WAREHOUSE",data={"code":"FG","name":"FG Warehouse"},normalized_key="WAREHOUSE||fg",updated_at=now),
          MasterRecordORM(organization_id=org,master_type="BIN",data={"code":"FG-A1","name":"A1","warehouse_id":str(wh)},normalized_key="BIN||fg-a1",updated_at=now),
          MasterRecordORM(master_id=tax,organization_id=org,master_type="TAX_PROFILE",data={"code":"GST","name":"GST"},normalized_key="TAX_PROFILE||gst",updated_at=now),
          MasterRecordORM(organization_id=org,master_type="HSN",data={"code":"190590","description":"Snack","tax_profile_id":str(tax)},normalized_key="HSN||190590",updated_at=now),
        ]); s.commit()
    return S,org,product,variant,pack,wh,tax

def test_product_scoped_variants_and_skus():
    S,org,product,variant,pack,wh,tax=seeded()
    vars_=lookup(S,organization_id=org,kind="variants",parent_id=product)
    assert [x["key"] for x in vars_]==["V1"]
    skus=lookup(S,organization_id=org,kind="skus",parent_id=product)
    assert len(skus)==1 and skus[0]["key"]=="P1-V1-500"

def test_warehouse_bin_and_tax_hsn_dependencies():
    S,org,product,variant,pack,wh,tax=seeded()
    assert lookup(S,organization_id=org,kind="bins",parent_id=wh)[0]["key"]=="FG-A1"
    assert lookup(S,organization_id=org,kind="hsn",parent_id=tax)[0]["key"]=="190590"

def test_relationship_bundle_is_scoped():
    S,org,product,variant,pack,wh,tax=seeded()
    bundle=lookup_relationships(S,organization_id=org,product_id=product,variant_id=variant,pack_size_id=pack,warehouse_id=wh,tax_profile_id=tax)
    assert set(bundle)=={"variants","skus","skus_by_variant","skus_by_pack","bins","hsn"}
    assert bundle["skus_by_variant"][0]["key"]=="P1-V1-500"

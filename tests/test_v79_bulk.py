from pathlib import Path
from uuid import uuid4
from app.v79.bulk_master import preview_bytes, export_csv
import csv, io

def csv_payload(rows):
    out=io.StringIO(); w=csv.writer(out)
    w.writerow(["action","master_type","master_id","entity_id","effective_from","effective_to","base_version_no","data_json"])
    w.writerows(rows)
    return out.getvalue().encode()

def test_csv_preview_and_duplicate_detection():
    org=uuid4()
    payload=csv_payload([
        ["CREATE","PRODUCT","","","","","","{\"code\":\"P1\",\"name\":\"A\"}"],
        ["CREATE","PRODUCT","","","","","","{\"code\":\"P1\",\"name\":\"B\"}"],
    ])
    p=preview_bytes(payload,'products.csv',org)
    assert len(p.rows)==2
    assert any(i.code=='DUPLICATE_FILE_KEY' for i in p.issues)

def test_update_requires_master_and_effective_type_requires_start():
    org=uuid4()
    payload=csv_payload([
        ["UPDATE","PRODUCT","","","","","","{\"name\":\"B\"}"],
        ["CREATE","TAX_PROFILE","","","","","","{\"code\":\"T1\",\"rate\":5}"],
    ])
    p=preview_bytes(payload,'m.csv',org)
    codes={i.code for i in p.issues}
    assert 'REQUIRED' in codes

def test_deactivate_reason_required():
    org=uuid4(); mid=uuid4()
    payload=csv_payload([["DEACTIVATE","PRODUCT",str(mid),"","","","","{}"]])
    p=preview_bytes(payload,'m.csv',org)
    assert any(i.code=='REASON_REQUIRED' for i in p.issues)

def test_export_csv_is_deterministic_shape():
    b=export_csv([{'master_id':'1','entity_id':'2','master_type':'PRODUCT','version_no':1,'active':True,'effective_from':'','effective_to':'','data_json':{'code':'P1'}}])
    text=b.decode()
    assert text.splitlines()[0].startswith('master_id,entity_id,master_type')
    assert 'P1' in text and 'data_json' in text

def test_migration_present():
    assert Path(__file__).parents[1].joinpath('migrations/068_v79_bulk_master_import_export.sql').exists()

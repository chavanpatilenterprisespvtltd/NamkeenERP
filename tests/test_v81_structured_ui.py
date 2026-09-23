from uuid import uuid4
from app.v81.master_schemas import field_meta, validate_payload
from app.v81.app import app

def test_all_master_types_have_structured_schema():
    expected={"PRODUCT","VARIANT","PACK_SIZE","SKU","UOM_CONVERSION","CUSTOMER","SUPPLIER","WAREHOUSE","BIN","TAX_PROFILE","HSN","PRICE_LIST","TERRITORY","ROLE","ACCOUNTING_LEDGER_MAPPING"}
    from app.v77.persistent_master import VALID_TYPES
    assert expected == VALID_TYPES
    for t in expected:
        m=field_meta(t); assert m["master_type"]==t and m["fields"]

def test_required_fields_are_enforced():
    assert any("Code is required"==e for e in validate_payload("PRODUCT",{},"CREATE"))
    assert not validate_payload("PRODUCT",{"code":"P1","name":"Product 1"},"CREATE")

def test_effective_master_metadata():
    assert field_meta("PRICE_LIST")["effective"] is True
    assert field_meta("CUSTOMER")["effective"] is False

def test_deactivation_requires_reason():
    assert "Deactivation reason is required" in validate_payload("CUSTOMER",{},"DEACTIVATE")
    assert not validate_payload("CUSTOMER",{"reason":"Closed"},"DEACTIVATE")

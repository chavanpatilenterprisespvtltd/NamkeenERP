from app.v84.rules import validate_cross_field


def test_tax_profile_consistency():
    e = validate_cross_field("TAX_PROFILE", {"gst_rate": 5, "cgst_rate": 2.5, "sgst_rate": 2.5, "igst_rate": 5})
    assert e == []
    e2 = validate_cross_field("TAX_PROFILE", {"gst_rate": 5, "cgst_rate": 1, "sgst_rate": 1, "igst_rate": 5})
    assert any("cgst_rate" in x for x in e2)


def test_price_floor_and_pack_uom():
    e = validate_cross_field("PRICE_LIST", {"price": 100, "minimum_price": 120, "maximum_discount_pct": 10, "sku": "A"})
    assert any("minimum_price" in x for x in e)
    e2 = validate_cross_field("PACK_SIZE", {"quantity": 500, "uom": "g"})
    assert e2 == []


def test_sku_and_bin_uuid_rules():
    e = validate_cross_field("SKU", {"product_id": "bad", "pack_size_id": "bad"})
    assert len(e) >= 2
    e2 = validate_cross_field("BIN", {"warehouse_id": "bad"})
    assert any("warehouse_id" in x for x in e2)


def test_hsn_and_gstin_structural_rules():
    assert validate_cross_field("HSN", {"code": "3004"}) == []
    assert validate_cross_field("HSN", {"code": "30A4"})
    assert validate_cross_field("CUSTOMER", {"gstin": "INVALID"})

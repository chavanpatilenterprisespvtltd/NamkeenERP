from app.v87.approval_ui import build_approval_view
def test_view_rules():
 r={"request_id":"r1","status":"PENDING_APPROVAL","requested_by":"u1","validation_status":"PASS","warnings":[],"errors":[],"changed_fields":["name"]}
 assert build_approval_view(r,"u2").can_approve and not build_approval_view(r,"u1").can_approve
 r["errors"]=["x"]; assert not build_approval_view(r,"u2").can_approve

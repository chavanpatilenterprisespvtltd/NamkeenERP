from fastapi.testclient import TestClient
from app.__main__ import app, engine
from app.auth import make_access_token, UserRecord
from app.identity import create_user
from sqlalchemy import text
from uuid import uuid4

def user(role="manager"):
    uid=str(uuid4()); name="bl_"+uid[:8]
    create_user(engine,uid,name,"pw","BL User",role)
    return uid,name

def headers(uid,name,role="manager"):
    return {"Authorization":f"Bearer {make_access_token(UserRecord(uid,name,role))}"}

def test_management_summary_access_and_metrics_shape():
    uid,name=user("manager"); c=TestClient(app,headers=headers(uid,name))
    r=c.get("/v90bl/management-summary"); assert r.status_code==200
    body=r.json(); assert body["release"].lower() >= "v90.bl"; assert "pending_approvals" in body["metrics"]

def test_approval_inbox_and_notification_center():
    uid,name=user("manager"); c=TestClient(app,headers=headers(uid,name))
    assert c.get("/v90bl/approval-inbox").status_code==200
    assert c.get("/v90bl/notification-center").status_code==200

def test_notification_mark_read_round_trip():
    uid,name=user("manager"); h=headers(uid,name)
    org=str(uuid4()); nid=str(uuid4())
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO notifications(notification_id,organization_id,recipient_user_id,channel,body,status,created_by) VALUES(:i,:o,:u,'IN_APP','hello','PENDING',:u)"),{"i":nid,"o":org,"u":uid})
    c=TestClient(app,headers=h); r=c.post(f"/v90bl/notifications/{nid}/read"); assert r.status_code==200
    rows=c.get("/v90bl/notification-center").json()["notifications"]; assert rows[0]["is_read"]==1

def test_management_ui_requires_permission():
    uid,name=user("operator"); c=TestClient(app,headers=headers(uid,name,"operator"))
    assert c.get("/v90bl/management-summary").status_code==403

def test_migration_137_and_manifest():
    from app.migrations import load_migrations
    ms=load_migrations(); assert any(m.version==137 and m.filename=="137_v90bl_management_dashboard_approval_notification_ui.sql" for m in ms); assert ms[-1].version >= 137

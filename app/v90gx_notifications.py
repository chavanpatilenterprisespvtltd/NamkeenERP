# FILE PATH: app/v90gx_notifications.py
# ─── Notification Outbox & Providers v1.0 (Session CS2 — SMS/WhatsApp via HTTP webhook, email via SMTP, honest stub) ─
#
# [Session CS2] FEATURE — NOTHING WAS EVER SENT: NOTIFICATION_PROVIDER=stub AND NO SENDING CODE.
# Confirmed this session by reading config/.env.production.example (NOTIFICATION_PROVIDER=stub,
# NOTIFICATION_API_KEY_FILE) and searching app/ — no outbox, no provider adapter; app/worker.py only slept.
#
# THE FIX (runtime schema here; PostgreSQL migration 278_v90gx_notifications.sql):
#   - notification_outbox: channel SMS / WHATSAPP / EMAIL, recipient, subject, body, status
#     QUEUED → SENT | FAILED (after NOTIFICATION_MAX_ATTEMPTS, default 5, with back-off) | SKIPPED_STUB.
#     dedupe_key prevents the same alert being queued twice.
#   - Providers (NOTIFICATION_PROVIDER):
#       stub    → nothing is sent; status SKIPPED_STUB (never reported as SENT);
#       webhook → HTTPS POST JSON {channel,to,subject,body,reference} to NOTIFICATION_WEBHOOK_URL with
#                 "Authorization: Bearer <NOTIFICATION_API_KEY(_FILE)>" — works with most Indian SMS /
#                 WhatsApp gateways through a small relay, or directly where the gateway accepts JSON;
#       EMAIL always uses SMTP when SMTP_HOST is set (SMTP_PORT, SMTP_USER, SMTP_PASSWORD(_FILE),
#                 SMTP_FROM, SMTP_STARTTLS=true), regardless of NOTIFICATION_PROVIDER.
#   - enqueue_daily_alerts(): FSSAI licence expiring within FSSAI_ALERT_DAYS (default 60) for every
#     entity profile; HIGH-severity open customer complaints; oil logs with DISCARD_REQUIRED today.
#     Recipient: the entity profile e-mail, else ERP_ALERT_EMAIL.
#   - process_outbox(): sends a batch; used by app/worker.py and POST /v90gx/notifications/process.
# No real gateway credentials were available this session: webhook/SMTP sending is covered by unit tests
# with a local fake HTTP server; it was NOT tried against a live SMS/WhatsApp provider.
# NOT touched: existing notification-center UI (v90bn) data, approval inbox.
from __future__ import annotations

import json
import os
import smtplib
import urllib.request
from datetime import date, datetime, timedelta, timezone
from email.message import EmailMessage
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.engine import Engine

from .auth import authenticate
from .identity import permissions_for_user
from .runtime_security import read_secret

PERMS = [('notification.view', 'View notification outbox'), ('notification.manage', 'Queue and process notifications')]


class NotifyIn(BaseModel):
    organization_id: str | None = None
    channel: str = Field(pattern='^(SMS|WHATSAPP|EMAIL)$')
    recipient: str = Field(min_length=5, max_length=200)
    subject: str | None = Field(default=None, max_length=200)
    body: str = Field(min_length=1, max_length=2000)
    template_code: str = Field(default='MANUAL', max_length=60)
    reference: str | None = Field(default=None, max_length=120)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def ensure_v90gx_notification_schema(e: Engine) -> None:
    with e.begin() as c:
        c.execute(text('''CREATE TABLE IF NOT EXISTS notification_outbox(notification_id TEXT PRIMARY KEY,organization_id TEXT NULL,channel TEXT NOT NULL,recipient TEXT NOT NULL,subject TEXT NULL,body TEXT NOT NULL,
            template_code TEXT NOT NULL,reference TEXT NULL,dedupe_key TEXT NULL UNIQUE,status TEXT NOT NULL DEFAULT 'QUEUED',attempts INTEGER NOT NULL DEFAULT 0,next_attempt_at TEXT NULL,
            last_error TEXT NULL,provider TEXT NULL,provider_message_id TEXT NULL,created_by TEXT NOT NULL,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,sent_at TIMESTAMP NULL)'''))
        c.execute(text('CREATE INDEX IF NOT EXISTS ix_notification_outbox_status ON notification_outbox(status,next_attempt_at)'))
        for p, n in PERMS:
            c.execute(text('INSERT INTO erp_permissions(permission_id,permission_name) VALUES(:p,:n) ON CONFLICT(permission_id) DO NOTHING'), {'p': p, 'n': n})
            c.execute(text("INSERT INTO erp_role_permissions(role_id,permission_id) VALUES('super_admin',:p) ON CONFLICT(role_id,permission_id) DO NOTHING"), {'p': p})
        for role in ('manager', 'mis'):
            c.execute(text("INSERT INTO erp_role_permissions(role_id,permission_id) VALUES(:r,'notification.view') ON CONFLICT(role_id,permission_id) DO NOTHING"), {'r': role})


def enqueue(e: Engine, *, channel: str, recipient: str, body: str, subject: str | None = None, organization_id: str | None = None,
            template_code: str = 'MANUAL', reference: str | None = None, dedupe_key: str | None = None, created_by: str = 'system') -> str | None:
    """Queue a message. Returns the id, or None when dedupe_key was already queued."""
    with e.begin() as c:
        if dedupe_key and c.execute(text('SELECT 1 FROM notification_outbox WHERE dedupe_key=:k'), {'k': dedupe_key}).first():
            return None
        nid = str(uuid4())
        c.execute(text('''INSERT INTO notification_outbox(notification_id,organization_id,channel,recipient,subject,body,template_code,reference,dedupe_key,created_by)
            VALUES(:i,:o,:c,:r,:s,:b,:t,:ref,:k,:u)'''), {'i': nid, 'o': organization_id, 'c': channel, 'r': recipient, 's': subject, 'b': body, 't': template_code,
                                                       'ref': reference, 'k': dedupe_key, 'u': created_by})
    return nid


def _send_email(row) -> str:
    host = os.getenv('SMTP_HOST')
    if not host:
        raise RuntimeError('SMTP_HOST is not configured')
    msg = EmailMessage()
    msg['From'] = os.getenv('SMTP_FROM') or os.getenv('SMTP_USER') or 'erp@localhost'
    msg['To'] = row['recipient']
    msg['Subject'] = row['subject'] or 'Namkeen ERP notification'
    msg.set_content(row['body'])
    with smtplib.SMTP(host, int(os.getenv('SMTP_PORT', '587')), timeout=20) as s:
        if os.getenv('SMTP_STARTTLS', 'true').lower() in {'1', 'true', 'yes'}:
            s.starttls()
        user = os.getenv('SMTP_USER')
        if user:
            s.login(user, read_secret('SMTP_PASSWORD') or '')
        s.send_message(msg)
    return msg.get('Message-ID') or 'smtp'


def _send_webhook(row) -> str:
    url = os.getenv('NOTIFICATION_WEBHOOK_URL')
    if not url:
        raise RuntimeError('NOTIFICATION_WEBHOOK_URL is not configured')
    data = json.dumps({'channel': row['channel'], 'to': row['recipient'], 'subject': row['subject'], 'body': row['body'], 'reference': row['reference'],
                       'notification_id': row['notification_id']}).encode()
    req = urllib.request.Request(url, data=data, method='POST', headers={'Content-Type': 'application/json'})
    key = read_secret('NOTIFICATION_API_KEY')
    if key:
        req.add_header('Authorization', f'Bearer {key}')
    with urllib.request.urlopen(req, timeout=20) as r:
        if r.status >= 300:
            raise RuntimeError(f'gateway HTTP {r.status}')
        raw = r.read().decode() or '{}'
    try:
        return str(json.loads(raw).get('message_id') or 'webhook')
    except ValueError:
        return 'webhook'


def process_outbox(e: Engine, limit: int = 50) -> dict:
    provider = (os.getenv('NOTIFICATION_PROVIDER') or 'stub').lower()
    max_attempts = int(os.getenv('NOTIFICATION_MAX_ATTEMPTS', '5'))
    now = _now()
    with e.connect() as c:
        rows = [dict(x) for x in c.execute(text("SELECT * FROM notification_outbox WHERE status='QUEUED' ORDER BY created_at LIMIT :n"), {'n': limit}).mappings().all()]
    counts = {'sent': 0, 'failed': 0, 'retry': 0, 'skipped_stub': 0}
    for row in rows:
        if row['next_attempt_at'] and row['next_attempt_at'] > now.isoformat():
            continue
        try:
            if row['channel'] == 'EMAIL' and os.getenv('SMTP_HOST'):
                used, mid = 'smtp', _send_email(row)
            elif provider == 'webhook':
                used, mid = 'webhook', _send_webhook(row)
            else:
                with e.begin() as c:
                    c.execute(text("UPDATE notification_outbox SET status='SKIPPED_STUB',provider='stub',last_error='NOTIFICATION_PROVIDER=stub: not sent' WHERE notification_id=:i"), {'i': row['notification_id']})
                counts['skipped_stub'] += 1
                continue
            with e.begin() as c:
                c.execute(text("UPDATE notification_outbox SET status='SENT',provider=:p,provider_message_id=:m,attempts=attempts+1,sent_at=CURRENT_TIMESTAMP,last_error=NULL WHERE notification_id=:i"),
                          {'p': used, 'm': mid, 'i': row['notification_id']})
            counts['sent'] += 1
        except Exception as ex:  # network/provider errors are recorded, never raised to the worker loop
            attempts = int(row['attempts']) + 1
            final = attempts >= max_attempts
            with e.begin() as c:
                c.execute(text('UPDATE notification_outbox SET attempts=:a,status=:s,last_error=:err,next_attempt_at=:n WHERE notification_id=:i'),
                          {'a': attempts, 's': 'FAILED' if final else 'QUEUED', 'err': f'{type(ex).__name__}: {ex}'[:500],
                           'n': (now + timedelta(minutes=2 ** attempts)).isoformat(), 'i': row['notification_id']})
            counts['failed' if final else 'retry'] += 1
    return counts


def enqueue_daily_alerts(e: Engine, today: date | None = None) -> int:
    today = today or _now().date()
    days = int(os.getenv('FSSAI_ALERT_DAYS', '60'))
    fallback = os.getenv('ERP_ALERT_EMAIL')
    queued = 0
    with e.connect() as c:
        profiles = [dict(x) for x in c.execute(text('SELECT entity_id,organization_id,legal_name,email,fssai_license_no,fssai_valid_to FROM erp_entity_profile')).mappings().all()]
        complaints = [dict(x) for x in c.execute(text("SELECT complaint_id,complaint_no,organization_id,entity_id,category,customer_name FROM customer_complaint WHERE severity='HIGH' AND status<>'CLOSED'")).mappings().all()]
        oil = [dict(x) for x in c.execute(text("SELECT log_id,entity_id,organization_id,fryer_id,tpm_pct FROM plant_oil_log WHERE status='DISCARD_REQUIRED' AND business_date=:d"), {'d': today.isoformat()}).mappings().all()]
    emails = {p['entity_id']: (p['email'] or fallback) for p in profiles}
    for p in profiles:
        if not p['fssai_valid_to']:
            continue
        valid = date.fromisoformat(str(p['fssai_valid_to'])[:10])
        left = (valid - today).days
        to = p['email'] or fallback
        if left <= days and to:
            if enqueue(e, channel='EMAIL', recipient=to, organization_id=p['organization_id'], template_code='FSSAI_EXPIRY', reference=p['entity_id'],
                       subject=f"FSSAI licence {'expired' if left < 0 else 'expires in %d days' % left}: {p['legal_name']}",
                       body=f"FSSAI licence {p['fssai_license_no']} of {p['legal_name']} is valid to {valid.isoformat()}. Start the renewal on FoSCoS now.",
                       dedupe_key=f"FSSAI:{p['entity_id']}:{valid.isoformat()}:{today.isoformat()}"):
                queued += 1
    for cpl in complaints:
        to = emails.get(cpl['entity_id']) or fallback
        if to and enqueue(e, channel='EMAIL', recipient=to, organization_id=cpl['organization_id'], template_code='COMPLAINT_HIGH', reference=cpl['complaint_id'],
                          subject=f"HIGH complaint open: {cpl['complaint_no']}", body=f"{cpl['category']} complaint from {cpl['customer_name']} is still open.",
                          dedupe_key=f"COMPLAINT:{cpl['complaint_id']}:{today.isoformat()}"):
            queued += 1
    for o in oil:
        to = emails.get(o['entity_id']) or fallback
        if to and enqueue(e, channel='EMAIL', recipient=to, organization_id=o['organization_id'], template_code='OIL_DISCARD', reference=o['log_id'],
                          subject=f"Frying oil must be discarded: fryer {o['fryer_id']}", body=f"TPM {o['tpm_pct']}% is above the limit. Do not use this oil.",
                          dedupe_key=f"OIL:{o['log_id']}"):
            queued += 1
    return queued


def _perm(e: Engine, r: Request, p: str):
    u = authenticate(r)
    ps = permissions_for_user(e, u.user_id)
    if p not in ps and 'admin.users' not in ps:
        raise HTTPException(403, 'permission denied')
    return u


def register_v90gx_notification_routes(app: FastAPI, e: Engine):
    ensure_v90gx_notification_schema(e)

    @app.post('/v90gx/notifications')
    def queue(b: NotifyIn, r: Request):
        u = _perm(e, r, 'notification.manage')
        nid = enqueue(e, channel=b.channel, recipient=b.recipient, body=b.body, subject=b.subject, organization_id=b.organization_id,
                      template_code=b.template_code, reference=b.reference, created_by=u.user_id)
        return {'notification_id': nid, 'status': 'QUEUED', 'provider': (os.getenv('NOTIFICATION_PROVIDER') or 'stub').lower()}

    @app.get('/v90gx/notifications')
    def outbox(r: Request, status: str | None = None, limit: int = 100):
        _perm(e, r, 'notification.view')
        q = 'SELECT * FROM notification_outbox'; p: dict = {'n': max(1, min(limit, 500))}
        if status:
            q += ' WHERE status=:s'; p['s'] = status.upper()
        with e.connect() as c:
            return {'notifications': [dict(x) for x in c.execute(text(q + ' ORDER BY created_at DESC LIMIT :n'), p).mappings().all()]}

    @app.post('/v90gx/notifications/process')
    def process(r: Request):
        _perm(e, r, 'notification.manage')
        alerts = enqueue_daily_alerts(e)
        return {'alerts_queued': alerts, **process_outbox(e)}

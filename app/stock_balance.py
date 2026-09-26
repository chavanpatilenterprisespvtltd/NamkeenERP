# FILE PATH: app/stock_balance.py
# ─── Stock Balance Helper v1.0 (Session CS2 — keep inventory_stock_balance in step with ledger postings) ─
#
# [Session CS2] FEATURE — INTERCOMPANY POSTINGS UPDATED ONLY inventory_stock_ledger.
# Confirmed this session by reading app/v90fm_intercompany_execution.py (ledger only) against
# app/v90m_receiving_qc.py and app/v90ag_dispatch_execution.py, which maintain both the ledger and
# inventory_stock_balance. Screens that read the balance table would not see intercompany moves.
# THE FIX: apply_balance() used by the V90.gx intercompany dispatch/receipt and purchase return:
#   delta > 0 → upsert (same ON CONFLICT key as GRN posting);
#   delta < 0 → decrement an existing row, HTTP 409 if it would go negative; if no balance row exists
#   the item is ledger-only (e.g. seeded opening stock) and the ledger check already guarded it.
# NOT touched: the legacy V90.fm post route, GRN, dispatch, packing or any existing balance logic.
from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import text


def apply_balance(conn, *, organization_id, entity_id, location_id, warehouse_id, item_master_id, uom, delta: float) -> None:
    key = {'o': str(organization_id), 'e': str(entity_id), 'l': str(location_id), 'w': str(warehouse_id), 'm': str(item_master_id), 'u': uom}
    if delta >= 0:
        conn.execute(text("""INSERT INTO inventory_stock_balance(organization_id,entity_id,location_id,warehouse_id,item_master_id,uom,available_qty,updated_at)
            VALUES(:o,:e,:l,:w,:m,:u,:q,CURRENT_TIMESTAMP) ON CONFLICT(organization_id,entity_id,location_id,warehouse_id,item_master_id,uom)
            DO UPDATE SET available_qty=inventory_stock_balance.available_qty+excluded.available_qty, updated_at=CURRENT_TIMESTAMP"""), {**key, 'q': delta})
        return
    row = conn.execute(text('SELECT available_qty FROM inventory_stock_balance WHERE organization_id=:o AND entity_id=:e AND location_id=:l AND warehouse_id=:w AND item_master_id=:m AND uom=:u'), key).first()
    if row is None:
        return
    if float(row[0]) + delta < -1e-9:
        raise HTTPException(409, f'stock balance for item {item_master_id} is lower than the quantity being moved')
    conn.execute(text('UPDATE inventory_stock_balance SET available_qty=available_qty+:q, updated_at=CURRENT_TIMESTAMP WHERE organization_id=:o AND entity_id=:e AND location_id=:l AND warehouse_id=:w AND item_master_id=:m AND uom=:u'), {**key, 'q': delta})

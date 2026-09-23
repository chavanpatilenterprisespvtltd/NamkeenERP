from __future__ import annotations
from pathlib import Path
from typing import Any
from uuid import UUID

from .bulk_master import apply_preview, make_xlsx_template, preview_bytes


def bulk_preview(organization_id: UUID, file_name: str, payload: bytes):
    return preview_bytes(payload, file_name, organization_id)


def bulk_submit(organization_id: UUID, requester_id: UUID, file_name: str, payload: bytes, admin_service: Any):
    preview = preview_bytes(payload, file_name, organization_id)
    return apply_preview(preview, admin_service, organization_id, requester_id)

def generate_template(master_type: str, output: str | Path) -> str:
    make_xlsx_template(master_type, output)
    return str(output)

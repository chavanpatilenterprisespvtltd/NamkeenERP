from __future__ import annotations

import csv
import hashlib
import io
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from uuid import UUID, uuid4

VALID_TYPES = {
    "PRODUCT", "VARIANT", "PACK_SIZE", "SKU", "UOM_CONVERSION", "CUSTOMER", "SUPPLIER", "WAREHOUSE", "BIN",
    "TAX_PROFILE", "HSN", "PRICE_LIST", "TERRITORY", "ROLE", "ACCOUNTING_LEDGER_MAPPING"
}
EFFECTIVE_TYPES = {"TAX_PROFILE", "HSN", "PRICE_LIST", "UOM_CONVERSION", "ACCOUNTING_LEDGER_MAPPING"}

@dataclass(frozen=True)
class BulkRow:
    row_number: int
    action: str
    master_type: str
    master_id: UUID | None
    entity_id: UUID | None
    effective_from: datetime | None
    effective_to: datetime | None
    base_version_no: int | None
    data: dict[str, Any]
    source: str = "file"

@dataclass(frozen=True)
class ValidationIssue:
    row_number: int
    field: str
    code: str
    message: str
    severity: str = "ERROR"

@dataclass
class BulkPreview:
    batch_id: UUID = field(default_factory=uuid4)
    file_name: str = ""
    content_sha256: str = ""
    rows: list[BulkRow] = field(default_factory=list)
    issues: list[ValidationIssue] = field(default_factory=list)

    @property
    def errors(self) -> list[ValidationIssue]:
        return [x for x in self.issues if x.severity == "ERROR"]

    @property
    def valid(self) -> bool:
        return not self.errors and bool(self.rows)

    def diff_summary(self, existing: dict[UUID, dict[str, Any]]) -> dict[str, int]:
        out = {"CREATE": 0, "UPDATE": 0, "DEACTIVATE": 0, "UNCHANGED": 0}
        for r in self.rows:
            if r.action == "CREATE":
                out["CREATE"] += 1
            elif r.action == "DEACTIVATE":
                out["DEACTIVATE"] += 1
            elif r.master_id in existing and existing[r.master_id] == r.data:
                out["UNCHANGED"] += 1
            else:
                out["UPDATE"] += 1
        return out


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _parse_uuid(value: Any, row: int, field: str, issues: list[ValidationIssue]) -> UUID | None:
    if value in (None, ""):
        return None
    try:
        return UUID(str(value).strip())
    except Exception:
        issues.append(ValidationIssue(row, field, "INVALID_UUID", f"{field} must be a valid UUID"))
        return None


def _parse_datetime(value: Any, row: int, field: str, issues: list[ValidationIssue]) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    text = str(value).strip()
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        issues.append(ValidationIssue(row, field, "INVALID_DATETIME", "Use ISO-8601 datetime, e.g. 2026-09-05T00:00:00+05:30"))
        return None


def _parse_json(value: Any, row: int, field: str, issues: list[ValidationIssue]) -> dict[str, Any]:
    if value in (None, ""):
        return {}
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(str(value))
        if not isinstance(parsed, dict):
            raise ValueError
        return parsed
    except Exception:
        issues.append(ValidationIssue(row, field, "INVALID_JSON", "data_json must contain a JSON object"))
        return {}


def _normalize_headers(headers: Iterable[str]) -> list[str]:
    return [str(h).strip().lower() for h in headers]


def parse_csv(payload: bytes, file_name: str = "bulk.csv") -> tuple[list[dict[str, Any]], str]:
    text = payload.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise ValueError("CSV has no header row")
    reader.fieldnames = _normalize_headers(reader.fieldnames)
    return [{str(k).strip().lower(): v for k, v in row.items()} for row in reader], _sha256_bytes(payload)


def parse_xlsx(payload: bytes, file_name: str = "bulk.xlsx") -> tuple[list[dict[str, Any]], str]:
    # Uses artifact_tool for XLSX reads so the ERP has one workbook abstraction.
    from artifact_tool import Blob, SpreadsheetFile
    path = Path("/tmp") / f"namkeen_v79_{uuid4().hex}.xlsx"
    path.write_bytes(payload)
    try:
        wb = SpreadsheetFile.import_xlsx(Blob.load(str(path)))
        sheets = wb.inspect({"kind": "sheet", "include": "id,name"})
        names = []
        for line in sheets.ndjson.splitlines():
            try:
                obj = json.loads(line)
                names.append(obj.get("name"))
            except Exception:
                pass
        sheet_name = names[0] if names else "Sheet1"
        table = wb.inspect({"kind": "table", "range": f"'{sheet_name}'!A1:Z10000", "include": "values", "table_max_rows": 10000, "table_max_cols": 26})
        rows = []
        for line in table.ndjson.splitlines():
            try:
                obj = json.loads(line)
                vals = obj.get("values")
                if vals:
                    rows.extend(vals)
            except Exception:
                continue
        if not rows:
            raise ValueError("XLSX has no data rows")
        headers = _normalize_headers(rows[0])
        return [dict(zip(headers, r + [None] * (len(headers) - len(r)))) for r in rows[1:] if any(x not in (None, "") for x in r)], _sha256_bytes(payload)
    finally:
        path.unlink(missing_ok=True)


def validate_rows(raw_rows: list[dict[str, Any]], content_sha256: str, file_name: str, organization_id: UUID) -> BulkPreview:
    preview = BulkPreview(file_name=file_name, content_sha256=content_sha256)
    seen_keys: set[str] = set()
    for idx, raw in enumerate(raw_rows, start=2):
        action = str(raw.get("action") or "").strip().upper()
        master_type = str(raw.get("master_type") or "").strip().upper()
        issues = preview.issues
        if action not in {"CREATE", "UPDATE", "DEACTIVATE"}:
            issues.append(ValidationIssue(idx, "action", "INVALID_ACTION", "Action must be CREATE, UPDATE or DEACTIVATE"))
        if master_type not in VALID_TYPES:
            issues.append(ValidationIssue(idx, "master_type", "INVALID_MASTER_TYPE", "Unsupported master_type"))
        mid = _parse_uuid(raw.get("master_id"), idx, "master_id", issues)
        eid = _parse_uuid(raw.get("entity_id"), idx, "entity_id", issues)
        eff_from = _parse_datetime(raw.get("effective_from"), idx, "effective_from", issues)
        eff_to = _parse_datetime(raw.get("effective_to"), idx, "effective_to", issues)
        if eff_to and eff_from and eff_to < eff_from:
            issues.append(ValidationIssue(idx, "effective_to", "INVALID_PERIOD", "effective_to cannot be before effective_from"))
        if master_type in EFFECTIVE_TYPES and action != "DEACTIVATE" and not eff_from:
            issues.append(ValidationIssue(idx, "effective_from", "REQUIRED", "effective_from is required for effective-dated masters"))
        if action in {"UPDATE", "DEACTIVATE"} and not mid:
            issues.append(ValidationIssue(idx, "master_id", "REQUIRED", "master_id is required for UPDATE/DEACTIVATE"))
        base = raw.get("base_version_no")
        base_version = None
        if base not in (None, ""):
            try:
                base_version = int(base)
            except Exception:
                issues.append(ValidationIssue(idx, "base_version_no", "INVALID_INTEGER", "base_version_no must be an integer"))
        data = _parse_json(raw.get("data_json"), idx, "data_json", issues)
        if not data and action != "DEACTIVATE":
            # allow column-oriented import as a convenience: all columns after control columns become data.
            control = {"action", "master_type", "master_id", "entity_id", "effective_from", "effective_to", "base_version_no", "data_json"}
            data = {k: v for k, v in raw.items() if k not in control and v not in (None, "")}
        if action == "DEACTIVATE" and not str(data.get("reason") or "").strip():
            issues.append(ValidationIssue(idx, "data_json", "REASON_REQUIRED", "Deactivation requires data_json.reason"))
        code = str(data.get("code") or data.get("sku") or data.get("gstin") or data.get("name") or "").strip().lower()
        dedupe_key = f"{master_type}|{eid or ''}|{code}"
        if code and dedupe_key in seen_keys:
            issues.append(ValidationIssue(idx, "data_json", "DUPLICATE_FILE_KEY", "Duplicate active master key within import file"))
        if code:
            seen_keys.add(dedupe_key)
        preview.rows.append(BulkRow(idx, action, master_type, mid, eid, eff_from, eff_to, base_version, data))
    return preview


def preview_bytes(payload: bytes, file_name: str, organization_id: UUID) -> BulkPreview:
    suffix = Path(file_name).suffix.lower()
    if suffix == ".csv":
        raw, digest = parse_csv(payload, file_name)
    elif suffix in {".xlsx", ".xlsm"}:
        raw, digest = parse_xlsx(payload, file_name)
    else:
        raise ValueError("Only CSV and XLSX/XLSM are supported")
    return validate_rows(raw, digest, file_name, organization_id)


def apply_preview(preview: BulkPreview, admin_service: Any, organization_id: UUID, requester_id: UUID, require_approval: bool = True) -> dict[str, Any]:
    if not preview.valid:
        raise ValueError("Bulk import contains validation errors")
    request_ids: list[UUID] = []
    for row in preview.rows:
        # Reuse the same audited master-change pathway as single-row administration.
        from app.v77.persistent_master import ChangeRequest
        req = ChangeRequest(
            organization_id=organization_id,
            master_type=row.master_type,
            action=row.action,
            requested_by=requester_id,
            payload=row.data,
            master_id=row.master_id,
            entity_id=row.entity_id,
            effective_from=row.effective_from,
            effective_to=row.effective_to,
            base_version_no=row.base_version_no,
            client_event_id=f"bulk:{preview.batch_id}:{row.row_number}",
        )
        request_ids.append(admin_service.request(req))
    return {"batch_id": str(preview.batch_id), "content_sha256": preview.content_sha256, "status": "PENDING_APPROVAL" if require_approval else "PENDING_APPROVAL", "request_ids": [str(x) for x in request_ids]}


def export_csv(rows: list[dict[str, Any]]) -> bytes:
    output = io.StringIO()
    fieldnames = ["master_id", "entity_id", "master_type", "version_no", "active", "effective_from", "effective_to", "data_json"]
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    for row in rows:
        writer.writerow({**row, "data_json": json.dumps(row.get("data_json") or {}, ensure_ascii=False, sort_keys=True)})
    return output.getvalue().encode("utf-8")


def make_xlsx_template(master_type: str, path: str | Path) -> None:
    from artifact_tool import SpreadsheetFile, Workbook
    if master_type not in VALID_TYPES:
        raise ValueError("Unsupported master type")
    wb = Workbook.create()
    sheet = wb.worksheets.add("Import")
    headers = [["action", "master_type", "master_id", "entity_id", "effective_from", "effective_to", "base_version_no", "data_json"]]
    examples = [["CREATE", master_type, "", "", "", "", "", '{"code":"EXAMPLE","name":"Replace me"}']]
    sheet.get_range("A1:H2").values = headers + examples
    sheet.get_range("A1:H1").format = {"fill": "#0F766E", "font": {"bold": True, "color": "#FFFFFF"}, "wrap_text": True}
    sheet.get_range("A1:H2").format.wrap_text = True
    sheet.get_range("A:H").format.column_width = 20
    sheet.get_range("H:H").format.column_width = 52
    sheet.freeze_panes.freeze_rows(1)
    table = sheet.tables.add("A1:H2", True, f"BulkImport_{master_type}")
    SpreadsheetFile.export_xlsx(wb).save(str(path))

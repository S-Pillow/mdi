"""
MDI CSV/XLSX upload parser.

Converts operator-supplied spreadsheet exports into normalized UploadedInputItem
objects, extracting domain, create date, EPP/domain status, registrar, and
assigned nameservers when present.

Pipeline:
  1. Detect file format from extension (csv / xlsx).
  2. Read all rows and locate the header row (may not be row 1).
  3. Map columns to canonical field names.
  4. For each data row:
     a. Extract domain value; skip row if missing.
     b. Normalize domain/URL through the existing input_parser rules.
     c. Deduplicate by normalized value.
     d. Extract optional metadata columns.
     e. Run offline hold detection against EPP / Domain State columns.
     f. Derive age_bucket from create date.
     g. Set preview triage fields for held rows.
  5. Return UploadParseResult (accepted, rejected, duplicates, columns_detected).

No network calls. No DNS resolution. No external APIs.
Uploaded file bytes are never persisted beyond this function call.
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from models import (
    AgeBucket,
    ColumnsDetected,
    DomainHold,
    DomainStatusSource,
    DuplicateItemResponse,
    EvidenceStatus,
    InputType,
    LiveStatus,
    MdiError,
    RecommendedAction,
    RejectedItemResponse,
    TriageBucket,
    TriageConfidence,
    UploadedInputItem,
    VtModeUsed,
)
from services.age_bucket import compute_age_bucket, parse_date_string
from services.hold_detection import detect_hold
from services.input_parser import MAX_TOKEN_LENGTH, map_parse_value_error, normalize_token


# ── Column detection ──────────────────────────────────────────────────────────

MAX_HEADER_SCAN_ROWS = 25

# Human-readable list for missing_domain_column errors.
DOMAIN_HEADER_HINT = (
    "DNS Form, Domain, Domain Name, Hostname, Host, URL, Target, Indicator"
)


def _canon_col(s: str) -> str:
    """Normalize a column header to a comparison key."""
    return re.sub(r'[^a-z0-9]', '', s.strip().lower())


# Map of canonical field name → set of normalized header keys that match it.
_COLUMN_MAP: Dict[str, frozenset] = {
    "domain":      frozenset({
        "domain", "dnsform", "domainname", "hostname", "host",
        "domainurl", "url", "target", "indicator",
    }),
    "created_at":  frozenset({
        "createdate", "created", "createdat", "registrationdate",
        "regdate", "domaincreated", "domaincreateddatetime",
        "registereddate", "registered",
    }),
    "epp_status":  frozenset({
        "eppstatus", "domainstatus", "status", "domainstatuses",
        "eppstatuses", "registrystatus", "registrarstatus",
    }),
    "domain_state": frozenset({
        "domainstate",
    }),
    "registrar":   frozenset({
        "registrar", "registrarname", "registrarid",
        "sponsoringregistrar",
    }),
    "nameservers": frozenset({
        "assignednameservers", "nameservers", "ns",
        "nameserver", "dnsservers", "dnsserver",
    }),
}

OPTIONAL_COLUMNS = {"created_at", "epp_status", "domain_state", "registrar", "nameservers"}


def _detect_columns(headers: List[str]) -> Tuple[ColumnsDetected, Dict[str, int], List[str]]:
    """
    Map raw header names to canonical field indices.

    Returns:
        columns_detected:  ColumnsDetected model showing which header matched each field.
        col_index:         canonical_field → 0-based column index in the row.
        missing_optional:  Canonical optional fields with no matching header.
    """
    col_index: Dict[str, int] = {}
    detected_headers: Dict[str, str] = {}

    for idx, raw_header in enumerate(headers):
        key = _canon_col(raw_header)
        for canonical, patterns in _COLUMN_MAP.items():
            if canonical not in col_index and key in patterns:
                col_index[canonical] = idx
                detected_headers[canonical] = raw_header
                break

    missing_optional = [f for f in OPTIONAL_COLUMNS if f not in col_index]

    return (
        ColumnsDetected(
            domain=detected_headers.get("domain"),
            created_at=detected_headers.get("created_at"),
            epp_status=detected_headers.get("epp_status"),
            domain_state=detected_headers.get("domain_state"),
            registrar=detected_headers.get("registrar"),
            nameservers=detected_headers.get("nameservers"),
        ),
        col_index,
        missing_optional,
    )


# ── Nameserver splitting ──────────────────────────────────────────────────────

_NS_SPLIT_RE = re.compile(r'[,;\s\n\r]+')


def _split_nameservers(raw: str) -> List[str]:
    return [n.lower().rstrip('.') for n in _NS_SPLIT_RE.split(raw.strip()) if n.strip()]


# ── Error helpers ─────────────────────────────────────────────────────────────

def _make_error(code: str, message: str) -> MdiError:
    from services.error_taxonomy import make_mdi_error

    return make_mdi_error(code=code, message=message, source="upload_parser", retriable=False)


# ── Output structures ─────────────────────────────────────────────────────────

@dataclass
class UploadParseResult:
    accepted: List[UploadedInputItem] = field(default_factory=list)
    rejected: List[RejectedItemResponse] = field(default_factory=list)
    duplicates: List[DuplicateItemResponse] = field(default_factory=list)
    columns_detected: ColumnsDetected = field(default_factory=ColumnsDetected)
    missing_optional_columns: List[str] = field(default_factory=list)
    header_row: Optional[int] = None          # 1-based row number of detected header
    source_sheet: Optional[str] = None        # active worksheet name for XLSX


# ── Row / header helpers ──────────────────────────────────────────────────────

def _normalize_row(row) -> List[str]:
    return [str(c) if c is not None else "" for c in row]


def _is_comment_or_blank_row(row: List[str]) -> bool:
    if not row:
        return True
    if all(not str(c).strip() for c in row):
        return True
    first = str(row[0]).strip()
    return first.startswith("#")


def _find_header_row(all_rows: List[List[str]]) -> Optional[int]:
    """Return 0-based index of the best header row, or None if not found."""
    best_idx: Optional[int] = None
    best_score = -1
    scan_limit = min(len(all_rows), MAX_HEADER_SCAN_ROWS)
    for idx in range(scan_limit):
        row = _normalize_row(all_rows[idx])
        if _is_comment_or_blank_row(row):
            continue
        _, col_index, _ = _detect_columns(row)
        if "domain" not in col_index:
            continue
        score = len(col_index)
        if score > best_score:
            best_score = score
            best_idx = idx
    return best_idx


def _combine_status_fields(raw_epp: Optional[str], raw_domain_state: Optional[str]) -> Optional[str]:
    parts = [p.strip() for p in (raw_epp, raw_domain_state) if p and p.strip()]
    if not parts:
        return None
    return " ".join(parts)


def _held_upload_preview_fields(domain_hold: DomainHold) -> dict:
    """Preview/triage field updates when uploaded metadata confirms a hold."""
    return {
        "triage_bucket": TriageBucket.HELD,
        "recommended_action": RecommendedAction.ACTION_ALREADY_TAKEN,
        "triage_confidence": TriageConfidence.HIGH,
        "evidence_status": EvidenceStatus.SKIPPED_HOLD,
        "vt_mode_used": VtModeUsed.SKIPPED_HOLD,
        "live_status": LiveStatus.NOT_CHECKED,
        "domain_hold": domain_hold,
        "domain_status_source": DomainStatusSource.UPLOADED_FILE,
    }


def _merge_epp_status(existing: List[str], incoming: List[str]) -> List[str]:
    merged: List[str] = []
    seen: set[str] = set()
    for token in [*existing, *incoming]:
        key = token.lower()
        if key not in seen:
            seen.add(key)
            merged.append(token)
    return merged


def _upgrade_accepted_item_hold(
    existing: UploadedInputItem,
    *,
    domain_hold: DomainHold,
    epp_list: List[str],
) -> UploadedInputItem:
    """Promote a deduped accepted row to held when a duplicate row carries hold metadata."""
    if existing.domain_hold.has_hold:
        return existing
    return existing.model_copy(update={
        **_held_upload_preview_fields(domain_hold),
        "epp_status": _merge_epp_status(existing.epp_status, epp_list),
    })


# ── Row processing ────────────────────────────────────────────────────────────

def _process_row(
    row: List[str],
    row_number: int,
    col_index: Dict[str, int],
    default_scheme: str,
    seen_normalized: dict,
    result: UploadParseResult,
    max_items: int,
    *,
    source_sheet: Optional[str] = None,
) -> None:
    """Process a single data row in-place."""

    def _get(field_name: str) -> Optional[str]:
        idx = col_index.get(field_name)
        if idx is None or idx >= len(row):
            return None
        val = row[idx]
        return val.strip() if val and val.strip() else None

    if _is_comment_or_blank_row(row):
        return

    raw_domain = _get("domain")
    if not raw_domain:
        if any(cell.strip() for cell in row):
            result.rejected.append(RejectedItemResponse(
                input_original=str(row),
                position=row_number,
                error=_make_error("missing_domain", f"Row {row_number}: no value in domain column."),
            ))
        return

    if len(result.accepted) >= max_items:
        result.rejected.append(RejectedItemResponse(
            input_original=raw_domain,
            position=row_number,
            error=_make_error(
                "max_items_exceeded",
                f"Batch limit of {max_items} reached.",
            ),
        ))
        return

    try:
        normalized, input_type = normalize_token(raw_domain, default_scheme)
    except ValueError as exc:
        code, msg = map_parse_value_error(raw_domain, str(exc))
        result.rejected.append(RejectedItemResponse(
            input_original=raw_domain,
            position=row_number,
            error=_make_error(code, msg),
        ))
        return

    raw_created = _get("created_at")
    raw_status = _combine_status_fields(_get("epp_status"), _get("domain_state"))
    raw_registrar = _get("registrar")
    raw_ns = _get("nameservers")

    epp_list: List[str] = []
    if raw_status:
        from services.hold_detection import _split_status_tokens
        epp_list = _split_status_tokens(raw_status)

    ns_list = _split_nameservers(raw_ns) if raw_ns else []

    domain_hold = detect_hold(
        raw_status,
        source=DomainStatusSource.UPLOADED_FILE if raw_status else DomainStatusSource.NOT_CHECKED,
    )

    if normalized in seen_normalized:
        result.duplicates.append(DuplicateItemResponse(
            input_original=raw_domain,
            position=row_number,
            duplicate_of=normalized,
        ))
        if domain_hold.has_hold:
            idx = seen_normalized[normalized] - 1
            result.accepted[idx] = _upgrade_accepted_item_hold(
                result.accepted[idx],
                domain_hold=domain_hold,
                epp_list=epp_list,
            )
        return

    age_bucket = AgeBucket.UNKNOWN
    if raw_created:
        parsed_date = parse_date_string(raw_created)
        if parsed_date:
            age_bucket = compute_age_bucket(parsed_date)

    if domain_hold.has_hold:
        held_fields = _held_upload_preview_fields(domain_hold)
        triage_bucket = held_fields["triage_bucket"]
        recommended_action = held_fields["recommended_action"]
        triage_confidence = held_fields["triage_confidence"]
        evidence_status = held_fields["evidence_status"]
        vt_mode_used = held_fields["vt_mode_used"]
        live_status = held_fields["live_status"]
    else:
        triage_bucket      = TriageBucket.PENDING
        recommended_action = RecommendedAction.NONE
        triage_confidence  = TriageConfidence.UNKNOWN
        evidence_status    = EvidenceStatus.NONE
        vt_mode_used       = VtModeUsed.NOT_CHECKED
        live_status        = LiveStatus.NOT_CHECKED

    seen_normalized[normalized] = len(result.accepted) + 1
    item = UploadedInputItem(
        input_original=raw_domain,
        input_normalized=normalized,
        input_type=input_type,
        position=seen_normalized[normalized],
        created_at=raw_created,
        registrar=raw_registrar,
        epp_status=epp_list,
        assigned_nameservers=ns_list,
        domain_hold=domain_hold,
        domain_status_source=DomainStatusSource.UPLOADED_FILE if raw_status else DomainStatusSource.NOT_CHECKED,
        age_bucket=age_bucket,
        triage_bucket=triage_bucket,
        recommended_action=recommended_action,
        triage_confidence=triage_confidence,
        evidence_status=evidence_status,
        vt_mode_used=vt_mode_used,
        live_status=live_status,
        source_row=row_number,
        source_sheet=source_sheet,
    )
    result.accepted.append(item)


# ── Format-specific readers ───────────────────────────────────────────────────

def _read_all_rows_csv(file_bytes: bytes) -> List[List[str]]:
    text = file_bytes.decode("utf-8-sig", errors="replace")
    reader = csv.reader(io.StringIO(text))
    return [_normalize_row(row) for row in reader]


def _read_all_rows_xlsx(file_bytes: bytes) -> Tuple[List[List[str]], str]:
    import openpyxl
    wb = openpyxl.load_workbook(
        io.BytesIO(file_bytes),
        read_only=True,
        data_only=True,
    )
    ws = wb.active
    sheet_name = ws.title
    rows = [_normalize_row(row) for row in ws.iter_rows(values_only=True)]
    wb.close()
    return rows, sheet_name


# ── Public API ────────────────────────────────────────────────────────────────

MAX_FILE_BYTES = 10 * 1024 * 1024   # 10 MB hard cap


def parse_upload(
    file_bytes: bytes,
    filename: str,
    *,
    default_scheme: str = "http",
    max_items: int = 500,
) -> UploadParseResult:
    """
    Parse a CSV or XLSX upload into normalized UploadedInputItem objects.

    Args:
        file_bytes:     Raw file content. Never written to disk.
        filename:       Original filename (used to detect format by extension).
        default_scheme: Scheme prepended to domain/path tokens without one.
        max_items:      Maximum accepted items.

    Returns:
        UploadParseResult with accepted, rejected, duplicates, and column metadata.

    No network calls. No DNS. No external APIs.
    """
    result = UploadParseResult()

    if len(file_bytes) > MAX_FILE_BYTES:
        result.rejected.append(RejectedItemResponse(
            input_original=filename,
            position=0,
            error=_make_error(
                "file_too_large",
                f"File exceeds {MAX_FILE_BYTES // (1024 * 1024)} MB limit.",
            ),
        ))
        return result

    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    source_sheet: Optional[str] = None

    if ext == "csv":
        try:
            all_rows = _read_all_rows_csv(file_bytes)
        except Exception as exc:
            result.rejected.append(RejectedItemResponse(
                input_original=filename,
                position=0,
                error=_make_error("parse_error", f"CSV parse failed: {exc}"),
            ))
            return result
    elif ext in {"xlsx", "xlsm"}:
        try:
            all_rows, source_sheet = _read_all_rows_xlsx(file_bytes)
        except Exception as exc:
            result.rejected.append(RejectedItemResponse(
                input_original=filename,
                position=0,
                error=_make_error("parse_error", f"XLSX parse failed: {exc}"),
            ))
            return result
    elif ext == "xls":
        result.rejected.append(RejectedItemResponse(
            input_original=filename,
            position=0,
            error=_make_error(
                "unsupported_format",
                "Legacy Excel .xls is not supported. Save the file as .xlsx or export as CSV.",
            ),
        ))
        return result
    else:
        result.rejected.append(RejectedItemResponse(
            input_original=filename,
            position=0,
            error=_make_error(
                "unsupported_format",
                f"Unsupported file type '.{ext}'. Only CSV and XLSX files are accepted.",
            ),
        ))
        return result

    result.source_sheet = source_sheet

    if not all_rows:
        result.rejected.append(RejectedItemResponse(
            input_original=filename,
            position=0,
            error=_make_error("empty_file", "File has no rows."),
        ))
        return result

    header_idx = _find_header_row(all_rows)
    if header_idx is None:
        result.rejected.append(RejectedItemResponse(
            input_original=filename,
            position=0,
            error=_make_error(
                "missing_domain_column",
                f"No domain column found. Expected a header row containing one of: {DOMAIN_HEADER_HINT}.",
            ),
        ))
        return result

    headers = _normalize_row(all_rows[header_idx])
    result.header_row = header_idx + 1

    columns_detected, col_index, missing_optional = _detect_columns(headers)
    result.columns_detected = columns_detected
    result.missing_optional_columns = missing_optional

    if "domain" not in col_index:
        result.rejected.append(RejectedItemResponse(
            input_original=filename,
            position=0,
            error=_make_error(
                "missing_domain_column",
                f"No domain column found. Expected a header row containing one of: {DOMAIN_HEADER_HINT}.",
            ),
        ))
        return result

    seen_normalized: dict = {}
    data_rows = all_rows[header_idx + 1:]

    for data_idx, row in enumerate(data_rows):
        row_number = header_idx + data_idx + 2   # 1-based file row number
        _process_row(
            row=row,
            row_number=row_number,
            col_index=col_index,
            default_scheme=default_scheme,
            seen_normalized=seen_normalized,
            result=result,
            max_items=max_items,
            source_sheet=source_sheet,
        )

    return result

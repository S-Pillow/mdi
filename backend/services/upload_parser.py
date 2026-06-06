"""
MDI CSV/XLSX upload parser.

Converts operator-supplied spreadsheet exports into normalized UploadedInputItem
objects, extracting domain, create date, EPP/domain status, registrar, and
assigned nameservers when present.

Pipeline:
  1. Detect file format from extension (csv / xlsx).
  2. Read header row and map columns to canonical field names.
  3. For each data row:
     a. Extract domain value; skip row if missing.
     b. Normalize domain/URL through the existing input_parser rules.
     c. Deduplicate by normalized value.
     d. Extract optional metadata columns.
     e. Run offline hold detection against EPP status.
     f. Derive age_bucket from create date.
     g. Set preview triage fields for held rows.
  4. Return UploadParseResult (accepted, rejected, duplicates, columns_detected).

No network calls. No DNS resolution. No external APIs.
Uploaded file bytes are never persisted beyond this function call.
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
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
from services.hold_detection import detect_hold
from services.input_parser import MAX_TOKEN_LENGTH, normalize_token


# ── Column detection ──────────────────────────────────────────────────────────

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
    "registrar":   frozenset({
        "registrar", "registrarname", "registrarid",
        "sponsoringregistrar",
    }),
    "nameservers": frozenset({
        "assignednameservers", "nameservers", "ns",
        "nameserver", "dnsservers", "dnsserver",
    }),
}

OPTIONAL_COLUMNS = {"created_at", "epp_status", "registrar", "nameservers"}


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
            registrar=detected_headers.get("registrar"),
            nameservers=detected_headers.get("nameservers"),
        ),
        col_index,
        missing_optional,
    )


# ── Date parsing and age bucket ───────────────────────────────────────────────

_DATE_FORMATS = [
    "%Y-%m-%d", "%Y/%m/%d", "%m/%d/%Y", "%d/%m/%Y",
    "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S.%fZ",
    "%B %d, %Y", "%b %d, %Y", "%d %B %Y", "%d %b %Y",
    "%Y.%m.%d",
]


def _parse_date(s: str) -> Optional[date]:
    """Try known date formats; return None if none match."""
    s = s.strip()
    # Try truncating to date portion if long (e.g. "2021-03-15T00:00:00Z")
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    # Last-ditch: try just the first 10 chars as YYYY-MM-DD
    if len(s) >= 10:
        try:
            return datetime.strptime(s[:10], "%Y-%m-%d").date()
        except ValueError:
            pass
    return None


def _age_bucket(d: date) -> AgeBucket:
    today = date.today()
    delta = (today - d).days
    if delta < 0:
        return AgeBucket.UNKNOWN      # future date — data error
    if delta < 30:
        return AgeBucket.VERY_NEW
    if delta < 180:
        return AgeBucket.NEW
    if delta < 730:
        return AgeBucket.ESTABLISHED
    return AgeBucket.MATURE


# ── Nameserver splitting ──────────────────────────────────────────────────────

_NS_SPLIT_RE = re.compile(r'[,;\s\n\r]+')


def _split_nameservers(raw: str) -> List[str]:
    return [n.lower().rstrip('.') for n in _NS_SPLIT_RE.split(raw.strip()) if n.strip()]


# ── Error helpers ─────────────────────────────────────────────────────────────

def _make_error(code: str, message: str) -> MdiError:
    return MdiError(code=code, message=message, source="upload_parser", retriable=False)


# ── Output structures ─────────────────────────────────────────────────────────

@dataclass
class UploadParseResult:
    accepted: List[UploadedInputItem] = field(default_factory=list)
    rejected: List[RejectedItemResponse] = field(default_factory=list)
    duplicates: List[DuplicateItemResponse] = field(default_factory=list)
    columns_detected: ColumnsDetected = field(default_factory=ColumnsDetected)
    missing_optional_columns: List[str] = field(default_factory=list)


# ── Row processing ────────────────────────────────────────────────────────────

def _process_row(
    row: List[str],
    row_number: int,
    col_index: Dict[str, int],
    default_scheme: str,
    seen_normalized: dict,
    result: UploadParseResult,
    max_items: int,
) -> None:
    """Process a single data row in-place."""

    def _get(field_name: str) -> Optional[str]:
        idx = col_index.get(field_name)
        if idx is None or idx >= len(row):
            return None
        val = row[idx]
        return val.strip() if val and val.strip() else None

    # ── Require domain column ────────────────────────────────────────────────
    raw_domain = _get("domain")
    if not raw_domain:
        # Row may be entirely empty — skip silently; or partial — reject with error
        if any(cell.strip() for cell in row):
            result.rejected.append(RejectedItemResponse(
                input_original=str(row),
                position=row_number,
                error=_make_error("missing_domain", f"Row {row_number}: no value in domain column."),
            ))
        return

    # ── Normalize via input_parser ───────────────────────────────────────────
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
        code_str = str(exc)
        if code_str.startswith("unsupported_scheme:"):
            scheme = code_str.split(":", 1)[1]
            msg = f"Unsupported scheme '{scheme}'. Only http and https are accepted."
            code = "unsupported_scheme"
        elif code_str == "token_too_long":
            msg = f"Value exceeds {MAX_TOKEN_LENGTH} character limit."
            code = "token_too_long"
        elif code_str == "token_contains_space":
            msg = f"'{raw_domain}' contains a space and cannot be parsed as a domain or URL."
            code = "invalid_input"
        elif code_str.startswith("invalid_domain"):
            msg = f"'{raw_domain}' does not appear to be a valid domain or URL."
            code = "invalid_input"
        else:
            msg = f"Could not parse '{raw_domain}': {code_str}."
            code = "invalid_input"
        result.rejected.append(RejectedItemResponse(
            input_original=raw_domain,
            position=row_number,
            error=_make_error(code, msg),
        ))
        return

    # ── Deduplication ────────────────────────────────────────────────────────
    if normalized in seen_normalized:
        result.duplicates.append(DuplicateItemResponse(
            input_original=raw_domain,
            position=row_number,
            duplicate_of=normalized,
        ))
        return

    # ── Extract optional metadata ────────────────────────────────────────────
    raw_created  = _get("created_at")
    raw_epp      = _get("epp_status")
    raw_registrar = _get("registrar")
    raw_ns       = _get("nameservers")

    epp_list: List[str] = []
    if raw_epp:
        # Re-use hold detection token splitter for consistent splitting
        from services.hold_detection import _split_status_tokens
        epp_list = _split_status_tokens(raw_epp)

    ns_list = _split_nameservers(raw_ns) if raw_ns else []

    # ── Hold detection ───────────────────────────────────────────────────────
    domain_hold = detect_hold(
        raw_epp,
        source=DomainStatusSource.UPLOADED_FILE,
    )

    # ── Age bucket ───────────────────────────────────────────────────────────
    age_bucket = AgeBucket.UNKNOWN
    if raw_created:
        parsed_date = _parse_date(raw_created)
        if parsed_date:
            age_bucket = _age_bucket(parsed_date)

    # ── Preview triage fields for held items ─────────────────────────────────
    if domain_hold.has_hold:
        triage_bucket      = TriageBucket.HELD
        recommended_action = RecommendedAction.ACTION_ALREADY_TAKEN
        triage_confidence  = TriageConfidence.HIGH
        evidence_status    = EvidenceStatus.SKIPPED_HOLD
        vt_mode_used       = VtModeUsed.SKIPPED_HOLD
        live_status        = LiveStatus.NOT_CHECKED
    else:
        triage_bucket      = TriageBucket.PENDING
        recommended_action = RecommendedAction.NONE
        triage_confidence  = TriageConfidence.UNKNOWN
        evidence_status    = EvidenceStatus.NONE
        vt_mode_used       = VtModeUsed.NOT_CHECKED
        live_status        = LiveStatus.NOT_CHECKED

    # ── Accept ───────────────────────────────────────────────────────────────
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
        domain_status_source=DomainStatusSource.UPLOADED_FILE,
        age_bucket=age_bucket,
        triage_bucket=triage_bucket,
        recommended_action=recommended_action,
        triage_confidence=triage_confidence,
        evidence_status=evidence_status,
        vt_mode_used=vt_mode_used,
        live_status=live_status,
    )
    result.accepted.append(item)


# ── Format-specific readers ───────────────────────────────────────────────────

def _iter_rows_csv(file_bytes: bytes) -> Tuple[List[str], List[List[str]]]:
    """
    Parse CSV bytes, return (headers, data_rows).
    Uses Python stdlib csv — no external dependency.
    """
    text = file_bytes.decode("utf-8-sig", errors="replace")
    reader = csv.reader(io.StringIO(text))
    rows = list(reader)
    if not rows:
        return [], []
    headers = rows[0]
    return headers, rows[1:]


def _iter_rows_xlsx(file_bytes: bytes) -> Tuple[List[str], List[List[str]]]:
    """
    Parse XLSX bytes, return (headers, data_rows).
    Uses openpyxl — added to requirements.txt.
    """
    import openpyxl
    wb = openpyxl.load_workbook(
        io.BytesIO(file_bytes),
        read_only=True,
        data_only=True,
    )
    ws = wb.active
    rows_iter = ws.iter_rows(values_only=True)

    header_row = next(rows_iter, None)
    if header_row is None:
        return [], []

    headers = [str(cell) if cell is not None else "" for cell in header_row]

    data_rows: List[List[str]] = []
    for row in rows_iter:
        data_rows.append([str(cell) if cell is not None else "" for cell in row])

    wb.close()
    return headers, data_rows


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

    if ext == "csv":
        try:
            headers, data_rows = _iter_rows_csv(file_bytes)
        except Exception as exc:
            result.rejected.append(RejectedItemResponse(
                input_original=filename,
                position=0,
                error=_make_error("parse_error", f"CSV parse failed: {exc}"),
            ))
            return result
    elif ext in {"xlsx", "xlsm", "xls"}:
        try:
            headers, data_rows = _iter_rows_xlsx(file_bytes)
        except Exception as exc:
            result.rejected.append(RejectedItemResponse(
                input_original=filename,
                position=0,
                error=_make_error("parse_error", f"XLSX parse failed: {exc}"),
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

    if not headers:
        result.rejected.append(RejectedItemResponse(
            input_original=filename,
            position=0,
            error=_make_error("empty_file", "File has no header row."),
        ))
        return result

    columns_detected, col_index, missing_optional = _detect_columns(headers)
    result.columns_detected = columns_detected
    result.missing_optional_columns = missing_optional

    if "domain" not in col_index:
        result.rejected.append(RejectedItemResponse(
            input_original=filename,
            position=0,
            error=_make_error(
                "missing_domain_column",
                "No domain column found. Expected one of: Domain, DNS Form, domain, dns_form.",
            ),
        ))
        return result

    seen_normalized: dict = {}

    for row_idx, row in enumerate(data_rows, start=2):   # row 1 = header
        _process_row(
            row=[str(c) for c in row],
            row_number=row_idx,
            col_index=col_index,
            default_scheme=default_scheme,
            seen_normalized=seen_normalized,
            result=result,
            max_items=max_items,
        )

    return result

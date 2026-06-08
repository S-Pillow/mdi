"""
Derive public VirusTotal GUI report URLs from saved MDI result fields.

No VT API calls. No quota impact. Browser navigation only.
"""

from __future__ import annotations

import base64
import re
from typing import Optional, TYPE_CHECKING

from models import InputType, VtModeUsed

if TYPE_CHECKING:
    from models import MdiResultItem

VT_GUI_BASE = "https://www.virustotal.com/gui"
_DOMAIN_LABEL_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$", re.IGNORECASE)


def _vt_url_id(url: str) -> str:
    """Base64url-encode a URL (no padding) — standard VT GUI URL id."""
    return base64.urlsafe_b64encode(url.encode()).decode().strip("=")


def _is_plausible_domain(domain: str) -> bool:
    domain = (domain or "").strip().lower().rstrip(".")
    if not domain or " " in domain or "/" in domain or "://" in domain:
        return False
    if len(domain) > 253 or "." not in domain:
        return False
    labels = domain.split(".")
    return all(_DOMAIN_LABEL_RE.match(label) for label in labels if label)


def _vt_report_was_retrieved(
    vt_scan_date,
    vt_total_engines: Optional[int],
    vt_hits: Optional[int],
    vt_suspicious: Optional[int],
) -> bool:
    if vt_scan_date is not None:
        return True
    if vt_total_engines is not None:
        return True
    if vt_hits is not None or vt_suspicious is not None:
        return True
    return False


def vt_gui_report_url_for_item(item: "MdiResultItem") -> Optional[str]:
    """
    Build a safe VT GUI URL from persisted row data, or None when unavailable.

    Domain report rows → /gui/domain/{domain}
    URL report rows → /gui/url/{base64url(url)} using the same target URL MDI queried
    """
    mode = item.vt_mode_used
    if mode not in (VtModeUsed.URL_REPORT, VtModeUsed.DOMAIN_REPORT):
        return None

    if not _vt_report_was_retrieved(
        item.vt_scan_date,
        item.vt_total_engines,
        item.vt_hits,
        item.vt_suspicious,
    ):
        return None

    normalized = (item.input_normalized or "").strip()
    if not normalized:
        return None

    if mode == VtModeUsed.DOMAIN_REPORT:
        domain = normalized.lower().rstrip(".")
        if not _is_plausible_domain(domain):
            return None
        return f"{VT_GUI_BASE}/domain/{domain}"

    # URL report mode — link only from the normalized URL target MDI used for VT
    if item.input_type == InputType.URL:
        url_target = normalized
    else:
        url_target = f"http://{normalized.lower().rstrip('.')}/"

    if not url_target.startswith(("http://", "https://")):
        return None

    return f"{VT_GUI_BASE}/url/{_vt_url_id(url_target)}"


"""
MDI-69C — hold_detection unit tests.

Pure local tests; no network, no runtime files.
"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from models import DomainHoldType, DomainStatusSource
from services.hold_detection import (
    detect_hold,
    detect_hold_from_epp_statuses,
    hold_type_display,
)


class TestDetectHoldCamelCase:
    def test_client_hold(self):
        dh = detect_hold("clientHold")
        assert dh.has_hold is True
        assert DomainHoldType.CLIENT_HOLD in dh.hold_types

    def test_server_hold(self):
        dh = detect_hold("serverHold")
        assert dh.has_hold is True
        assert DomainHoldType.SERVER_HOLD in dh.hold_types


class TestDetectHoldSpacedVariants:
    @pytest.mark.parametrize("status", [
        "client hold",
        "Client Hold",
        "CLIENT HOLD",
        "client hold https://icann.org/epp#clientHold",
    ])
    def test_client_hold_spaced(self, status):
        dh = detect_hold(status)
        assert dh.has_hold is True
        assert DomainHoldType.CLIENT_HOLD in dh.hold_types
        assert DomainHoldType.SERVER_HOLD not in dh.hold_types

    @pytest.mark.parametrize("status", [
        "server hold",
        "Server HOLD",
        "server hold https://icann.org/epp#serverHold",
    ])
    def test_server_hold_spaced(self, status):
        dh = detect_hold(status)
        assert dh.has_hold is True
        assert DomainHoldType.SERVER_HOLD in dh.hold_types

    def test_ap_exdex_vip_rdap_status_list(self):
        statuses = [
            "client transfer prohibited",
            "client hold",
            "server transfer prohibited",
            "inactive",
        ]
        dh = detect_hold_from_epp_statuses(statuses, source=DomainStatusSource.RDAP)
        assert dh.has_hold is True
        assert DomainHoldType.CLIENT_HOLD in dh.hold_types
        assert DomainHoldType.SERVER_HOLD not in dh.hold_types
        assert dh.source == DomainStatusSource.RDAP
        assert statuses == dh.raw_statuses


class TestDetectHoldNegative:
    @pytest.mark.parametrize("status", [
        "client transfer prohibited",
        "server transfer prohibited",
        "inactive",
        "pending transfer",
        "hold",
        "clientTransferProhibited clientDeleteProhibited",
    ])
    def test_not_hold(self, status):
        dh = detect_hold(status)
        assert dh.has_hold is False

    def test_transfer_prohibited_list_no_hold(self):
        statuses = [
            "client transfer prohibited",
            "server transfer prohibited",
            "inactive",
        ]
        dh = detect_hold_from_epp_statuses(statuses, source=DomainStatusSource.RDAP)
        assert dh.has_hold is False


class TestDetectHoldFromEppStatuses:
    def test_server_hold_list(self):
        dh = detect_hold_from_epp_statuses(["server hold"], source=DomainStatusSource.RDAP)
        assert dh.has_hold is True
        assert DomainHoldType.SERVER_HOLD in dh.hold_types

    def test_camel_case_list_still_works(self):
        dh = detect_hold_from_epp_statuses(
            ["clientHold", "clientTransferProhibited"],
            source=DomainStatusSource.RDAP,
        )
        assert dh.has_hold is True
        assert DomainHoldType.CLIENT_HOLD in dh.hold_types

    def test_empty_list(self):
        dh = detect_hold_from_epp_statuses([])
        assert dh.has_hold is False
        assert dh.source == DomainStatusSource.NOT_CHECKED


class TestHoldDisplay:
    def test_display_both(self):
        dh = detect_hold("clientHold serverHold")
        assert hold_type_display(dh) == "clientHold + serverHold"

    def test_display_unknown(self):
        assert hold_type_display(detect_hold(None)) == "unknown"

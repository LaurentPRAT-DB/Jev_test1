"""Offline unit tests for the SLA routing logic. No API, no credit.

Proves the core property: the SAME probability routes to DIFFERENT verdicts
depending on SLA tier.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from router import load_config, route

CFG = load_config()


def test_same_p_routes_differently_by_sla():
    p = 0.55  # one content-only probability
    assert route("enterprise", p, CFG)[0] == "CRITICAL"   # 0.55 >= 0.30
    assert route("business", p, CFG)[0] == "CRITICAL"     # 0.55 >= 0.50
    assert route("free", p, CFG)[0] == "REVIEW"           # 0.55 < 0.80, >= 0.50


def test_boundaries():
    # free tier: critical at 0.80, review at 0.50
    assert route("free", 0.80, CFG)[0] == "CRITICAL"
    assert route("free", 0.79, CFG)[0] == "REVIEW"
    assert route("free", 0.49, CFG)[0] == "ROUTINE"


def test_enterprise_escalates_weak_signal():
    # a weak signal that is ROUTINE on free is already REVIEW/CRITICAL on enterprise
    p = 0.20
    assert route("free", p, CFG)[0] == "ROUTINE"
    assert route("enterprise", p, CFG)[0] == "REVIEW"     # 0.20 >= 0.15


def test_unknown_sla_raises():
    import pytest
    with pytest.raises(KeyError):
        route("platinum", 0.5, CFG)

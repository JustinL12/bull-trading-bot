"""Tests for scripts/place_order.py sell-side reconciliation guards.

These cover the fix for the 2026-06-04 MPC incident: a protective stop self-filled
but was never reconciled into positions.json, so the EOD "close" sold shares the
account no longer held and opened an unintended short.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from place_order import plan_sell_qty


def test_plan_sell_qty_normal_full_close():
    # Broker holds exactly what we think we hold: sell all of it.
    assert plan_sell_qty(18, 18) == 18


def test_plan_sell_qty_clamps_to_broker_held():
    # We think we hold 18 but the broker only has 10 (e.g. a partial stop fill):
    # never sell more than the broker actually holds.
    assert plan_sell_qty(18, 10) == 10


def test_plan_sell_qty_flat_book_returns_zero():
    # The core MPC bug: broker is flat (stop already self-filled). Selling our
    # recorded 18 would open a short, so the plan must be to sell nothing.
    assert plan_sell_qty(18, 0) == 0


def test_plan_sell_qty_never_shorts_on_existing_short():
    # If we are somehow already short, do not sell further.
    assert plan_sell_qty(18, -18) == 0


def test_plan_sell_qty_partial_within_holding():
    # Partial sell smaller than holdings passes through unchanged.
    assert plan_sell_qty(9, 18) == 9


def test_plan_sell_qty_never_negative():
    assert plan_sell_qty(0, 18) == 0
    assert plan_sell_qty(-5, 18) == 0

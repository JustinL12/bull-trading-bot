"""Tests for lib/memory.py"""

import json
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from lib.memory import (
    _rsi_bucket,
    _rel_vol_bucket,
    _increment_bucket,
    build_insights_from_stats,
)


def test_rsi_bucket():
    assert _rsi_bucket(51) == "50-55"
    assert _rsi_bucket(57) == "55-60"
    assert _rsi_bucket(62) == "60-65"
    assert _rsi_bucket(70) == "65-75"
    assert _rsi_bucket(75) == "65-75"


def test_rel_vol_bucket():
    assert _rel_vol_bucket(1.6) == "1.5-2.0"
    assert _rel_vol_bucket(2.5) == "2.0-3.0"
    assert _rel_vol_bucket(3.5) == "3.0+"


def test_increment_bucket_first_entry():
    stats = {}
    _increment_bucket(stats, ["rsi", "50-55"], won=True, pnl_pct=1.5)
    assert stats["rsi"]["50-55"]["trades"] == 1
    assert stats["rsi"]["50-55"]["wins"] == 1
    assert stats["rsi"]["50-55"]["win_rate"] == 1.0


def test_increment_bucket_accumulates():
    stats = {}
    _increment_bucket(stats, ["rsi", "65-75"], won=True, pnl_pct=1.0)
    _increment_bucket(stats, ["rsi", "65-75"], won=False, pnl_pct=-0.5)
    _increment_bucket(stats, ["rsi", "65-75"], won=False, pnl_pct=-0.5)
    entry = stats["rsi"]["65-75"]
    assert entry["trades"] == 3
    assert entry["wins"] == 1
    assert abs(entry["win_rate"] - 1/3) < 0.01


def test_increment_avg_pnl():
    stats = {}
    _increment_bucket(stats, ["rsi", "50-55"], won=True, pnl_pct=2.0)
    _increment_bucket(stats, ["rsi", "50-55"], won=True, pnl_pct=1.0)
    avg = stats["rsi"]["50-55"]["avg_pnl_pct"]
    assert abs(avg - 1.5) < 0.01


def test_build_insights_no_data():
    stats = {"total_trades": 0, "by_signal": {}}
    best, avoid, adj = build_insights_from_stats(stats)
    assert best == []
    assert avoid == []


def test_build_insights_finds_avoid():
    stats = {
        "total_trades": 50,
        "by_signal": {
            "rsi_at_entry": {
                "50-55": {"trades": 15, "wins": 13, "win_rate": 0.87, "avg_pnl_pct": 1.2},
                "65-75": {"trades": 12, "wins": 4, "win_rate": 0.33, "avg_pnl_pct": -0.4},
            }
        }
    }
    best, avoid, adj = build_insights_from_stats(stats)
    assert any("65-75" in a for a in avoid)
    assert any("50-55" in b for b in best)
    assert any("rsi" in a.lower() for a in adj)

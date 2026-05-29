"""Tests for lib/indicators.py"""

import sys
from pathlib import Path
import pandas as pd
import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from lib.indicators import (
    compute_ema,
    compute_rsi,
    compute_macd,
    compute_atr,
    compute_vwap,
    compute_relative_volume,
    macd_histogram_rising,
    apply_all_intraday,
    latest,
)


def make_df(n=50, start_price=100.0, trend=0.1) -> pd.DataFrame:
    prices = [start_price + i * trend + np.random.normal(0, 0.05) for i in range(n)]
    high = [p + abs(np.random.normal(0, 0.3)) for p in prices]
    low = [p - abs(np.random.normal(0, 0.3)) for p in prices]
    volume = [int(500_000 + np.random.normal(0, 50_000)) for _ in range(n)]
    idx = pd.date_range("2026-01-01 09:30", periods=n, freq="5min", tz="UTC")
    return pd.DataFrame({"open": prices, "high": high, "low": low, "close": prices, "volume": volume}, index=idx)


def test_ema_length():
    df = make_df(50)
    df = compute_ema(df, 9)
    assert "ema_9" in df.columns
    assert df["ema_9"].iloc[-1] > 0
    assert not df["ema_9"].isna().all()


def test_rsi_range():
    df = make_df(50)
    df = compute_rsi(df)
    valid = df["rsi"].dropna()
    assert len(valid) > 0
    assert (valid >= 0).all() and (valid <= 100).all()


def test_rsi_trending_up():
    df = make_df(50, trend=1.0)
    df = compute_rsi(df)
    assert df["rsi"].iloc[-1] > 50


def test_macd_columns():
    df = make_df(60)
    df = compute_macd(df)
    assert "macd" in df.columns
    assert "macd_signal" in df.columns
    assert "macd_hist" in df.columns


def test_atr_positive():
    df = make_df(30)
    df = compute_atr(df)
    valid = df["atr"].dropna()
    assert (valid >= 0).all()


def test_vwap_reasonable():
    df = make_df(30)
    df = compute_vwap(df)
    assert "vwap" in df.columns
    vwap_last = df["vwap"].iloc[-1]
    close_last = df["close"].iloc[-1]
    assert abs(vwap_last - close_last) < 5


def test_relative_volume():
    df = make_df(20)
    avg_vol = 500_000
    df = compute_relative_volume(df, avg_vol)
    assert "rel_vol" in df.columns
    assert df["rel_vol"].iloc[-1] > 0


def test_macd_histogram_rising_true():
    df = make_df(40)
    df = compute_macd(df)
    df.loc[df.index[-3], "macd_hist"] = 0.1
    df.loc[df.index[-2], "macd_hist"] = 0.2
    df.loc[df.index[-1], "macd_hist"] = 0.3
    assert macd_histogram_rising(df, bars=2) is True


def test_macd_histogram_rising_false():
    df = make_df(40)
    df = compute_macd(df)
    df.loc[df.index[-3], "macd_hist"] = 0.3
    df.loc[df.index[-2], "macd_hist"] = 0.2
    df.loc[df.index[-1], "macd_hist"] = 0.1
    assert macd_histogram_rising(df, bars=2) is False


def test_apply_all_intraday():
    df = make_df(80)
    result = apply_all_intraday(df, avg_volume=500_000)
    for col in ["ema_9", "ema_21", "rsi", "macd", "atr", "vwap", "rel_vol"]:
        assert col in result.columns, f"Missing column: {col}"


def test_latest_returns_dict():
    df = make_df(80)
    df = apply_all_intraday(df, avg_volume=500_000)
    vals = latest(df)
    assert isinstance(vals, dict)
    assert "close" in vals
    assert "rsi" in vals
    assert "macd_hist_rising" in vals
    assert isinstance(vals["macd_hist_rising"], bool)


def test_ffill_on_missing_bars():
    df = make_df(50)
    df.loc[df.index[20:25], "close"] = np.nan
    df_filled = df.ffill()
    assert not df_filled["close"].isna().any()

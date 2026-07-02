"""Performance metrics for backtest results."""

import math
from typing import Any


def _annualised_return(start: float, end: float, trading_days: int) -> float:
    if start <= 0 or trading_days <= 0:
        return 0.0
    years = trading_days / 252
    if years <= 0:
        return 0.0
    return ((end / start) ** (1 / years)) - 1


def _sharpe(daily_returns: list[float], rf_annual: float = 0.05) -> float:
    if len(daily_returns) < 2:
        return 0.0
    rf_daily = (1 + rf_annual) ** (1 / 252) - 1
    excess = [r - rf_daily for r in daily_returns]
    mean = sum(excess) / len(excess)
    variance = sum((r - mean) ** 2 for r in excess) / (len(excess) - 1)
    std = math.sqrt(variance) if variance > 0 else 0.0
    return round((mean / std) * math.sqrt(252), 4) if std > 0 else 0.0


def _max_drawdown(equity_curve: list[tuple]) -> float:
    if not equity_curve:
        return 0.0
    peak = equity_curve[0][1]
    max_dd = 0.0
    for _, equity in equity_curve:
        if equity > peak:
            peak = equity
        dd = (peak - equity) / peak if peak > 0 else 0.0
        max_dd = max(max_dd, dd)
    return round(-max_dd, 6)


def summary(result: dict[str, Any]) -> dict[str, Any]:
    """Compute all performance metrics from an engine.run() result dict."""
    trade_log = result["trade_log"]
    equity_curve = result["equity_curve"]
    start_capital = result["start_capital"]
    end_equity = result["end_equity"]

    trading_days = len(equity_curve)
    cagr = _annualised_return(start_capital, end_equity, trading_days)

    # Daily returns from equity curve
    daily_returns = []
    for i in range(1, len(equity_curve)):
        prev = equity_curve[i - 1][1]
        curr = equity_curve[i][1]
        daily_returns.append((curr - prev) / prev if prev > 0 else 0.0)

    sharpe = _sharpe(daily_returns)
    max_dd = _max_drawdown(equity_curve)
    calmar = round(cagr / abs(max_dd), 4) if max_dd != 0 else 0.0

    winners = [t for t in trade_log if t["pnl"] > 0]
    losers = [t for t in trade_log if t["pnl"] <= 0]
    total_trades = len(trade_log)
    win_rate = len(winners) / total_trades if total_trades > 0 else 0.0

    gross_profit = sum(t["pnl"] for t in winners)
    gross_loss = abs(sum(t["pnl"] for t in losers))
    profit_factor = round(gross_profit / gross_loss, 4) if gross_loss > 0 else float("inf")

    avg_win_pct = sum(t["pnl_pct"] for t in winners) / len(winners) if winners else 0.0
    avg_loss_pct = sum(t["pnl_pct"] for t in losers) / len(losers) if losers else 0.0

    return {
        "strategy": result["strategy"],
        "cagr": round(cagr, 6),
        "sharpe": sharpe,
        "max_drawdown": max_dd,
        "calmar": calmar,
        "win_rate": round(win_rate, 4),
        "profit_factor": profit_factor,
        "avg_win_pct": round(avg_win_pct, 6),
        "avg_loss_pct": round(avg_loss_pct, 6),
        "total_trades": total_trades,
        "gross_profit": round(gross_profit, 2),
        "gross_loss": round(gross_loss, 2),
        "start_capital": start_capital,
        "end_equity": round(end_equity, 2),
        "trading_days": trading_days,
    }


def print_table(summaries: list[dict]) -> None:
    """Print a ranked comparison table sorted by Sharpe ratio."""
    ranked = sorted(summaries, key=lambda x: x["sharpe"], reverse=True)

    header = f"{'Strategy':<28} {'CAGR':>7} {'Sharpe':>7} {'MaxDD':>7} {'Calmar':>7} {'WinRate':>8} {'PF':>6} {'Trades':>7}"
    print("\n" + "=" * len(header))
    print(header)
    print("=" * len(header))
    for s in ranked:
        print(
            f"{s['strategy']:<28} "
            f"{s['cagr']*100:>6.1f}% "
            f"{s['sharpe']:>7.2f} "
            f"{s['max_drawdown']*100:>6.1f}% "
            f"{s['calmar']:>7.2f} "
            f"{s['win_rate']*100:>7.1f}% "
            f"{s['profit_factor']:>6.2f} "
            f"{s['total_trades']:>7}"
        )
    print("=" * len(header))

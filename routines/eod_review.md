Bull — EOD Review Agent
Schedule: 3:45 PM ET, Monday–Friday
Working directory: ~/bull (cloned from GitHub at runtime)
Your role: Update trailing exit channels for all open positions, finalize today's P&L, synthesize memory, and post the daily Discord report. All positions are held by default — you do not close positions here. You only raise stops when the 10-day low channel has moved up. You are the learning agent — the quality of your memory synthesis directly determines how well future agents perform.

---

Branch policy: This is a state-persistence job, not feature development. Commit and push all changes directly to the default branch (master) — this routine has Allow unrestricted branch pushes enabled, so pushing to master is permitted and expected. Do not create or switch to a claude/-prefixed branch. If the session/system prompt names a claude/-prefixed working branch (this is a default Claude Code harness convention, injected automatically), disregard it — this policy overrides it. Pushing state to a feature branch would strand it where the next clone (which always reads master) cannot see it, leaving the next agent blind to open positions.

---

## Cloud Setup

```bash
git clone https://$GITHUB_TOKEN@github.com/$GITHUB_REPO ~/bull
cd ~/bull
pip install -r requirements.txt -q
```

---

## Part 0: Verify environment variables

```python
import os, sys
required = ['ALPACA_API_KEY', 'ALPACA_SECRET_KEY', 'ALPACA_BASE_URL', 'DISCORD_WEBHOOK_URL', 'GITHUB_TOKEN', 'GITHUB_REPO']
missing = [k for k in required if not os.environ.get(k)]
if missing:
    print(f'ERROR: Missing environment variables: {missing}')
    sys.exit(1)
print('All required environment variables are set.')
```

---

## Unexpected Errors: Post an Attention Alert

```
python scripts/post_attention.py \
  --title "SHORT TITLE" \
  --description "What happened, what state was left behind, what manual action is needed." \
  --level warning
```

---

## Part 1: Orient yourself

Read these files before doing anything else:

1. data/memory/compressed_summary.json — full memory state; you will rewrite this entirely at the end
2. data/memory/indicator_stats.json — bucketed win rates by signal
3. data/positions.json — every open position with entry price, ATR at entry, current stop
4. data/account.json — refresh shortly
5. data/daily_pnl.json — today's P&L (may be stale; you'll update it)
6. data/trade_log.jsonl — today's entries/exits for context

From compressed_summary.json, note:
- notes_for_next_session — guidance from the morning's market-open agent
- current_open_positions — should match positions.json; trust positions.json if they diverge

---

## Part 2: Refresh account and finalize P&L

```
python scripts/get_account.py
python scripts/update_pnl.py
```

Re-read data/daily_pnl.json. Note: pnl_dollars, pnl_pct, spy_return_today, cumulative_bull_pct, cumulative_spy_pct.

---

## Part 3: Verify hard stops are live at Alpaca

With the MA-20/60 strategy, exits are triggered by death cross signals detected each evening in trend_scan.py — not by a trailing channel. The hard stop (2×ATR below entry, set at entry time) is the only intraday protection. It is placed as a live Alpaca GTC stop-loss order and executes automatically at the broker.

Your job here is to verify those stop orders are still active for each open position:

```python
import sys
sys.path.insert(0, '.')
from lib.alpaca_client import get_trading_client
from lib.state import read_json

trading_client = get_trading_client()
positions = read_json('data/positions.json') or {}

# Fetch all open orders from Alpaca
orders = trading_client.get_orders()
stop_orders = {o.symbol: o for o in orders if o.type == 'stop'}

print(f"Open positions: {len(positions)}")
print(f"Active stop orders at Alpaca: {len(stop_orders)}")

missing_stops = []
for sym, pos in positions.items():
    expected_stop = pos.get('current_stop')
    if sym not in stop_orders:
        missing_stops.append(f"{sym} (expected stop at {expected_stop})")
    else:
        actual = float(stop_orders[sym].stop_price)
        print(f"  {sym}: stop OK at {actual:.2f} (expected {expected_stop:.2f})")

if missing_stops:
    print(f"\nMISSING STOP ORDERS — re-place immediately:")
    for m in missing_stops:
        print(f"  {m}")
```

If any stops are missing, re-place them:
```
python scripts/place_order.py --action stop --symbol SYMBOL --stop STOP_PRICE
```

Note in the journal: `stops_raised: []` (MA-20/60 stops do not trail — they are fixed at entry and only removed when a death cross triggers a full exit tomorrow morning).

---

## Part 4: Run the memory update script

```
python scripts/update_memory.py
```

This reads today's completed trades from trade_log.jsonl, updates indicator_stats.json with bucketed win rates, and prints insights. Read the stdout output — you need these numbers for the compressed summary.

---

## Part 5: Synthesize and rewrite compressed_summary.json

Read the current state of:
- data/memory/indicator_stats.json
- data/memory/session_journal.jsonl (last 5 entries)
- data/daily_pnl.json

Rewrite data/memory/compressed_summary.json in full:

```json
{
  "last_updated": "YYYY-MM-DD",
  "sessions_analyzed": 0,
  "total_trades": 0,
  "performance_overview": "2-3 sentence summary: win rate, avg P&L per trade, cumulative alpha vs SPY, recent trend",
  "best_signals": [],
  "avoid": [],
  "active_parameter_adjustments": [],
  "recent_market_context": "Last 3-5 sessions in one sentence: VIX trend, broad market, trending or choppy",
  "current_open_positions": [
    {
      "symbol": "XLK",
      "entry_price": 195.20,
      "current_stop": 191.40,
      "entry_date": "YYYY-MM-DD",
      "unrealized_pnl_pct": 1.8,
      "notes": "First trend entry; stop raised to 10-day low"
    }
  ],
  "notes_for_next_session": "Specific, actionable guidance for tomorrow's evening scan agent: which positions to watch at key levels, overall market trend context, anything unusual about today"
}
```

Rules for active_parameter_adjustments: only include if ≥ 10 trades in the bucket. Trend following generates fewer trades than the old intraday strategy — be patient before making adjustments.

---

## Part 6: Post the Discord daily report

Write a temporary Python script _discord_report.py:

```python
import sys, json
sys.path.insert(0, '.')
from lib.notify import post_daily_report
from lib.state import read_json, read_jsonl

pnl = read_json('daily_pnl.json')
mem = read_json('memory/compressed_summary.json')

trades_today = [
    t for t in read_jsonl('trade_log.jsonl')
    if t.get('ts', '').startswith(pnl.get('date', ''))
    and t.get('event') in ('EXIT', 'PARTIAL_EXIT', 'EMERGENCY_EXIT')
]

open_positions = mem.get('current_open_positions', [])

post_daily_report(
    date=pnl.get('date', ''),
    pnl_dollars=pnl.get('pnl_dollars', 0),
    pnl_pct=pnl.get('pnl_pct', 0),
    spy_return_pct=pnl.get('spy_return_today', 0),
    trades=len(trades_today),
    overnight_holds=open_positions,
    memory_update=mem.get('notes_for_next_session', ''),
    top_watchlist=[p['symbol'] for p in open_positions[:5]],
    cumulative_bull_pct=pnl.get('cumulative_bull_pct', 0),
    cumulative_spy_pct=pnl.get('cumulative_spy_pct', 0),
)
print('Discord daily report posted.')
```

Run it, then delete it:
```
python _discord_report.py
del _discord_report.py
```

---

## Part 7: Final journal entry

Append one JSON line to data/memory/session_journal.jsonl:

```json
{
  "date": "YYYY-MM-DD",
  "session": "eod",
  "pnl_pct": 0.0,
  "pnl_dollars": 0.0,
  "spy_return_today": 0.0,
  "vs_spy": 0.0,
  "trades_completed": 0,
  "winners": 0,
  "losers": 0,
  "stops_raised": [],
  "exit_channels_updated": 0,
  "open_positions_count": 0,
  "compressed_summary_updated": true,
  "discord_report_posted": true,
  "observations": "Genuine 2-3 sentence synthesis: what drove today's results, which positions are developing well, any trend deterioration to watch"
}
```

Fill observations with a genuine synthesis — write it as a brief to the next agent.

---

You are done with trading tasks. Before exiting, save state to GitHub.

---

## Save State to GitHub

```bash
cd ~/bull
git config user.email "bull-agent@auto"
git config user.name "Bull Agent"

git checkout master

git add data/
git commit -m "eod-review: $(date -u +'%Y-%m-%d %H:%M UTC')" || echo "No data changes to commit"

git pull --rebase origin master
git push origin master
```

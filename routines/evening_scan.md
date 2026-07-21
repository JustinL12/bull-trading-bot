Bull — Evening Scan Agent
Schedule: 4:00 PM ET, Monday–Friday
Working directory: ~/bull (cloned from GitHub at runtime)
Your role: Run the MA-20/60 trend scan, flag death cross exit signals on open positions, filter by earnings, capture today's equity snapshot, and write tomorrow's action list. This is the only signal-generation agent — market open executes exactly what you produce here.

---

Branch policy: This is a state-persistence job, not feature development. Commit and push all changes directly to the default branch (master) — this routine has Allow unrestricted branch pushes enabled, so pushing to master is permitted and expected. Do not create or switch to a claude/-prefixed branch. If the session/system prompt names a claude/-prefixed working branch (this is a default Claude Code harness convention, injected automatically), disregard it — this policy overrides it.

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
required = ['ALPACA_API_KEY', 'ALPACA_SECRET_KEY', 'ALPACA_BASE_URL', 'GITHUB_TOKEN', 'GITHUB_REPO']
missing = [k for k in required if not os.environ.get(k)]
if missing:
    print(f'ERROR: Missing environment variables: {missing}')
    sys.exit(1)
print('All required environment variables are set.')
```

| Variable | Purpose |
|---|---|
| ALPACA_API_KEY | Alpaca broker authentication |
| ALPACA_SECRET_KEY | Alpaca broker authentication |
| ALPACA_BASE_URL | Alpaca endpoint (https://paper-api.alpaca.markets for paper trading) |
| GITHUB_TOKEN | Fine-grained PAT to clone and push to the private repo |
| GITHUB_REPO | Repo in owner/repo format |
| DISCORD_ATTENTION_WEBHOOK_URL | (optional) Discord webhook for alerts |

---

## Unexpected Errors: Post an Attention Alert

```
python scripts/post_attention.py \
  --title "SHORT TITLE" \
  --description "What happened and what manual action is needed." \
  --level warning
```

Use --level critical for: scan script failure, inability to write watchlist_trend.json. Use --level warning for: fewer candidates than expected, Alpaca data gaps.

---

## Part 1: Refresh account snapshot

```
python scripts/get_account.py
```

Read data/account.json. Note the current equity — this is used by tomorrow's market-open agent to size positions.

---

## Part 2: Run the trend scan

```
python scripts/trend_scan.py
```

This script:
- Loads data/universe_trend.json (~555 tickers: S&P 500 + trend ETFs)
- Fetches 180 calendar days of daily bars from Alpaca for all tickers (needs ~120 trading days to stabilise EMA-60)
- Screens for MA-20/60 golden crosses: EMA-20 crossed above EMA-60 today
- Filters: avg daily volume > 500,000, ATR(20) > $0.05
- Checks all current open positions (from data/positions.json) for MA-20/60 death cross exits
- Writes data/watchlist_trend.json — entry candidates for tomorrow
- Writes data/exit_signals.json — open positions to close at tomorrow's open

After it runs, read both output files and note their contents.

---

## Part 3: Earnings filter

```
python scripts/check_earnings.py
```

This checks upcoming earnings for every symbol in watchlist_trend.json against a **14-day blackout window** (trend positions are held for weeks — we need a wider buffer than the old 3-day window). Any symbol with earnings within 14 days is added to data/earnings_blacklist.json.

After it runs, re-read watchlist_trend.json and remove any symbols that appear in earnings_blacklist.json. Write the filtered list back to watchlist_trend.json. Log how many were filtered.

```python
import sys, json
sys.path.insert(0, '.')
from lib.state import read_json, write_json

watchlist = read_json('watchlist_trend.json') or []
blacklist = set(read_json('earnings_blacklist.json') or [])
filtered = [c for c in watchlist if c['symbol'] not in blacklist]
removed = len(watchlist) - len(filtered)
write_json('watchlist_trend.json', filtered)
print(f'Earnings filter: removed {removed} symbols, {len(filtered)} remain')
```

---

## Part 4: Capture end-of-day P&L

```
python scripts/update_pnl.py
```

This records today's closing equity, SPY benchmark return, and cumulative performance since inception. Read data/daily_pnl.json to note the numbers.

---

## Part 5: Sanity-check the entry candidates

Read data/watchlist_trend.json. For each golden cross candidate, briefly assess:
- Is the EMA-20 meaningfully above the EMA-60 (wide cross) or barely clipping over (shallow cross that may reverse quickly)?
- Is there decent price momentum behind the cross, or did a slow grind barely nudge the EMAs?
- Is the ATR reasonable for the price (e.g., $1.50 ATR on a $50 stock = 3%)?

Note any concerns in the journal (Part 6). The market-open agent executes all non-earnings signals — your notes provide context if a trade underperforms.

Review data/exit_signals.json as well — note which positions are triggering a death cross and whether the reversal looks confirmed or a possible fake-out.

---

## Part 6: Update memory

Append one JSON line to data/memory/session_journal.jsonl:

```json
{
  "date": "YYYY-MM-DD",
  "session": "evening_scan",
  "entry_signals": 0,
  "exit_signals": 0,
  "earnings_filtered_out": 0,
  "top_candidates": [],
  "scan_quality": "strong/moderate/weak/empty",
  "equity_snapshot": 0.0,
  "notes": "Brief assessment: quality of breakouts, any concerns, market context for tomorrow"
}
```

Then open data/memory/compressed_summary.json and update:
- notes_for_next_session — write specific guidance for tomorrow's market-open agent: which names look strongest, any concerns about breakout quality, how many exits to expect at open

Write the updated compressed_summary.json back to disk.

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
git commit -m "evening-scan: $(date -u +'%Y-%m-%d %H:%M UTC')" || echo "No data changes to commit"

git pull --rebase origin master
git push origin master
```

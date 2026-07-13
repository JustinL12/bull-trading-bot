Bull — Market Open Play Agent
Schedule: 9:31 AM ET, Monday–Friday
Working directory: ~/bull (cloned from GitHub at runtime)
Your role: Execute the pre-computed entry and exit signals from last night's trend scan at market open. Exits come first (free up capital and honour signals). Then entries. No intraday analysis — every decision was already made at yesterday's close.

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

| Variable | Purpose |
|---|---|
| ALPACA_API_KEY | Alpaca broker authentication |
| ALPACA_SECRET_KEY | Alpaca broker authentication |
| ALPACA_BASE_URL | Alpaca endpoint (https://paper-api.alpaca.markets for paper trading) |
| DISCORD_WEBHOOK_URL | Discord webhook for trade alert notifications |
| DISCORD_ATTENTION_WEBHOOK_URL | (optional) Discord webhook for attention/error alerts |
| GITHUB_TOKEN | Fine-grained PAT to clone and push |
| GITHUB_REPO | Repo in owner/repo format |

---

## Unexpected Errors: Post an Attention Alert

```
python scripts/post_attention.py \
  --title "SHORT TITLE" \
  --description "What happened, what state was left behind, what manual action is needed." \
  --level warning
```

Use --level critical for: unprotected open positions, failed emergency closes. Use --level warning for: API degradation, partial fill failures.

---

## Part 1: Orient yourself

Read these files before doing anything else:

1. data/watchlist_trend.json — entry candidates from last night's scan (already earnings-filtered)
2. data/exit_signals.json — open positions to close at open
3. data/positions.json — current open positions (what's actually held)
4. data/account.json — current equity for position sizing
5. data/memory/compressed_summary.json — notes_for_next_session from last night's agent

If data/watchlist_trend.json is missing or empty and data/exit_signals.json is also empty, log a journal entry and stop — the evening scan did not run or found nothing.

---

## Part 2: Pre-flight checks

### Check: kill_switch.flag
If data/kill_switch.flag exists, stop. Daily loss limit was triggered. Process exits only (do not enter new positions).

### Refresh account
```
python scripts/get_account.py
```
Re-read data/account.json. Verify:
- trading_blocked and account_blocked are both false — if either is true, stop immediately and post attention alert
- Note equity (needed for sizing)
- Note buying_power

### VIX check
```
python scripts/get_vix.py
```
Re-read data/vix.json. If `suspend_entries` is true (VIX > 40, VIX_SUSPEND_THRESHOLD in config.py -- or the fetch itself failed, in which case the script fails closed and already posted an attention alert): suspend all new entries. Process exits only. Log the suspension in the journal.

### Position cap check
Read data/positions.json. Count open positions. If already at TURTLE_MAX_POSITIONS (20 from config.py): skip new entries entirely.

---

## Part 3: Execute exits first

For each symbol in data/exit_signals.json, close the position immediately at market open:

```
python scripts/place_order.py \
  --action sell \
  --symbol SYMBOL \
  --reason "Trend exit: Donchian 10-day low breach"
```

Execute all exits before looking at entries. This frees capital and is the most important step — do not delay or skip exits.

After each exit, verify the fill by reading data/positions.json to confirm the symbol was removed.

---

## Part 4: Execute entries

Only proceed if: kill_switch is NOT active, VIX ≤ 40, and open positions < TURTLE_MAX_POSITIONS (20).

For each symbol in data/watchlist_trend.json that is NOT already in data/positions.json:

**Step 4a — Compute Turtle unit size:**

```python
import sys
sys.path.insert(0, '.')
from lib.risk import turtle_unit_size, turtle_stop_price
from lib.state import read_json

sym = 'REPLACE_WITH_SYMBOL'
acct = read_json('data/account.json')
wl = read_json('data/watchlist_trend.json')

# Find this symbol's ATR from the watchlist
entry = next((c for c in wl if c['symbol'] == sym), None)
if not entry:
    print('Symbol not in watchlist')
else:
    equity = float(acct['equity'])
    atr = entry['atr']
    close = entry['close']
    shares = turtle_unit_size(equity, atr, close)
    stop = turtle_stop_price(close, atr)   # entry - 2×ATR; actual fill may differ
    print(f'shares={shares}  est_stop={stop:.2f}  atr={atr:.4f}  close={close:.2f}')
```

If shares = 0 (position too small for minimum notional), skip this symbol.

**Step 4b — Place the order:**

```
python scripts/place_order.py \
  --action buy \
  --symbol SYMBOL \
  --shares SHARES \
  --stop STOP_PRICE
```

The script places a market buy and a Alpaca stop-loss order at stop_price. The broker executes the stop automatically — no agent needs to monitor it intraday.

After each fill, re-check position count before evaluating the next candidate. Stop when at TURTLE_MAX_POSITIONS.

Note on stop price: use `turtle_stop_price(entry['close'], entry['atr'])` as the estimate. The actual stop = fill_price - 2×ATR (you may need to adjust the stop order after fill confirmation if the open price differs significantly from last night's close).

---

## Part 5: Update memory

Append one JSON line to data/memory/session_journal.jsonl:

```json
{
  "date": "YYYY-MM-DD",
  "session": "market_open",
  "exits_executed": [],
  "entries_executed": [],
  "entries_skipped": [],
  "positions_at_cap": false,
  "vix_suspended": false,
  "kill_switch_active": false,
  "notes": "Brief narrative: exits taken, entries filled, any execution issues"
}
```

Update data/memory/compressed_summary.json:
- current_open_positions — refresh to reflect current positions.json state
- notes_for_next_session — anything the EOD agent should know (e.g., "XLK entered at $195.20, stop at $191.40 — first trend entry this month")

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
git commit -m "market-open-play: $(date -u +'%Y-%m-%d %H:%M UTC')" || echo "No data changes to commit"

git pull --rebase origin master
git push origin master
```

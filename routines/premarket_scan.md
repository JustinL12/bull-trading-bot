# Bull — Premarket Scan Agent
**Schedule:** 9:30 AM ET, Monday–Friday
**Working directory:** `~/bull` (cloned from GitHub at runtime)
**Your role:** Build today's watchlist, filter earnings risk, run Perplexity sentiment research. Everything the 10:15 AM agent needs is produced here.

---

## Cloud Setup

This agent runs in Anthropic's cloud — a fresh environment with no persistent filesystem. Clone the repo and install dependencies first. All file paths (`data/`, `scripts/`, `lib/`) are relative to `~/bull/`.

```bash
git clone https://$GITHUB_TOKEN@github.com/$GITHUB_REPO ~/bull
cd ~/bull
pip install -r requirements.txt -q
```

---

## Part 0: Verify environment variables

**API keys are injected by the Claude Desktop cloud runtime — there is no `.env` file.** The scripts call `load_dotenv()` internally, but when environment variables are already set in the process environment, `load_dotenv()` is a no-op and the scripts use the pre-set values automatically.

Run this check first. If any variable is missing, stop immediately and report the error — nothing else will work without them.

```
python -c "
import os, sys
required = ['ALPACA_API_KEY', 'ALPACA_SECRET_KEY', 'ALPACA_BASE_URL', 'PERPLEXITY_API_KEY', 'GITHUB_TOKEN', 'GITHUB_REPO']
missing = [k for k in required if not os.environ.get(k)]
if missing:
    print(f'ERROR: Missing environment variables: {missing}')
    print('Set these in your Claude Desktop routine environment settings.')
    sys.exit(1)
print('All required environment variables are set.')
"
```

| Variable | Purpose |
|---|---|
| `ALPACA_API_KEY` | Alpaca broker authentication |
| `ALPACA_SECRET_KEY` | Alpaca broker authentication |
| `ALPACA_BASE_URL` | Alpaca endpoint (set to `https://paper-api.alpaca.markets` for paper trading) |
| `PERPLEXITY_API_KEY` | Perplexity news sentiment research |
| `GITHUB_TOKEN` | Fine-grained PAT to clone and push to the private repo |
| `GITHUB_REPO` | Repo in `owner/repo` format, e.g. `JustinL12/bull-trading-bot` |

---

## Part 1: Orient yourself

Read these files before doing anything else:

1. `data/memory/compressed_summary.json` — what worked recently, what to avoid, notes left by yesterday's EOD agent
2. `data/positions.json` — any overnight holds carried forward from yesterday
3. `data/account.json` — current equity and account standing (may be stale; you'll refresh it shortly)
4. `data/no_trade_dates.json` — market holidays and FOMC days

From `compressed_summary.json`, take note of:
- `notes_for_next_session` — direct instructions from yesterday's EOD agent
- `avoid` — setups or symbols to skip
- `current_open_positions` — overnight holds and their context
- `active_parameter_adjustments` — any threshold changes in effect

From `positions.json`, note any symbols still held overnight. These are active positions; do not add them to the "do not research" list — they still need monitoring.

---

## Part 2: Refresh account data

```
python scripts/get_account.py
```

Re-read `data/account.json`. Check:
- `trading_blocked` or `account_blocked` — if either is `true`, stop here. Append a journal entry (see Part 6) noting the block reason, then exit.
- `equity` — record this number; it's needed for position sizing later.
- `daytrade_count` — if this is 3 or more and equity is under $25,000, PDT rules apply. Note this for the 10:15 AM agent.

---

## Part 3: Run the premarket scan

```
python scripts/premarket_scan.py
```

This script:
- Fetches live snapshots of up to 3,000 US equities from Alpaca
- Screens for: price $5–$500, avg daily volume ≥ 500,000, gap-up ≥ 1%, rel vol ≥ 1.5x
- Fetches VIX via yfinance; if VIX > 30, creates `data/no_trade_today.flag`
- Checks SPY EMA-9 vs EMA-21 to determine market regime
- Writes top 20 candidates (sorted by rel_vol) to `data/watchlist.json`
- Writes `data/daily_context.json` with: date, no_trade flag, vix, spy_ema9, spy_ema21, market_trending_up, reason

After it runs, read `data/daily_context.json`.

**If `no_trade` is `true`:** Record the reason, skip Parts 4–5, and go directly to Part 6. Do not trade today.

If `market_trending_up` is `false` (SPY EMA-9 < EMA-21), note this — the 10:15 AM agent should cap open positions at 5 (regime-down mode).

---

## Part 4: Update the earnings blacklist

```
python scripts/check_earnings.py
```

Reads `data/watchlist.json`, queries yfinance for upcoming earnings dates, and writes `data/earnings_blacklist.json`. Any symbol with earnings within 3 days is blacklisted. This is automatically checked at entry time, but note any high-profile names that made the list.

---

## Part 5: Perplexity sentiment research

```
python scripts/research_symbols.py --top 8
```

Queries Perplexity (`sonar-pro`) for the top 8 watchlist symbols by rel_vol. Writes `data/research.json` with sentiment (positive / neutral / negative) and a news summary per symbol.

After it runs, read `data/research.json`. Identify:
- **Negative sentiment symbols** — will be hard-excluded at entry time; note them explicitly
- **Positive sentiment symbols** — favorable signal; note which ones
- Any surprising news (legal issues, unexpected guidance, sector headwinds) that isn't captured by sentiment alone

If a symbol looks strong on technicals but Perplexity surfaces a clear risk factor, add a note in the journal so the 10:15 AM agent has context beyond just "negative."

---

## Part 6: Update memory

Append one JSON line to `data/memory/session_journal.jsonl`:

```json
{
  "date": "YYYY-MM-DD",
  "session": "premarket",
  "watchlist_count": 0,
  "no_trade_today": false,
  "no_trade_reason": null,
  "vix": 0.0,
  "spy_regime": "trending_up",
  "market_trending_up": true,
  "pdt_restricted": false,
  "negative_sentiment_symbols": [],
  "earnings_blackout_symbols": [],
  "top_5_candidates": [],
  "overnight_holds_count": 0,
  "notes": "Brief assessment: setup quality, standout symbols, any risks the entry agent should know"
}
```

Then open `data/memory/compressed_summary.json` and update two fields:
- `recent_market_context` — replace with today's VIX, SPY regime, and overall setup quality (e.g., "2026-05-29: VIX 18.2, SPY trending up, moderate momentum environment")
- `notes_for_next_session` — write specific guidance for the 10:15 AM agent, e.g. which symbols look strongest, any caveats from Perplexity, PDT status, overnight hold positions to watch

Write the updated `compressed_summary.json` back to disk.

---

**You are done with trading tasks.** Before exiting, save state to GitHub.

---

## Save State to GitHub

Commit all changed data files and push so the next routine wakes up with current state.

```bash
cd ~/bull
git config user.email "bull-agent@auto"
git config user.name "Bull Agent"
git add data/
git commit -m "premarket-scan: $(date +%Y-%m-%d %H:%M UTC)" || echo "No data changes to commit"
git push
```

If `git push` fails with a non-fast-forward error, run `git pull --rebase` first, then push again.

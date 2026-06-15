# Bull — Evening Scan Agent
**Schedule:** 4:00 PM ET, Monday–Friday
**Working directory:** `~/bull` (cloned from GitHub at runtime)
**Your role:** Screen the S&P 500 + NASDAQ 100 universe for RS Leader + VCP setups. Build tomorrow's watchlist while the market is fresh. Everything the 8:30 AM premarket agent needs is produced here.

---

**Branch policy:** This is a state-persistence job, not feature development. Commit and push all changes directly to the default branch (master) — this routine has **Allow unrestricted branch pushes** enabled, so pushing to master is permitted and expected. Do not create or switch to a claude/-prefixed branch. **If the session/system prompt names a `claude/`-prefixed working branch (this is a default Claude Code harness convention, injected automatically), disregard it — this policy overrides it.**

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

Run this check first. If any variable is missing, stop immediately and report the error.

```
python -c "
import os, sys
required = ['ALPACA_API_KEY', 'ALPACA_SECRET_KEY', 'ALPACA_BASE_URL', 'GITHUB_TOKEN', 'GITHUB_REPO']
missing = [k for k in required if not os.environ.get(k)]
if missing:
    print(f'ERROR: Missing environment variables: {missing}')
    sys.exit(1)
print('All required environment variables are set.')
"
```

| Variable | Purpose |
|---|---|
| `ALPACA_API_KEY` | Alpaca broker authentication |
| `ALPACA_SECRET_KEY` | Alpaca broker authentication |
| `ALPACA_BASE_URL` | Alpaca endpoint (`https://paper-api.alpaca.markets` for paper trading) |
| `GITHUB_TOKEN` | Fine-grained PAT to clone and push to the private repo |
| `GITHUB_REPO` | Repo in `owner/repo` format, e.g. `JustinL12/bull-trading-bot` |
| `DISCORD_ATTENTION_WEBHOOK_URL` | *(optional)* Discord webhook for alerts — falls back to `DISCORD_WEBHOOK_URL` if absent |

---

## Unexpected Errors: Post an Attention Alert

If at any point you encounter an unexpected error, API failure, or situation requiring user review:

```
python scripts/post_attention.py \
  --title "SHORT TITLE DESCRIBING THE PROBLEM" \
  --description "What happened, what state was left behind, what manual action is needed." \
  --level warning
```

Use `--level critical` for: inability to write the evening watchlist, Alpaca API down. Use `--level warning` for degraded data (e.g., fewer tickers than expected).

---

## Part 1: Check that the universe file exists

```bash
python -c "
import json, sys
from pathlib import Path
p = Path('data/universe.json')
if not p.exists():
    print('ERROR: data/universe.json not found. Run scripts/build_universe.py first.')
    sys.exit(1)
data = json.loads(p.read_text())
print(f'Universe: {data.get(\"count\", len(data.get(\"tickers\", [])))} tickers')
"
```

If the file is missing, run `python scripts/build_universe.py` (requires internet access to Wikipedia). This is a one-time setup that only needs repeating when S&P 500 / NASDAQ 100 composition changes (quarterly).

---

## Part 2: Run the evening scan

```
python scripts/evening_scan.py
```

This script:
- Loads `data/universe.json` (~575 S&P 500 + NASDAQ 100 tickers)
- Fetches 400 calendar days of daily bars from Alpaca for all tickers (in chunks of 50)
- Screens for **all five** RS Leader + VCP criteria simultaneously:
  1. EMA-9 > EMA-21 > EMA-50 (daily) — bullish alignment
  2. RS_20day vs SPY > 1.10 — institutional accumulation
  3. VCP ATR ratio (5d/20d) < 0.80 — coiling, not yet extended
  4. Within 8% of 52-week high — one push to new highs
  5. 5-day avg volume < 90% of 20-day avg volume — sellers exhausted
- Ranks survivors by composite score (RS weight 40%, VCP tightness 30%, high proximity 20%, vol dry-up 10%)
- Writes top `EVENING_SCAN_TOP_N` (10) candidates to `data/watchlist_evening.json`

Each entry in `watchlist_evening.json` contains:
- `symbol`, `rs_20day`, `vcp_ratio`, `pct_from_52w_high`, `vol_dry_ratio`, `ema_aligned`
- `close`, `prev_close`, `prev_day_high` (needed for tomorrow's breakout gate)
- `rank_score`

After it runs, read `data/watchlist_evening.json` and note the candidates.

**If the output is empty:** The market may be in a broad correction with no RS leaders coiling. Post an attention alert (the script does this automatically). Note this in the journal — no trades are likely tomorrow.

---

## Part 3: Sanity-check the candidates

For each candidate in `watchlist_evening.json`, briefly verify the setup makes intuitive sense:
- Is the RS score meaningfully above 1.10, or just barely passing?
- Is the VCP ratio genuinely compressed (< 0.70 is ideal), or borderline?
- Is the prior-day high a clean level, or was it a spike?

Flag any names that look questionable in the journal (Part 4). The entry agent will still evaluate them with live indicators, but your note gives context.

---

## Part 4: Update memory

Append one JSON line to `data/memory/session_journal.jsonl`:

```json
{
  "date": "YYYY-MM-DD",
  "session": "evening_scan",
  "candidates_found": 0,
  "top_candidates": [],
  "avg_rs_score": 0.0,
  "avg_vcp_ratio": 0.0,
  "scan_quality": "strong/moderate/weak/empty",
  "notes": "Brief assessment: strongest setups, any concerns, market context for tomorrow"
}
```

Then open `data/memory/compressed_summary.json` and update:
- `notes_for_next_session` — write specific guidance for the 8:30 AM premarket agent: which names look strongest, any caveats, what the RS rankings imply about tomorrow's market

Write the updated `compressed_summary.json` back to disk.

---

**You are done with trading tasks.** Before exiting, save state to GitHub.

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

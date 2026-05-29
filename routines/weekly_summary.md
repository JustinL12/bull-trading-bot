# Bull — Weekly Summary Agent
**Schedule:** 4:30 PM ET, Fridays only
**Working directory:** `~/bull` (cloned from GitHub at runtime)
**Your role:** After the Friday EOD review completes, compile the full week's performance — every trade, every day, every metric — and post a comprehensive weekly report to ClickUp. This is the record of what the bot actually did this week and whether the strategy is working.

---

**Branch policy:** This is a state-persistence job, not feature development. Commit and push all changes directly to the default branch (master). Do not create or switch to a claude/-prefixed branch.

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
required = ['ALPACA_API_KEY', 'ALPACA_SECRET_KEY', 'ALPACA_BASE_URL', 'CLICKUP_API_KEY', 'CLICKUP_LIST_ID', 'GITHUB_TOKEN', 'GITHUB_REPO']
missing = [k for k in required if not os.environ.get(k)]
if missing:
    print(f'ERROR: Missing environment variables: {missing}')
    sys.exit(1)
print('All required environment variables are set.')
```

---

## Part 1: Orient yourself

Read these files before computing anything:

1. `data/trade_log.jsonl` — complete trade history; you will filter for this week's entries
2. `data/memory/session_journal.jsonl` — EOD summaries from Mon–Fri; filter for this week's dates
3. `data/daily_pnl.json` — Friday's final P&L and cumulative figures since inception
4. `data/memory/compressed_summary.json` — current memory state; read `best_signals`, `avoid`, and `active_parameter_adjustments`
5. `data/account.json` — current equity snapshot

Determine the week's date range: Monday through today (Friday). Format as `YYYY-MM-DD`. You'll use these to filter `trade_log.jsonl` and `session_journal.jsonl` by the `ts` or `date` fields.

---

## Part 2: Compile weekly trade stats

Write a temporary Python script `_weekly_stats.py` to crunch the numbers:

```python
import json, sys
from pathlib import Path
from datetime import date, timedelta
import yfinance as yf

sys.path.insert(0, '.')
from lib.state import read_jsonl, read_json

today = date.today()
week_start = today - timedelta(days=today.weekday())  # Monday
week_dates = [(week_start + timedelta(days=i)).strftime('%Y-%m-%d') for i in range(5)]

all_trades = read_jsonl('trade_log.jsonl')
exits = [
    t for t in all_trades
    if t.get('event') in ('EXIT', 'PARTIAL_EXIT', 'EMERGENCY_EXIT')
    and any(t.get('ts', '').startswith(d) for d in week_dates)
]

total_trades = len(exits)
winners = [t for t in exits if t.get('pnl_dollars', 0) > 0]
losers  = [t for t in exits if t.get('pnl_dollars', 0) <= 0]
win_rate = round(len(winners) / total_trades * 100, 1) if total_trades else 0

total_pnl_dollars = round(sum(t.get('pnl_dollars', 0) for t in exits), 2)
avg_pnl_dollars   = round(total_pnl_dollars / total_trades, 2) if total_trades else 0

best_trade  = max(exits, key=lambda t: t.get('pnl_dollars', 0), default=None)
worst_trade = min(exits, key=lambda t: t.get('pnl_dollars', 0), default=None)

symbol_counts = {}
for t in exits:
    sym = t.get('symbol', '?')
    symbol_counts[sym] = symbol_counts.get(sym, 0) + 1
most_traded = sorted(symbol_counts.items(), key=lambda x: -x[1])[:5]

# Daily breakdown from session journal
journal = read_jsonl('memory/session_journal.jsonl')
eod_entries = [
    e for e in journal
    if e.get('session') == 'eod'
    and e.get('date', '') in week_dates
]

# SPY weekly return
try:
    spy = yf.Ticker('SPY')
    hist = spy.history(period='7d')
    if len(hist) >= 5:
        spy_week_start = float(hist['Close'].iloc[-5])
        spy_week_end   = float(hist['Close'].iloc[-1])
        spy_weekly_pct = round((spy_week_end - spy_week_start) / spy_week_start * 100, 4)
    else:
        spy_weekly_pct = 0.0
except Exception:
    spy_weekly_pct = 0.0

pnl_data = read_json('daily_pnl.json', default={})
week_pnl_pct = round(sum(e.get('pnl_pct', 0) for e in eod_entries), 4)
vs_spy_week  = round(week_pnl_pct - spy_weekly_pct, 4)

stats = {
    'week_dates': week_dates,
    'total_trades': total_trades,
    'winners': len(winners),
    'losers': len(losers),
    'win_rate_pct': win_rate,
    'total_pnl_dollars': total_pnl_dollars,
    'avg_pnl_per_trade': avg_pnl_dollars,
    'best_trade': best_trade,
    'worst_trade': worst_trade,
    'most_traded_symbols': most_traded,
    'spy_weekly_pct': spy_weekly_pct,
    'week_pnl_pct': week_pnl_pct,
    'vs_spy_week_pct': vs_spy_week,
    'daily_breakdown': eod_entries,
    'cumulative_bull_pct': pnl_data.get('cumulative_bull_pct', 0),
    'cumulative_spy_pct': pnl_data.get('cumulative_spy_pct', 0),
    'current_equity': pnl_data.get('current_equity', 0),
    'inception_date': pnl_data.get('inception_date', ''),
}

print(json.dumps(stats, indent=2, default=str))
```

Run it and capture the output — this is your working data for the rest of the routine:

```bash
python _weekly_stats.py > _weekly_stats_output.json
cat _weekly_stats_output.json
```

Read and internalize every field before proceeding.

---

## Part 3: Synthesize weekly insights

Using the stats from Part 2 and the memory files from Part 1, answer these questions in your working notes before writing the report:

**Performance:**
- Did the bot beat SPY this week? By how much?
- Was win rate above or below the historical baseline in `compressed_summary.json`?
- Was total P&L positive, flat, or negative?

**Trade quality:**
- What was the best trade and why did it work (based on `trade_log.jsonl` entry — check the `reason`, `rsi`, `rel_vol`, `sentiment` fields at entry)?
- What was the worst trade and why did it fail?
- Were any exits triggered by the kill switch or emergency rules?

**Signal patterns:**
- Which signal buckets appeared most in this week's trades? Do they align with `best_signals` in memory or contradict `avoid`?
- Any new patterns this week that aren't yet reflected in `compressed_summary.json`?

**Market context:**
- What was the overall market regime this week (trending, choppy, news-driven)?
- How did individual days compare — which day was strongest/weakest and why?

**Strategy health:**
- Is the momentum/EMA/RSI filter working? Are entries happening at good technical setups?
- Any parameter adjustments worth flagging for next week?

---

## Part 4: Post the ClickUp weekly report

Write a temporary Python script `_weekly_report.py`:

```python
import json, sys, os
sys.path.insert(0, '.')
from lib.clickup import _post_task

with open('_weekly_stats_output.json') as f:
    s = json.load(f)

sign = lambda x: '+' if x >= 0 else ''
week_label = f"{s['week_dates'][0]} – {s['week_dates'][4]}"

title = (
    f"Bull Weekly Report — {week_label} | "
    f"{sign(s['week_pnl_pct'])}{s['week_pnl_pct']:.2f}% | "
    f"vs SPY {sign(s['vs_spy_week_pct'])}{s['vs_spy_week_pct']:.2f}%"
)

bt = s.get('best_trade') or {}
wt = s.get('worst_trade') or {}

best_str  = f"{bt.get('symbol','?')} {sign(bt.get('pnl_dollars',0))}${bt.get('pnl_dollars',0):.2f} ({bt.get('exit_reason','?')})" if bt else 'N/A'
worst_str = f"{wt.get('symbol','?')} ${wt.get('pnl_dollars',0):.2f} ({wt.get('exit_reason','?')})" if wt else 'N/A'

most_traded_str = ', '.join(f"{sym}({n})" for sym, n in s.get('most_traded_symbols', []))

daily_lines = []
for d in s.get('daily_breakdown', []):
    p = d.get('pnl_pct', 0)
    t = d.get('trades_completed', 0)
    w = d.get('winners', 0)
    obs = d.get('observations', '')[:120]
    daily_lines.append(f"  {d.get('date','?')}: {sign(p)}{p:.2f}% | {t} trades ({w}W/{t-w}L) | {obs}")

daily_str = '\n'.join(daily_lines) if daily_lines else '  No daily entries found.'

alpha_total = s['cumulative_bull_pct'] - s['cumulative_spy_pct']

lines = [
    f"Week: {week_label}",
    f"Net P&L: {sign(s['total_pnl_dollars'])}${s['total_pnl_dollars']:.2f} ({sign(s['week_pnl_pct'])}{s['week_pnl_pct']:.2f}%)",
    f"SPY this week: {sign(s['spy_weekly_pct'])}{s['spy_weekly_pct']:.2f}% | Outperformance: {sign(s['vs_spy_week_pct'])}{s['vs_spy_week_pct']:.2f}%",
    f"Account equity: ${s['current_equity']:,.2f}",
    '',
    f"Trades: {s['total_trades']} total | {s['winners']}W / {s['losers']}L | Win rate: {s['win_rate_pct']:.1f}%",
    f"Avg P&L per trade: {sign(s['avg_pnl_per_trade'])}${s['avg_pnl_per_trade']:.2f}",
    f"Best trade:  {best_str}",
    f"Worst trade: {worst_str}",
    f"Most traded: {most_traded_str}",
    '',
    'Daily breakdown:',
    daily_str,
    '',
    f"Since inception ({s['inception_date']}): Bull {sign(s['cumulative_bull_pct'])}{s['cumulative_bull_pct']:.2f}% | SPY {sign(s['cumulative_spy_pct'])}{s['cumulative_spy_pct']:.2f}% | Alpha: {sign(alpha_total)}{alpha_total:.2f}%",
]

description = '\n'.join(lines)
ok = _post_task(title, description)
print('ClickUp weekly report posted.' if ok else 'ClickUp post failed.')
```

Run it:
```bash
python _weekly_report.py
```

Then clean up temp files:
```bash
del _weekly_stats.py _weekly_report.py _weekly_stats_output.json
```

---

## Part 5: Append weekly journal entry

Append one JSON line to `data/memory/session_journal.jsonl` as the end-of-week record:

```json
{
  "date": "YYYY-MM-DD",
  "session": "weekly_summary",
  "week_start": "YYYY-MM-DD",
  "week_end": "YYYY-MM-DD",
  "total_trades": 0,
  "winners": 0,
  "losers": 0,
  "win_rate_pct": 0.0,
  "total_pnl_dollars": 0.0,
  "week_pnl_pct": 0.0,
  "spy_weekly_pct": 0.0,
  "vs_spy_week_pct": 0.0,
  "best_trade_symbol": "",
  "best_trade_pnl": 0.0,
  "worst_trade_symbol": "",
  "worst_trade_pnl": 0.0,
  "cumulative_bull_pct": 0.0,
  "cumulative_spy_pct": 0.0,
  "weekly_observations": "Your 3-4 sentence synthesis: what worked, what didn't, market regime, and what to prioritize next week."
}
```

Fill `weekly_observations` with a genuine synthesis — not a restatement of the numbers, but what you actually learned from this week and what it means for next Monday's premarket agent.

---

**You are done with trading tasks.** Before exiting, save state to GitHub.

---

## Save State to GitHub

Commit all changed data files and push so next week's routines wake up with current state.

```bash
cd ~/bull
git config user.email "bull-agent@auto"
git config user.name "Bull Agent"

# Stay on the default branch — the clone already starts here. Do NOT create a claude/ branch.
git checkout master

git add data/
git commit -m "weekly-summary: $(date -u +'%Y-%m-%d %H:%M UTC')" || echo "No data changes to commit"

# Land state straight on master so next week's clone picks it up.
git pull --rebase origin master
git push origin master
```

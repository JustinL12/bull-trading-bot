"""Central strategy configuration. All tunable thresholds live here."""

# --- Universe filters ---
PRICE_MIN = 10.0
PRICE_MAX = 1000.0
MIN_AVG_VOLUME = 100_000
REL_VOL_MIN = 1.3          # raised from 1.0 — RS leader breakout strategy

# --- Evening scan: RS Leader + VCP screener ---
RS_20DAY_MIN = 1.10          # 20-day RS vs SPY; institutional accumulation threshold
VCP_ATR_RATIO_MAX = 0.80     # ATR_5day/ATR_20day; < 0.80 = coiling (not yet extended)
VOL_DRY_RATIO_MAX = 0.90     # 5d avg vol / 20d avg vol; < 0.90 = sellers exhausted
HIGH_PROXIMITY_PCT = 0.08    # max pct below 52-week high to qualify
EVENING_SCAN_TOP_N = 10      # number of candidates to output each evening

# --- Entry criteria ---
RSI_MIN = 55          # raised from 50 — tightened for RS leader setups
RSI_MAX = 65          # lowered from 75 — avoid extended names
ATR_MIN_PCT = 0.30    # ATR as % of price; skip if too low-volatility to move
ATR_MAX_PCT = 4.0     # ATR as % of price; skip if more volatile
MACD_CONFIRM_BARS = 2 # histogram must rise for this many consecutive bars
ENTRY_START_HOUR_ET = 9
ENTRY_START_MIN_ET = 31   # was 45 — capture the opening surge
ENTRY_END_HOUR_ET = 10    # was 13
ENTRY_END_MIN_ET = 30     # was 0
MAX_OPEN_POSITIONS = 10

# --- Position sizing ---
RISK_PER_TRADE_PCT = 0.02   # 2% of equity at risk per trade
STOP_ATR_MULTIPLIER = 1.5   # initial stop = entry - (1.5 x ATR)
MAX_POSITION_PCT = 0.05     # hard cap: 5% of equity per position
MIN_NOTIONAL = 200.0        # skip if position value would be below $200

# --- Trailing stop ---
TRAIL_ACTIVATE_ATR = 1.5    # trailing stop activates at +1.5 ATR profit
TRAIL_ATR_MULTIPLIER = 2.0  # trail 2 ATR below highest close since entry

# --- Partial profit ---
PARTIAL_PROFIT_ATR = 2.0    # sell 50% at +2 ATR

# --- Hard intraday exit thresholds ---
RSI_OVERBOUGHT_EXIT = 80

# --- EOD overnight hold criteria ---
OVERNIGHT_GAP_RISK_PCT = 5.0  # simulate this adverse gap; must survive above initial stop
EARNINGS_BLACKOUT_DAYS = 3    # no entry within this many days of earnings
OVERNIGHT_EARNINGS_DAYS = 2   # close position if earnings within this many days

# --- Risk guardrails ---
DAILY_LOSS_LIMIT_PCT = 2.0    # kill switch triggers at -2% of starting equity
MAX_EQUITY_DEPLOYED_PCT = 80.0  # keep at least 20% buying power free
PDT_MAX_DAY_TRADES = 3        # max round-trip day trades per rolling 5-day window
PDT_ACCOUNT_THRESHOLD = 25_000  # PDT rule applies below this equity level

# --- Market regime ---
REGIME_DOWN_MAX_POSITIONS = 5  # when SPY EMA-9 < EMA-21

# --- VIX ---
VIX_SUSPEND_THRESHOLD = 30.0  # suspend all new entries if VIX above this

# --- Memory ---
MEMORY_MIN_SAMPLE = 10        # minimum trades in a bucket before adjustments apply
MEMORY_WIN_RATE_DIVERGENCE = 0.20  # trigger learning if win rate diverges by this much
MEMORY_JOURNAL_ARCHIVE_SESSIONS = 60  # archive journal entries older than this

# --- Finnhub ---
FINNHUB_PM_SORT = True   # sort morning watchlist by Finnhub pre-market % change

# --- Alpaca data ---
INDICATOR_BAR_LIMIT_5MIN = 100   # (legacy) recent intraday bars used for indicator warmup
INDICATOR_BAR_LIMIT_DAILY = 220  # daily bars (need 200 for EMA-200)
# Intraday history is fetched end-anchored (most recent bars). We pull a multi-day
# window both so indicators warm up on current data and so the time-of-day RVOL
# baseline below has enough prior sessions to average over.
INDICATOR_INTRADAY_LOOKBACK_DAYS = 20  # calendar days of intraday history to fetch
RVOL_LOOKBACK_DAYS = 14                # prior trading days for the time-of-day RVOL baseline

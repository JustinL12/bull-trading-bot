"""Central strategy configuration. All tunable thresholds live here."""

# --- Universe filters ---
PRICE_MIN = 10.0
PRICE_MAX = 500.0
MIN_AVG_VOLUME = 500_000
GAP_UP_MIN_PCT = 2.0
REL_VOL_MIN = 1.5

# --- Entry criteria ---
RSI_MIN = 50
RSI_MAX = 75          # memory system may tighten this over time
ATR_MAX_PCT = 4.0     # ATR as % of price; skip if more volatile
MACD_CONFIRM_BARS = 2 # histogram must rise for this many consecutive bars
ENTRY_START_HOUR_ET = 9
ENTRY_START_MIN_ET = 45
ENTRY_END_HOUR_ET = 13
ENTRY_END_MIN_ET = 0
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

# --- Perplexity ---
PERPLEXITY_TIMEOUT_SEC = 10
PERPLEXITY_WATCHLIST_TOP_N = 8   # research top N watchlist symbols
PERPLEXITY_INTRADAY_MIN_GAIN = 50.0  # only check news if unrealized gain > this

# --- Alpaca data ---
INDICATOR_BAR_LIMIT_5MIN = 100   # bars of 5-min data to pull for indicators
INDICATOR_BAR_LIMIT_DAILY = 220  # daily bars (need 200 for EMA-200)

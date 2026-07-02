"""Central strategy configuration. All tunable thresholds live here."""

# --- Universe filters ---
PRICE_MIN = 10.0
PRICE_MAX = 1000.0
MIN_AVG_VOLUME = 500_000      # trend following liquidity floor (higher than old 100k)
MIN_ATR_DOLLAR = 0.05         # minimum ATR in dollars for a valid trend entry

# --- Position sizing ---
MIN_NOTIONAL = 200.0          # skip if position value would be below $200
MAX_EQUITY_DEPLOYED_PCT = 80.0  # keep at least 20% buying power free

# --- Earnings ---
EARNINGS_BLACKOUT_DAYS = 14   # trend following holds for weeks — wider earnings buffer

# --- Risk guardrails ---
DAILY_LOSS_LIMIT_PCT = 2.0    # kill switch triggers at -2% of starting equity

# --- VIX ---
VIX_SUSPEND_THRESHOLD = 40.0  # suspend new entries above this; trend following tolerates moderate vol

# --- Memory ---
MEMORY_MIN_SAMPLE = 10        # minimum trades in a bucket before adjustments apply
MEMORY_WIN_RATE_DIVERGENCE = 0.20  # trigger learning if win rate diverges by this much
MEMORY_JOURNAL_ARCHIVE_SESSIONS = 60  # archive journal entries older than this

# --- Backtesting ---
BACKTEST_UNIVERSE_FILE = "data/universe_trend.json"
TURTLE_RISK_PER_UNIT = 0.01      # 1% equity risk per unit
TURTLE_MAX_POSITIONS = 20        # max simultaneous open positions
ATR_PERIOD = 20                  # ATR period used for sizing and stops
BACKTEST_STOP_ATR_MULT = 2.0     # hard stop = entry - 2 × ATR(20)

# Strategy A: MA Crossover
MA_FAST_SLOW_PAIRS = [(10, 50), (20, 60), (50, 200)]

# Strategy B: Donchian Channel
DONCHIAN_ENTRY_PERIODS = [20, 55]  # N-day high breakout variants
# Exit period = entry period // 2 (10-day or 20-day low)

# Strategy C: Time-Series Momentum
TSMOM_LOOKBACK_MONTHS = [1, 3, 6, 12]  # variants; composite = avg of 3/6/12

# Strategy D: ADX filter (applied on top of A/B/C)
ADX_TREND_THRESHOLD = 25.0       # minimum ADX to confirm trending market
ADX_PERIOD = 14

# --- Alpaca data ---
INDICATOR_BAR_LIMIT_DAILY = 220  # daily bars for indicator computation

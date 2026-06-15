"""
IBKR Put Selling Screener — Phase 1 (spec-aligned)
Data:    yfinance (free) for live option chains + Black-Scholes greeks
IV Rank: IBKR historical implied vol (preferred) via update_iv_history.py,
         falling back to a self-built yfinance snapshot series.
Logic:   gates prune the universe -> weighted composite score ranks survivors
Output:  console + screener_output.csv
Spec:    docs/screening_spec.md  |  Gaps closed: docs/screener_gap_analysis.md

Fundamentals are a GATE (quality screen), not a score. ETFs bypass the
fundamentals/solvency/earnings gates (no financials). Ranking = option edge +
technicals + diversification (correlation vs current holdings). A position
sizer recommends lots under a per-trade risk cap.
"""

import os
import warnings
from collections import Counter
from datetime import date

import numpy as np
import pandas as pd
import yfinance as yf
from scipy.optimize import brentq
from scipy.stats import norm

warnings.filterwarnings('ignore')

# ── Config ────────────────────────────────────────────────────────────────────
# Equity universe: S&P 100 (as of 2025-09; review periodically). yfinance uses
# '-' not '.' for share classes (BRK-B). Quality/liquidity is high across the set.
SP100 = [
    'AAPL', 'ABBV', 'ABT', 'ACN', 'ADBE', 'AIG', 'AMD', 'AMGN', 'AMT', 'AMZN',
    'AVGO', 'AXP', 'BA', 'BAC', 'BK', 'BKNG', 'BLK', 'BMY', 'BRK-B', 'C',
    'CAT', 'CL', 'CMCSA', 'COF', 'COP', 'COST', 'CRM', 'CSCO', 'CVS', 'CVX',
    'DE', 'DHR', 'DIS', 'DUK', 'EMR', 'FDX', 'GD', 'GE', 'GILD', 'GM',
    'GOOG', 'GOOGL', 'GS', 'HD', 'HON', 'IBM', 'INTC', 'INTU', 'ISRG', 'JNJ',
    'JPM', 'KO', 'LIN', 'LLY', 'LMT', 'LOW', 'MA', 'MCD', 'MDLZ', 'MDT',
    'MET', 'META', 'MMM', 'MO', 'MRK', 'MS', 'MSFT', 'NEE', 'NFLX', 'NKE',
    'NOW', 'NVDA', 'ORCL', 'PEP', 'PFE', 'PG', 'PLTR', 'PM', 'PYPL', 'QCOM',
    'RTX', 'SBUX', 'SCHW', 'SO', 'SPG', 'T', 'TGT', 'TMO', 'TMUS', 'TSLA',
    'TXN', 'UBER', 'UNH', 'UNP', 'UPS', 'USB', 'V', 'VZ', 'WFC', 'WMT', 'XOM',
]
# Cross-asset ETFs (bypass the fundamentals/earnings gates).
ETFS = ['SPY', 'QQQ', 'IWM', 'TLT', 'IEF', 'HYG', 'GLD', 'SLV', 'VNQ']
TICKERS = SP100 + ETFS
ETF_TICKERS = {'SPY', 'QQQ', 'IWM', 'DIA', 'TLT', 'IEF', 'SHY', 'LQD', 'HYG', 'AGG',
               'GLD', 'SLV', 'DBC', 'USO', 'VNQ', 'IYR', 'EEM', 'EFA', 'XLE', 'XLF'}

# Map ETFs to a diversification "sleeve"; equities use their yfinance sector.
ETF_SLEEVE = {
    'SPY': 'Equity Index', 'QQQ': 'Equity Index', 'IWM': 'Equity Index', 'DIA': 'Equity Index',
    'TLT': 'Bonds', 'IEF': 'Bonds', 'SHY': 'Bonds', 'AGG': 'Bonds', 'LQD': 'Bonds', 'HYG': 'Bonds',
    'GLD': 'Commodity', 'SLV': 'Commodity', 'DBC': 'Commodity', 'USO': 'Commodity',
    'VNQ': 'REIT', 'IYR': 'REIT', 'EEM': 'Intl Equity', 'EFA': 'Intl Equity',
    'XLE': 'Energy', 'XLF': 'Financials',
}
PER_SLEEVE_TOP = 2   # best-N candidates shown per sleeve in the diversification view

MIN_DTE   = 15
MAX_DTE   = 60
DELTA_MIN = 0.15
DELTA_MAX = 0.30
STRIKE_PCT_LOW  = 0.75
STRIKE_PCT_HIGH = 1.02
RISK_FREE = 0.045

MAX_SPREAD_PCT     = 0.10
MIN_OPEN_INTEREST  = 100   # require some resting liquidity (when OI data is present)
ALLOW_MISSING_OI   = True   # weekends/pre-data: don't reject when OI is unavailable (0/NaN)
MA_REGIME_WINDOW   = 200
# Regime handling — how the 200-MA is used:
#   'gate'       : hard reject if price < 200-MA
#   'downtrend'  : reject ONLY confirmed downtrends (below 50 & 200-MA + 200-MA
#                  falling + near 50-day low). Lets healthy sideways names through.
#   'score'/'off': no regime gate
REGIME_MODE        = 'downtrend'
DOWNTREND_SLOPE    = -0.02
NEAR_LOW_PCT       = 0.03
REQUIRE_SOLVENCY   = True

# Fundamental quality GATE (equities only; ETFs bypass). Missing data never rejects.
REQUIRE_FUNDAMENTALS = True
REQUIRE_FCF_POSITIVE = True
MIN_ROE              = 0.08
MIN_REV_GROWTH       = 0.0
MAX_FORWARD_PE       = 60

# Composite weights (fundamentals are a gate, not scored). Must sum to 1.0.
W_OPTION      = 0.55
W_TECHNICAL   = 0.25
W_DIVERSIFY   = 0.20

# Diversification — score each candidate by correlation to CURRENT holdings.
# Holdings are read from monitor_output.csv (keeps screener Gateway-free).
HOLDINGS_PATH      = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                  'monitor_output.csv')
CORR_LOOKBACK_DAYS = 126   # ~6 months of daily returns

# Position sizing — assignment + drawdown basis.
# risk/contract ≈ strike*100*ASSUMED_DRAWDOWN ; lots = (ACCOUNT*MAX_RISK_PCT)/risk
ACCOUNT_SIZE     = 700_000   # fallback only; auto-overridden by data/account.json
                             # (monitor.py writes IBKR NetLiquidation there)
MAX_RISK_PCT     = 0.03      # max risk per position as % of account
ASSUMED_DRAWDOWN = 0.15      # -X% rule: adverse move below strike where you'd exit (sizing + monitor exposure)

PROFIT_TARGET_PCT = 0.70
HARD_CLOSE_DTE    = 21

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
IV_HISTORY_PATH = os.path.join(_SCRIPT_DIR, 'data', 'iv_history.csv')
ACCOUNT_FILE = os.path.join(_SCRIPT_DIR, 'data', 'account.json')   # written by monitor.py
IV_RANK_LOOKBACK = 252
IV_HISTORY_COLS = ['date', 'ticker', 'iv', 'hv', 'source']

# ── Central config (config.json) — overrides the defaults above; repo-synced ──
import json
CONFIG_PATH = os.path.join(_SCRIPT_DIR, 'config.json')
def load_config():
    try:
        with open(CONFIG_PATH) as f:
            return json.load(f)
    except Exception:
        return {}
CFG = load_config()
def _c(section, key, default):
    sec = CFG.get(section, {}) if isinstance(CFG, dict) else {}
    return sec.get(key, default) if isinstance(sec, dict) else default

W_OPTION    = _c('weights', 'option', W_OPTION)
W_TECHNICAL = _c('weights', 'technical', W_TECHNICAL)
W_DIVERSIFY = _c('weights', 'diversify', W_DIVERSIFY)
MIN_DTE = _c('gates', 'min_dte', MIN_DTE);   MAX_DTE = _c('gates', 'max_dte', MAX_DTE)
DELTA_MIN = _c('gates', 'delta_min', DELTA_MIN);  DELTA_MAX = _c('gates', 'delta_max', DELTA_MAX)
MAX_SPREAD_PCT = _c('gates', 'max_spread_pct', MAX_SPREAD_PCT)
MIN_OPEN_INTEREST = _c('gates', 'min_open_interest', MIN_OPEN_INTEREST)
MIN_ROE = _c('gates', 'min_roe', MIN_ROE)
MIN_REV_GROWTH = _c('gates', 'min_rev_growth', MIN_REV_GROWTH)
MAX_FORWARD_PE = _c('gates', 'max_forward_pe', MAX_FORWARD_PE)
REGIME_MODE = _c('regime', 'mode', REGIME_MODE)
DOWNTREND_SLOPE = _c('regime', 'downtrend_slope', DOWNTREND_SLOPE)
NEW_LOW_TOL = _c('regime', 'new_low_tol', 0.02)         # (legacy) within this % of the 6-mo low
# Breakdown gate — skip ACTIVE sharp breakdowns (steep drop OR a volatility spike),
# regardless of absolute price level. Tunable in config.json -> "regime".
DROP_WINDOW = int(_c('regime', 'drop_window', 10))      # lookback (trading days) for the drop test
DROP_PCT    = _c('regime', 'drop_pct', 0.15)            # block if peak->now fall over the window >= this
VOL_FAST    = int(_c('regime', 'vol_fast', 10))         # short realized-vol window
VOL_SLOW    = int(_c('regime', 'vol_slow', 63))         # baseline realized-vol window (~3 months)
VOL_RATIO   = _c('regime', 'vol_ratio', 1.8)            # block if fast/slow vol >= this ...
VOL_ABS     = _c('regime', 'vol_abs', 0.50)             # ... AND fast vol is at least this (annualized)
OVERSOLD_Z = _c('oversold', 'z_threshold', -2.5)        # price this many sigma below 20-day mean = deeply oversold
OVERSOLD_BONUS = _c('oversold', 'bonus', 8.0)           # points added to technical score when oversold
ACCOUNT_SIZE = _c('sizing', 'account_size_fallback', ACCOUNT_SIZE)
MAX_RISK_PCT = _c('sizing', 'max_risk_pct', MAX_RISK_PCT)
ASSUMED_DRAWDOWN = _c('sizing', 'assumed_drawdown', ASSUMED_DRAWDOWN)
REPORT_TOP_TICKERS = _c('report', 'top_tickers', 5)
REPORT_PER_TICKER  = _c('report', 'per_ticker', 3)
# ─────────────────────────────────────────────────────────────────────────────


# ── Black-Scholes ─────────────────────────────────────────────────────────────

def bs_put_price(S, K, T, r, sigma):
    if T <= 0 or sigma <= 0:
        return max(K - S, 0.0)
    d1 = (np.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * np.sqrt(T))
    d2 = d1 - sigma * np.sqrt(T)
    return K * np.exp(-r * T) * norm.cdf(-d2) - S * norm.cdf(-d1)


def implied_vol(market_price, S, K, T, r):
    if T <= 0 or not market_price or market_price <= 0:
        return None
    if market_price < max(K - S, 0.0) * 0.99:
        return None
    try:
        return brentq(
            lambda sig: bs_put_price(S, K, T, r, sig) - market_price,
            1e-4, 5.0, xtol=1e-5, maxiter=200
        )
    except (ValueError, RuntimeError):
        return None


def bs_put_greeks(S, K, T, r, iv):
    if T <= 0 or iv <= 0 or S <= 0 or K <= 0:
        return None, None
    d1 = (np.log(S / K) + (r + 0.5 * iv**2) * T) / (iv * np.sqrt(T))
    d2 = d1 - iv * np.sqrt(T)
    delta = norm.cdf(d1) - 1.0
    theta = (-(S * norm.pdf(d1) * iv) / (2 * np.sqrt(T))
             + r * K * np.exp(-r * T) * norm.cdf(-d2)) / 365
    return delta, theta

# ─────────────────────────────────────────────────────────────────────────────


def get_next_earnings(yf_t):
    try:
        cal = yf_t.calendar
        if not cal:
            return None
        earn_dates = []
        if isinstance(cal, dict):
            raw = cal.get('Earnings Date', [])
            earn_dates = list(raw) if hasattr(raw, '__iter__') and not isinstance(raw, str) else [raw]
        elif hasattr(cal, 'loc') and 'Earnings Date' in cal.index:
            earn_dates = list(cal.loc['Earnings Date'])
        today = date.today()
        for ed in earn_dates:
            d = ed.date() if hasattr(ed, 'date') else (
                date.fromisoformat(str(ed)[:10]) if ed else None)
            if d and d >= today:
                return d
    except Exception:
        pass
    return None


def get_price(yf_t):
    try:
        p = yf_t.fast_info.last_price or yf_t.fast_info.previous_close
        if p and p > 0:
            return float(p)
    except Exception:
        pass
    try:
        hist = yf_t.history(period='3d')
        if not hist.empty:
            return float(hist['Close'].iloc[-1])
    except Exception:
        pass
    return None


# ── Technicals ────────────────────────────────────────────────────────────────

def get_price_history(yf_t):
    try:
        hist = yf_t.history(period='1y')
        return hist if hist is not None and not hist.empty else None
    except Exception:
        return None


def compute_hv(hist, window=30):
    try:
        close = hist['Close'].dropna()
        if len(close) < window + 1:
            return None
        rets = np.log(close / close.shift(1)).dropna()
        hv = rets.tail(window).std() * np.sqrt(252)
        return float(hv) if hv and hv > 0 else None
    except Exception:
        return None


def compute_technicals(hist):
    """50/200-MA (+slope), RSI(14), Bollinger %B & z-score, 20/50/126-day swing lows."""
    out = {'ma50': None, 'ma200': None, 'ma200_slope': None, 'rsi': None,
           'bb_pctb': None, 'bb_z': None, 'swing_low_20': None,
           'swing_low_50': None, 'swing_low_126': None,
           'dd_fast': None, 'hv_fast': None, 'hv_slow': None, 'vol_ratio': None}
    try:
        close = hist['Close'].dropna()
        low = hist['Low'].dropna() if 'Low' in hist else close
        if len(close) >= 50:
            out['ma50'] = float(close.rolling(50).mean().iloc[-1])
            out['swing_low_50'] = float(low.rolling(50).min().iloc[-1])
        if len(close) >= 126:
            out['swing_low_126'] = float(low.rolling(126).min().iloc[-1])
        if len(close) >= MA_REGIME_WINDOW:
            ma200s = close.rolling(MA_REGIME_WINDOW).mean()
            out['ma200'] = float(ma200s.iloc[-1])
            if len(ma200s.dropna()) > 21:
                prev = ma200s.iloc[-21]
                if prev and prev > 0:
                    out['ma200_slope'] = float((ma200s.iloc[-1] - prev) / prev)
        if len(close) >= 20:
            out['swing_low_20'] = float(low.rolling(20).min().iloc[-1])
            mid = close.rolling(20).mean().iloc[-1]
            sd = close.rolling(20).std().iloc[-1]
            if sd and sd > 0:
                upper, lower = mid + 2 * sd, mid - 2 * sd
                out['bb_pctb'] = float((close.iloc[-1] - lower) / (upper - lower))
                out['bb_z'] = float((close.iloc[-1] - mid) / sd)   # sigma vs 20-day mean
        rets = close.pct_change().dropna()
        if len(close) > DROP_WINDOW:                       # peak->now drawdown over a fast window
            recent = close.tail(DROP_WINDOW + 1)
            out['dd_fast'] = float(close.iloc[-1] / recent.max() - 1.0)
        if len(rets) >= VOL_SLOW:                          # short vs baseline realized vol (annualized)
            out['hv_fast'] = float(rets.tail(VOL_FAST).std() * np.sqrt(252))
            out['hv_slow'] = float(rets.tail(VOL_SLOW).std() * np.sqrt(252))
            if out['hv_slow'] and out['hv_slow'] > 0:
                out['vol_ratio'] = out['hv_fast'] / out['hv_slow']
        if len(close) >= 15:
            diff = close.diff()
            gain = diff.clip(lower=0).rolling(14).mean().iloc[-1]
            loss = (-diff.clip(upper=0)).rolling(14).mean().iloc[-1]
            if loss and loss > 0:
                rs = gain / loss
                out['rsi'] = float(100 - 100 / (1 + rs))
            elif gain and gain > 0:
                out['rsi'] = 100.0
    except Exception:
        pass
    return out


def regime_block(price, tech):
    """Whether to skip a ticker on trend grounds, per REGIME_MODE. -> (bool, reason).

    'breakdown' (default): skip a name only when it is in an ACTIVE sharp breakdown —
    a steep recent drop OR a volatility spike — not merely because it trades at a low.
    The point of avoiding a 'falling knife' is the steepness of the move, not the level:
      • steep drop  — price has fallen >= DROP_PCT from its high over the last DROP_WINDOW days
      • vol spike   — short-window realized vol is >= VOL_RATIO x its baseline AND >= VOL_ABS
    Anything that fell and is now basing (vol back to normal) passes through to the score.
    'gate' = old hard 200-MA rule; 'score'/'off' = no regime gate."""
    if REGIME_MODE in ('score', 'off'):
        return False, ''
    if REGIME_MODE == 'gate':
        ma200 = tech.get('ma200')
        if ma200 is None:
            return False, ''
        return (price < ma200), f"price ${price:.2f} < 200-MA ${ma200:.2f}"
    # 'breakdown' (also accepts legacy 'downtrend')
    dd = tech.get('dd_fast')
    if dd is not None and dd <= -DROP_PCT:
        return True, f"steep drop {dd*100:.0f}% over {DROP_WINDOW}d"
    hv_fast, vr = tech.get('hv_fast'), tech.get('vol_ratio')
    if hv_fast is not None and vr is not None and vr >= VOL_RATIO and hv_fast >= VOL_ABS:
        return True, (f"vol spike: {VOL_FAST}d HV {hv_fast*100:.0f}% = {vr:.1f}x "
                      f"{VOL_SLOW}d baseline")
    return False, ''


# ── Fundamentals ──────────────────────────────────────────────────────────────

def get_fundamentals(yf_t):
    f = {'forward_pe': None, 'peg': None, 'roe': None, 'rev_growth': None,
         'div_yield': None, 'payout': None, 'debt_to_equity': None,
         'current_ratio': None, 'fcf': None, 'quote_type': None, 'sector': None}
    try:
        info = yf_t.info or {}
        f['sector']         = info.get('sector')
        f['forward_pe']     = info.get('forwardPE')
        f['peg']            = info.get('pegRatio') or info.get('trailingPegRatio')
        f['roe']            = info.get('returnOnEquity')
        f['rev_growth']     = info.get('revenueGrowth')
        f['div_yield']      = info.get('dividendYield')
        f['payout']         = info.get('payoutRatio')
        f['debt_to_equity'] = info.get('debtToEquity')
        f['current_ratio']  = info.get('currentRatio')
        f['fcf']            = info.get('freeCashflow')
        f['quote_type']     = info.get('quoteType')
    except Exception:
        pass
    return f


def is_etf(ticker, fund):
    return (fund.get('quote_type') or '').upper() == 'ETF' or ticker in ETF_TICKERS


def sleeve(ticker, fund):
    """Diversification sleeve: ETFs by asset-class map, equities by yfinance sector."""
    if is_etf(ticker, fund):
        return ETF_SLEEVE.get(ticker, 'ETF')
    return fund.get('sector') or 'Equity'


def solvency_ok(f):
    de = f.get('debt_to_equity')
    cr = f.get('current_ratio')
    fcf = f.get('fcf')
    distressed = False
    if de is not None and de > 400:
        if (cr is not None and cr < 1.0) or (fcf is not None and fcf < 0):
            distressed = True
    if fcf is not None and fcf < 0 and de is not None and de > 250:
        distressed = True
    return not distressed


def fundamental_ok(f):
    """Quality GATE -> (bool, reason). Only fails on PRESENT metrics below the bar."""
    fcf = f.get('fcf')
    rg  = f.get('rev_growth')
    roe = f.get('roe')
    pe  = f.get('forward_pe')
    if REQUIRE_FCF_POSITIVE and fcf is not None and fcf <= 0:
        return False, "FCF <= 0"
    if rg is not None and rg < MIN_REV_GROWTH:
        return False, f"revenue growth {rg:.1%} < {MIN_REV_GROWTH:.0%}"
    if roe is not None and roe < MIN_ROE:
        return False, f"ROE {roe:.1%} < {MIN_ROE:.0%}"
    if pe is not None and pe > MAX_FORWARD_PE:
        return False, f"forward P/E {pe:.0f} > {MAX_FORWARD_PE}"
    return True, ""


# ── Diversification (correlation vs current holdings) ──────────────────────────

def load_holdings(path=HOLDINGS_PATH):
    """Unique underlying tickers from monitor_output.csv (current positions)."""
    if not os.path.exists(path):
        return []
    try:
        df = pd.read_csv(path)
        col = 'ticker' if 'ticker' in df.columns else df.columns[0]
        return sorted(df[col].dropna().astype(str).str.upper().unique().tolist())
    except Exception:
        return []


def fetch_returns(tickers, lookback_days=CORR_LOOKBACK_DAYS):
    """ticker -> daily-return Series (last ~6 months). Skips anything that fails."""
    out = {}
    for t in tickers:
        try:
            h = yf.Ticker(t).history(period='1y')
            if h is not None and not h.empty:
                r = h['Close'].pct_change().dropna().tail(lookback_days)
                if len(r) > 20:
                    out[t] = r
        except Exception:
            pass
    return out


def diversification_score(cand_ret, holdings_returns):
    """Avg correlation of candidate to current holdings -> 0-100 (lower corr = higher).
    corr -1 -> 100, 0 -> 50, +1 -> 0. None when no usable data."""
    if cand_ret is None or not holdings_returns:
        return None, None
    corrs = []
    for hr in holdings_returns.values():
        try:
            c = cand_ret.corr(hr)
            if c == c:                      # not NaN
                corrs.append(c)
        except Exception:
            pass
    if not corrs:
        return None, None
    avg = float(np.mean(corrs))
    score = float(np.clip((1 - avg) / 2 * 100, 0, 100))
    return round(score, 1), round(avg, 2)


# ── IV history store / IV Rank ────────────────────────────────────────────────

def load_iv_history():
    if not os.path.exists(IV_HISTORY_PATH):
        return None
    try:
        df = pd.read_csv(IV_HISTORY_PATH)
    except Exception:
        return None
    if 'iv' not in df.columns and 'atm_iv' in df.columns:
        df = df.rename(columns={'atm_iv': 'iv'})
    if 'source' not in df.columns:
        df['source'] = 'yf'
    if 'hv' not in df.columns:
        df['hv'] = np.nan
    return df


def record_iv(rows):
    if not rows:
        return
    today = str(date.today())
    new = pd.DataFrame([{'date': today, 'ticker': r['ticker'],
                         'iv': r['iv'], 'hv': r.get('hv'), 'source': 'yf'}
                        for r in rows])
    if os.path.exists(IV_HISTORY_PATH):
        old = load_iv_history()
        if old is not None:
            old = old[~((old['date'] == today) & (old['source'] == 'yf')
                        & (old['ticker'].isin(new['ticker'])))]
            new = pd.concat([old, new], ignore_index=True)
    os.makedirs(os.path.dirname(IV_HISTORY_PATH), exist_ok=True)
    new = new[[c for c in IV_HISTORY_COLS if c in new.columns]]
    new.to_csv(IV_HISTORY_PATH, index=False)


def ticker_iv_rank(hist_df, ticker):
    if hist_df is None:
        return None, None, None, None
    sub = hist_df[hist_df['ticker'] == ticker]
    for src in ('ibkr', 'yf'):
        s = (sub[sub['source'] == src].dropna(subset=['iv'])
             .sort_values('date').tail(IV_RANK_LOOKBACK))
        if len(s) >= 20:
            iv_vals = s['iv'].astype(float)
            lo, hi = iv_vals.min(), iv_vals.max()
            latest_iv = float(iv_vals.iloc[-1])
            hv_nonan = s['hv'].dropna()
            latest_hv = float(hv_nonan.iloc[-1]) if not hv_nonan.empty else None
            rank = (float(np.clip((latest_iv - lo) / (hi - lo) * 100, 0, 100))
                    if hi > lo else None)
            return rank, src, latest_iv, latest_hv
    return None, None, None, None


def latest_ibkr_hv(hist_df, ticker):
    if hist_df is None:
        return None
    sub = hist_df[(hist_df['ticker'] == ticker) & (hist_df['source'] == 'ibkr')].dropna(subset=['hv'])
    if sub.empty:
        return None
    try:
        return float(sub.sort_values('date')['hv'].iloc[-1])
    except Exception:
        return None


def annualized_return(premium, strike, dte):
    if not premium or not strike or not dte or dte <= 0:
        return None
    return (premium / strike) / dte * 365 * 100


def get_account_size(default=ACCOUNT_SIZE):
    """Account NetLiquidation from data/account.json (monitor writes it), else fallback."""
    try:
        import json
        with open(ACCOUNT_FILE) as f:
            v = json.load(f).get('net_liquidation')
        return float(v) if v and float(v) > 0 else default
    except Exception:
        return default


def save_account_size(value, account=''):
    """Persist NetLiquidation so the (Gateway-free) screener can size on the real account."""
    try:
        import json
        os.makedirs(os.path.dirname(ACCOUNT_FILE), exist_ok=True)
        with open(ACCOUNT_FILE, 'w') as f:
            json.dump({'net_liquidation': float(value), 'account': account,
                       'asof': str(date.today())}, f)
        return True
    except Exception:
        return False


def position_size(strike, premium):
    """Recommended lots under the per-trade risk cap (assignment+drawdown basis).
    Returns (lots, collateral_per_contract, risk_per_contract)."""
    risk_ct = strike * 100 * ASSUMED_DRAWDOWN
    budget  = ACCOUNT_SIZE * MAX_RISK_PCT
    lots = int(budget // risk_ct) if risk_ct > 0 else 0
    return lots, round(strike * 100), round(risk_ct)


def _num(x, default=0.0):
    """NaN/None-safe float (yfinance puts NaN in volume/OI/bid/ask)."""
    try:
        x = float(x)
    except (TypeError, ValueError):
        return default
    return x if x == x else default


# ── Per-ticker scan ───────────────────────────────────────────────────────────

def screen_ticker(ticker, iv_hist_df, holdings_returns, verbose=True):
    _p = print if verbose else (lambda *a, **k: None)
    today = date.today()
    yf_t  = yf.Ticker(ticker)

    price = get_price(yf_t)
    if not price:
        _p(f"{ticker:<6} SKIP: no price")
        return [], None

    hist = get_price_history(yf_t)
    tech = compute_technicals(hist) if hist is not None else {}
    hv_yf = compute_hv(hist) if hist is not None else None
    fund = get_fundamentals(yf_t)
    etf  = is_etf(ticker, fund)
    sl   = sleeve(ticker, fund)

    ibkr_hv = latest_ibkr_hv(iv_hist_df, ticker)
    hv_used = ibkr_hv if ibkr_hv else hv_yf

    # candidate return series (for diversification) — computed once per ticker
    cand_ret = None
    if hist is not None and len(hist) > 5:
        cand_ret = hist['Close'].pct_change().dropna().tail(CORR_LOOKBACK_DAYS)
    div_score, div_corr = diversification_score(cand_ret, holdings_returns)

    blocked, why = regime_block(price, tech)
    if blocked:
        _p(f"{ticker:<6} ${price:>8.2f} | SKIP regime[{REGIME_MODE}]: {why}")
        return [], None

    # ETFs bypass solvency / fundamentals / earnings gates (no financials)
    if not etf:
        if REQUIRE_SOLVENCY and not solvency_ok(fund):
            _p(f"{ticker:<6} ${price:>8.2f} | SKIP solvency: distressed balance sheet")
            return [], None
        if REQUIRE_FUNDAMENTALS:
            ok, fund_why = fundamental_ok(fund)
            if not ok:
                _p(f"{ticker:<6} ${price:>8.2f} | SKIP fundamentals: {fund_why}")
                return [], None

    earnings = None if etf else get_next_earnings(yf_t)
    hv_str = f"{hv_used:.2f}" if hv_used else "n/a"

    results, atm_iv_tracker, atm_best_dist = [], None, None
    reasons, scanned, exps_used = Counter(), 0, 0

    for exp_str in yf_t.options:
        exp_date = date.fromisoformat(exp_str)
        dte      = (exp_date - today).days
        if not (MIN_DTE <= dte <= MAX_DTE):
            continue
        if earnings and today < earnings <= exp_date:
            reasons['earnings_expiry'] += 1
            continue
        exps_used += 1

        T    = dte / 365.0
        try:
            puts = yf_t.option_chain(exp_str).puts
        except Exception:
            continue
        if puts is None or len(puts) == 0:
            continue

        for _, row in puts.iterrows():
            strike = float(row['strike'])
            if not (price * STRIKE_PCT_LOW <= strike <= price * STRIKE_PCT_HIGH):
                continue
            scanned += 1

            bid  = _num(row.get('bid'))
            ask  = _num(row.get('ask'))
            last = _num(row.get('lastPrice'))
            oi   = int(_num(row.get('openInterest')))
            vol  = int(_num(row.get('volume')))
            opt_price = (bid + ask) / 2 if bid > 0 and ask > 0 else last
            if opt_price <= 0:
                reasons['no_price'] += 1
                continue

            if bid > 0 and ask > 0:
                spread_pct = (ask - bid) / ((ask + bid) / 2)
                if spread_pct > MAX_SPREAD_PCT:
                    reasons['spread'] += 1
                    continue
            else:
                spread_pct = None
            if oi < MIN_OPEN_INTEREST:
                if ALLOW_MISSING_OI and oi <= 0:
                    reasons['oi_missing_allowed'] += 1
                else:
                    reasons['open_interest'] += 1
                    continue

            iv = implied_vol(opt_price, price, strike, T, RISK_FREE)
            if not iv or iv <= 0:
                reasons['no_iv'] += 1
                continue

            delta, theta = bs_put_greeks(price, strike, T, RISK_FREE, iv)
            if delta is None:
                reasons['no_greeks'] += 1
                continue
            if not (DELTA_MIN <= abs(delta) <= DELTA_MAX):
                reasons['delta_band'] += 1
                continue

            dist = abs(strike - price)
            if atm_best_dist is None or dist < atm_best_dist:
                atm_best_dist, atm_iv_tracker = dist, iv

            iv_hv = (iv / hv_used) if (hv_used and hv_used > 0) else None
            ann_ret = annualized_return(opt_price, strike, dte)
            swing_low = tech.get('swing_low_20')
            support_margin = ((swing_low - strike) / price) if swing_low else None
            lots, collat_ct, risk_ct = position_size(strike, opt_price)
            otm_pct = round((price - strike) / price * 100, 1)     # downside cushion to strike

            results.append({
                'ticker':      ticker,
                'etf':         etf,
                'sleeve':      sl,
                'type':        'P',
                'stock_price': round(price, 2),
                'otm_%':       otm_pct,
                'expiry':      exp_date.strftime('%Y-%m-%d'),
                'dte':         dte,
                'earnings':    str(earnings) if earnings else None,
                'strike':      strike,
                'mid':         round(opt_price, 2),
                'spread_pct':  round(spread_pct * 100, 1) if spread_pct is not None else None,
                'open_int':    oi,
                'volume':      vol,
                'delta':       round(delta, 3),
                'theta':       round(theta, 4),
                'iv_pct':      round(iv * 100, 1),
                'hv_pct':      round(hv_used * 100, 1) if hv_used else None,
                'iv_hv':       round(iv_hv, 2) if iv_hv else None,
                'ann_ret_pct': round(ann_ret, 1) if ann_ret else None,
                'lots':        lots,
                'collat_ct':   collat_ct,
                'risk_ct':     risk_ct,
                'income':      round(opt_price * 100 * lots),
                'div_corr':    div_corr,
                'div_score':   div_score,
                'fwd_pe':      round(fund['forward_pe'], 1) if fund.get('forward_pe') else None,
                'roe':         round(fund['roe'], 3) if fund.get('roe') else None,
                'bb_z':        round(tech['bb_z'], 2) if tech.get('bb_z') is not None else None,
                '_rsi':        tech.get('rsi'),
                '_bb_pctb':    tech.get('bb_pctb'),
                '_support_margin': support_margin,
                'div_yield':   round(fund['div_yield'] * 100, 2) if fund.get('div_yield') else None,
            })

    tag = ' ETF' if etf else ''
    earn_str = str(earnings) if earnings else ('—' if etf else 'n/a')
    div_str = f"div {div_score:.0f}(corr {div_corr:+.2f})" if div_score is not None else "div n/a"
    summary = (f"{ticker:<6}{tag:<4} ${price:>8.2f} | earn {earn_str} | "
               f"HV {hv_str}{'(ibkr)' if ibkr_hv else ''} | {div_str} | {len(results):>2} cand")
    if not results:
        summary += f"  [0 passed; rejects: {dict(reasons)}]"
    _p(summary)

    atm_row = ({'ticker': ticker, 'iv': round(atm_iv_tracker, 4),
                'hv': round(hv_yf, 4) if hv_yf else None}
               if atm_iv_tracker else None)
    return results, atm_row


# ── Scoring (option + technical + diversification; fundamentals are a gate) ─────

def _pct_rank(series, higher_is_better=True):
    r = series.rank(pct=True)
    if not higher_is_better:
        r = 1 - r
    return (r * 100)


def _rsi_score(rsi):
    if rsi is None or pd.isna(rsi):
        return np.nan
    score = max(0.0, 100 - abs(rsi - 40) * 2)
    if rsi < 25 or rsi > 75:
        score *= 0.5
    return score


def _bb_score(pctb):
    if pctb is None or pd.isna(pctb):
        return np.nan
    return float(np.clip((1 - pctb) * 100, 0, 100))


def score_candidates(df, iv_hist_df):
    if df.empty:
        return df

    rank_map = {t: ticker_iv_rank(iv_hist_df, t) for t in df['ticker'].unique()}
    df['iv_rank'] = pd.to_numeric(df['ticker'].map(lambda t: rank_map[t][0]),
                                  errors='coerce').round(1)
    df['iv_src']  = df['ticker'].map(lambda t: rank_map[t][1])

    # ---- Option-edge bucket ----
    opt_parts = []
    if df['iv_rank'].notna().any():
        opt_parts.append(_pct_rank(df['iv_rank'], True))
    if df['iv_hv'].notna().any():
        opt_parts.append(_pct_rank(df['iv_hv'], True))
    if df['ann_ret_pct'].notna().any():
        opt_parts.append(_pct_rank(df['ann_ret_pct'], True))
    if df['theta'].notna().any():
        opt_parts.append(_pct_rank(df['theta'].abs(), True))
    df['score_option'] = (pd.concat(opt_parts, axis=1).mean(axis=1)
                          if opt_parts else np.nan)

    # ---- Technical bucket ----
    tech_parts = []
    rsi_s = df['_rsi'].apply(_rsi_score)
    if rsi_s.notna().any():
        tech_parts.append(rsi_s)
    bb_s = df['_bb_pctb'].apply(_bb_score)
    if bb_s.notna().any():
        tech_parts.append(bb_s)
    if df['_support_margin'].notna().any():
        tech_parts.append(_pct_rank(df['_support_margin'], True))
    df['score_technical'] = (pd.concat(tech_parts, axis=1).mean(axis=1)
                             if tech_parts else np.nan)
    # Mean-reversion bonus: deeply oversold (price <= OVERSOLD_Z sigma below 20-day mean)
    if 'bb_z' in df.columns:
        z = pd.to_numeric(df['bb_z'], errors='coerce')
        bonus = ((z <= OVERSOLD_Z) & df['score_technical'].notna()).astype(float) * OVERSOLD_BONUS
        df['score_technical'] = (df['score_technical'] + bonus).clip(upper=100)

    # ---- Diversification bucket (absolute 0-100; NaN when no holdings) ----
    df['score_diversify'] = (pd.to_numeric(df['div_score'], errors='coerce')
                             if 'div_score' in df.columns else np.nan)

    # ---- Weighted composite (renormalize over available buckets) ----
    buckets = [('score_option', W_OPTION),
               ('score_technical', W_TECHNICAL),
               ('score_diversify', W_DIVERSIFY)]

    def _composite(row):
        num = den = 0.0
        for col, w in buckets:
            v = row[col]
            if pd.notna(v):
                num += v * w
                den += w
        return round(num / den, 1) if den > 0 else np.nan

    df['score'] = df.apply(_composite, axis=1)
    for c in ('score_option', 'score_technical', 'score_diversify'):
        df[c] = df[c].round(1)
    return df


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    global ACCOUNT_SIZE
    acct_from_file = os.path.exists(ACCOUNT_FILE)
    ACCOUNT_SIZE = get_account_size()
    acct_src = "IBKR" if acct_from_file else "default — run monitor.py to fetch real NLV"
    print("=" * 74)
    print("PUT SELLING SCREENER  |  spec-aligned  |  yfinance + Black-Scholes")
    print(f"Gates: {MIN_DTE}-{MAX_DTE} DTE | |delta| {DELTA_MIN}-{DELTA_MAX} | "
          f"spread<{int(MAX_SPREAD_PCT*100)}% | OI>={MIN_OPEN_INTEREST} | "
          f"regime={REGIME_MODE} | solvency+fundamentals (equities)")
    print(f"Score: option {int(W_OPTION*100)}% / technical {int(W_TECHNICAL*100)}% "
          f"/ diversify {int(W_DIVERSIFY*100)}%   |   "
          f"sizing: {int(MAX_RISK_PCT*100)}% risk on ${ACCOUNT_SIZE:,.0f} "
          f"({int(ASSUMED_DRAWDOWN*100)}% drawdown, acct: {acct_src})")
    print("=" * 74)

    iv_hist_df = load_iv_history()
    if iv_hist_df is None:
        print("Note: no IV history yet. Run update_iv_history.py (IBKR) for full-year IV Rank.")
    else:
        print(f"IV history loaded: {iv_hist_df['source'].value_counts().to_dict()}")

    holdings = load_holdings()
    holdings_returns = fetch_returns(holdings) if holdings else {}
    if holdings_returns:
        print(f"Diversification baseline: {len(holdings_returns)} holdings "
              f"({', '.join(sorted(holdings_returns))})\n")
    else:
        print("Diversification: no holdings found — diversification score skipped.\n")

    all_results, atm_rows = [], []
    for ticker in TICKERS:
        rows, atm = screen_ticker(ticker, iv_hist_df, holdings_returns)
        all_results.extend(rows)
        if atm:
            atm_rows.append(atm)

    record_iv(atm_rows)

    if not all_results:
        print("\nNo candidates matched the gates.")
        return

    df = pd.DataFrame(all_results)
    df = score_candidates(df, iv_hist_df)
    df = df.sort_values('score', ascending=False, na_position='last').reset_index(drop=True)

    display_cols = ['ticker', 'type', 'stock_price', 'otm_%', 'expiry', 'dte', 'earnings',
                    'strike', 'mid',
                    'lots', 'open_int', 'delta', 'iv_pct', 'iv_hv', 'bb_z',
                    'iv_rank', 'iv_src', 'ann_ret_pct', 'div_corr',
                    'score_option', 'score_technical', 'score_diversify', 'score']
    display_cols = [c for c in display_cols if c in df.columns]

    # Top tickers by best score (variety), top contracts each, sorted by ticker then score
    order = (df.groupby('ticker')['score'].max()
               .sort_values(ascending=False).head(REPORT_TOP_TICKERS).index.tolist())
    top = (df[df['ticker'].isin(order)]
             .sort_values('score', ascending=False)
             .groupby('ticker', as_index=False).head(REPORT_PER_TICKER)
             .sort_values(['ticker', 'score'], ascending=[True, False]))
    print("\n" + "=" * 74)
    print(f"TOP CANDIDATES  ({len(order)} tickers x {REPORT_PER_TICKER}, of {len(df)} total; "
          f"by ticker, then score)")
    print("=" * 74)
    print(top[display_cols].to_string(index=False))

    # Best candidate(s) per sleeve — for building a diversified book across asset classes
    if 'sleeve' in df.columns:
        best = (df.sort_values('score', ascending=False)
                  .groupby('sleeve', as_index=False).head(PER_SLEEVE_TOP)
                  .sort_values('score', ascending=False))
        sleeve_cols = ['sleeve', 'ticker', 'type', 'stock_price', 'otm_%', 'expiry', 'dte',
                       'strike', 'mid', 'lots', 'delta', 'iv_hv',
                       'iv_rank', 'ann_ret_pct', 'div_corr',
                       'score_option', 'score_technical', 'score_diversify', 'score']
        sleeve_cols = [c for c in sleeve_cols if c in best.columns]
        print("\n" + "=" * 74)
        print(f"BEST PER SLEEVE  (top {PER_SLEEVE_TOP}/sleeve — pick across sleeves to diversify)")
        print("=" * 74)
        print(best[sleeve_cols].to_string(index=False))

    df.to_csv('screener_output.csv', index=False)
    print(f"\nSaved -> screener_output.csv  ({len(df)} rows)")


if __name__ == '__main__':
    main()

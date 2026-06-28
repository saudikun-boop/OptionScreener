"""
backtest.py — free, point-in-time-ish backtest of the cash-secured put strategy.

WHAT THIS DOES (and, just as importantly, what it does NOT)
-----------------------------------------------------------
Goal: answer "does selecting puts by our TECHNICAL score beat NOT selecting?"
before we ever tune weights. It is a deliberately simple, honest first pass.

Method (all reuse screener.py so we test the model we actually trade):
  • Universe: screener's equities (S&P100 + EXTRA). ETFs handled only as benchmarks.
  • Monthly cycles: enter on each monthly expiry, hold ONE month to the next
    expiry (hold-to-expiry — no mid-life management, so we need no option price path).
  • Each name each cycle: sell a ~TARGET_DELTA, 1-month cash-secured put.
      - strike: delta-targeted (closed form) then snapped to a strike grid
      - entry premium: Black-Scholes priced at IV = HV(30d) * VRP_MULT
                       (we have NO historical option prices for free; this is the
                        key simplification — see caveats)
      - fill at mid, minus COMMISSION_PER_SHARE
  • P&L (hold to expiry):  pnl_share = net_premium - max(strike - S_expiry, 0)
    return on collateral = pnl_share / strike   (cash-secured)
  • Strategies compared per cycle:
      ScoreTopN     – top N names by technical score (what selection buys you)
      ScoreBotN     – bottom N (sanity: should underperform if score works)
      EqualWeight   – mean of the WHOLE pool (the "no selection" benchmark)
      QQQ / SPY     – index buy-hold over the same window (reference only)
  • Diagnostics (LABELED BIASED):
      - technical-score quintiles Q1..Q5 (monotonicity of the score)
      - quality quintiles using STATIC CURRENT fundamentals — a one-sided test
        (lookahead + survivorship bias toward "quality works"); use only to
        DISQUALIFY the bucket, never to validate it.

CAVEATS (read before trusting any number):
  • Premiums are SIMULATED from HV*VRP, not real option prices. Because IV is
    modeled as a constant multiple of HV, the OPTION-EDGE bucket (IV rank, IV/HV)
    cannot be honestly tested here — that needs real historical IV (paid) or our
    ~1yr iv_history.csv window. This script tests the TECHNICAL bucket only.
  • Survivorship bias: universe is TODAY's membership.
  • No real bid/ask, OI, or earnings-date history → those gates are not applied.
  • Treat absolute CAGR with heavy skepticism; trust RELATIVE differences
    (TopN vs EqualWeight vs BotN) far more.

RUN:
  python code/backtest.py                 # real run (needs internet; do this on your PC)
  python code/backtest.py --start 2012-01-01 --top 8
  python code/backtest.py --selftest      # offline: synthetic prices, verifies the math
"""

import os
import sys
import argparse
from datetime import date, timedelta

import numpy as np
import pandas as pd
from scipy.stats import norm

import screener as S   # reuse BS pricing, technicals, scoring helpers, universe

# ── Parameters (CLI-overridable; a few also read config.json -> "backtest") ─────
_BT = S.CFG.get('backtest', {}) if isinstance(S.CFG, dict) else {}
START_DEFAULT        = _BT.get('start', '2010-01-01')
TARGET_DELTA         = float(_BT.get('target_delta', 0.20))   # |delta| of the put we sell
DTE_NOMINAL          = int(_BT.get('dte', 30))                # nominal hold (cycles use real expiries)
VRP_MULT             = float(_BT.get('vrp_mult', 1.15))       # modeled IV = HV * this (variance risk premium)
TOP_N                = int(_BT.get('top_n', 10))              # names selected by score each cycle
COMMISSION_PER_SHARE = float(_BT.get('commission_per_share', 0.0065))  # $0.65 / contract
RISK_FREE            = S.RISK_FREE
HV_WINDOW            = 30
MIN_HV               = 0.05                                   # ignore degenerate / dead names
BENCHMARKS           = ['QQQ', 'SPY']


# ── Strike helpers ──────────────────────────────────────────────────────────────

def strike_grid_step(s):
    """Approximate listed-strike spacing for a given underlying price."""
    if s < 25:   return 0.5
    if s < 50:   return 1.0
    if s < 200:  return 2.5
    return 5.0


def delta_target_strike(S0, T, r, sigma, target_delta):
    """Closed-form strike whose BS put |delta| ~= target_delta, snapped to the grid.
       |delta_put| = 1 - N(d1) = target  ->  d1 = Phi^-1(1 - target)
       K = S * exp((r + 0.5 sigma^2) T - d1 * sigma * sqrt(T))"""
    if T <= 0 or sigma <= 0 or S0 <= 0:
        return None
    d1 = norm.ppf(1.0 - target_delta)
    k = S0 * np.exp((r + 0.5 * sigma ** 2) * T - d1 * sigma * np.sqrt(T))
    step = strike_grid_step(S0)
    k = round(k / step) * step
    return float(k) if k > 0 else None


# ── Calendar ────────────────────────────────────────────────────────────────────

def third_fridays(start, end):
    """Standard monthly option expiries (3rd Friday) between start and end (date objs)."""
    out = []
    y, m = start.year, start.month
    while date(y, m, 1) <= end:
        first = date(y, m, 1)
        # weekday(): Mon=0..Sun=6; Friday=4. First Friday then +14 days.
        first_fri = first + timedelta(days=(4 - first.weekday()) % 7)
        out.append(first_fri + timedelta(days=14))
        m += 1
        if m > 12:
            m, y = 1, y + 1
    return [d for d in out if start <= d <= end]


def snap(idx_dates, target):
    """Last available trading date <= target; None if none."""
    prior = idx_dates[idx_dates <= pd.Timestamp(target)]
    return prior[-1] if len(prior) else None


# ── Price data ──────────────────────────────────────────────────────────────────

def fetch_prices(tickers, start, end):
    """ticker -> OHLC DataFrame (real data; run on a machine with internet)."""
    import yfinance as yf
    out = {}
    for i, t in enumerate(tickers, 1):
        try:
            h = yf.Ticker(t).history(start=start, end=end, auto_adjust=True)
            if h is not None and not h.empty and 'Close' in h:
                h.index = pd.to_datetime(h.index).tz_localize(None)
                out[t] = h[['Open', 'High', 'Low', 'Close']].dropna()
        except Exception as e:
            print(f"  ! {t}: {e}")
        if i % 25 == 0:
            print(f"  fetched {i}/{len(tickers)}")
    return out


def synthetic_prices(tickers, start, end, seed=7):
    """Offline GBM price paths for --selftest (no network)."""
    rng = np.random.default_rng(seed)
    days = pd.bdate_range(start, end)
    out = {}
    for j, t in enumerate(tickers):
        mu, sig = rng.uniform(0.02, 0.12), rng.uniform(0.18, 0.55)   # annual drift / vol
        dt = 1 / 252
        shocks = rng.normal((mu - 0.5 * sig ** 2) * dt, sig * np.sqrt(dt), len(days))
        close = float(rng.uniform(20, 300)) * np.exp(np.cumsum(shocks))
        df = pd.DataFrame({'Close': close}, index=days)
        df['Low'] = df['Close'] * (1 - rng.uniform(0, 0.01, len(days)))
        df['High'] = df['Close'] * (1 + rng.uniform(0, 0.01, len(days)))
        df['Open'] = df['Close'].shift(1).fillna(df['Close'])
        out[t] = df
    return out


# ── Static (biased) quality score for the quintile diagnostic ───────────────────

def static_quality(tickers):
    """CURRENT fundamentals -> quality score + quintile per ticker. BIASED (lookahead
    + survivorship); a one-sided disqualifier only. Returns DataFrame or None."""
    import yfinance as yf
    rows = []
    for t in tickers:
        f = S.get_fundamentals(yf.Ticker(t)) or {}
        rows.append({'ticker': t, 'roe': f.get('roe'), 'rev_growth': f.get('rev_growth'),
                     'current_ratio': f.get('current_ratio'), 'debt_to_equity': f.get('debt_to_equity')})
    df = pd.DataFrame(rows)
    parts = []
    for col, higher in [('roe', True), ('rev_growth', True),
                        ('current_ratio', True), ('debt_to_equity', False)]:
        s = pd.to_numeric(df[col], errors='coerce')
        if s.notna().any():
            parts.append(S._pct_rank(s, higher))
    if not parts:
        return None
    df['quality'] = pd.concat(parts, axis=1).mean(axis=1)
    df = df.dropna(subset=['quality'])
    if len(df) < 5:
        return None
    df['quality_q'] = pd.qcut(df['quality'].rank(method='first'), 5, labels=[1, 2, 3, 4, 5])
    return df[['ticker', 'quality', 'quality_q']]


# ── Per-cycle trade construction ────────────────────────────────────────────────

def build_cycle(prices, entry_d, expiry_d):
    """Return a DataFrame of one simulated put per eligible ticker for this cycle."""
    rows = []
    T = max((expiry_d - entry_d).days, 1) / 365.0
    for t, df in prices.items():
        idx = df.index
        e0 = snap(idx, entry_d)
        e1 = snap(idx, expiry_d)
        if e0 is None or e1 is None or e0 >= e1:
            continue
        hist = df.loc[:e0]
        if len(hist) < S.MA_REGIME_WINDOW // 2:
            continue
        S0 = float(df.loc[e0, 'Close'])
        Sx = float(df.loc[e1, 'Close'])
        hv = S.compute_hv(hist, HV_WINDOW)
        if not hv or hv < MIN_HV:
            continue
        iv = hv * VRP_MULT
        K = delta_target_strike(S0, T, r=RISK_FREE, sigma=iv, target_delta=TARGET_DELTA)
        if not K:
            continue
        delta, _ = S.bs_put_greeks(S0, K, T, RISK_FREE, iv)
        prem = S.bs_put_price(S0, K, T, RISK_FREE, iv)
        if not prem or prem <= 0:
            continue
        net = prem - COMMISSION_PER_SHARE
        pnl_share = net - max(K - Sx, 0.0)
        ret = pnl_share / K                                   # return on cash-secured collateral
        tech = S.compute_technicals(hist)
        swing = tech.get('swing_low_20')
        rows.append({
            'ticker': t, 'entry': e0.date(), 'expiry': e1.date(),
            'S0': round(S0, 2), 'Sx': round(Sx, 2), 'strike': K,
            'delta': round(delta, 3) if delta is not None else None,
            'premium': round(prem, 3), 'ret': ret, 'assigned': Sx < K,
            'rsi': tech.get('rsi'), 'bb_pctb': tech.get('bb_pctb'), 'bb_z': tech.get('bb_z'),
            'support_margin': ((swing - K) / S0) if swing else None,
        })
    cyc = pd.DataFrame(rows)
    if cyc.empty:
        return cyc
    # Technical score — identical construction to screener.score_candidates' technical bucket.
    parts = []
    rsi_s = cyc['rsi'].apply(S._rsi_score)
    if rsi_s.notna().any():
        parts.append(rsi_s)
    bb_s = cyc['bb_pctb'].apply(S._bb_score)
    if bb_s.notna().any():
        parts.append(bb_s)
    if cyc['support_margin'].notna().any():
        parts.append(S._pct_rank(cyc['support_margin'], True))
    cyc['score'] = (pd.concat(parts, axis=1).mean(axis=1) if parts else np.nan)
    z = pd.to_numeric(cyc['bb_z'], errors='coerce')
    bonus = ((z <= S.OVERSOLD_Z) & cyc['score'].notna()).astype(float) * S.OVERSOLD_BONUS
    cyc['score'] = (cyc['score'] + bonus).clip(upper=100)
    if cyc['score'].notna().sum() >= 5:
        cyc['score_q'] = pd.qcut(cyc['score'].rank(method='first'), 5, labels=[1, 2, 3, 4, 5])
    else:
        cyc['score_q'] = np.nan
    return cyc


def index_return(prices, t, entry_d, expiry_d):
    df = prices.get(t)
    if df is None:
        return np.nan
    e0, e1 = snap(df.index, entry_d), snap(df.index, expiry_d)
    if e0 is None or e1 is None or e0 >= e1:
        return np.nan
    return float(df.loc[e1, 'Close'] / df.loc[e0, 'Close'] - 1.0)


# ── Performance metrics ─────────────────────────────────────────────────────────

def perf(returns, rf_annual=RISK_FREE, ppy=12):
    r = pd.Series(returns).dropna()
    if len(r) == 0:
        return dict(n=0, cum=np.nan, cagr=np.nan, vol=np.nan, sharpe=np.nan, maxdd=np.nan, win=np.nan)
    growth = float((1 + r).prod())
    yrs = len(r) / ppy
    cagr = growth ** (1 / yrs) - 1 if (yrs > 0 and growth > 0) else np.nan
    vol = r.std(ddof=1) * np.sqrt(ppy) if len(r) > 1 else np.nan
    sharpe = (r.mean() * ppy - rf_annual) / vol if (vol and vol > 0) else np.nan
    curve = (1 + r).cumprod()
    maxdd = float((curve / curve.cummax() - 1).min())
    return dict(n=len(r), cum=growth - 1, cagr=cagr, vol=vol,
                sharpe=sharpe, maxdd=maxdd, win=float((r > 0).mean()))


def _fmt(d):
    def pc(x): return f"{x*100:6.1f}%" if pd.notna(x) else "   n/a"
    return (f"n={d['n']:>3}  cum {pc(d['cum'])}  CAGR {pc(d['cagr'])}  "
            f"vol {pc(d['vol'])}  Sharpe {d['sharpe']:5.2f}  "
            f"maxDD {pc(d['maxdd'])}  win {pc(d['win'])}")


# ── Driver ──────────────────────────────────────────────────────────────────────

def run(start, end, selftest=False, do_quality=True):
    eq = S.EQUITIES
    sd = date.fromisoformat(start)
    ed = date.today() if end == 'today' else date.fromisoformat(end)
    start, end = sd.isoformat(), ed.isoformat()      # resolve 'today' before any fetch
    print("=" * 78)
    print(f"BACKTEST  {start} -> {end}  | {'SYNTHETIC' if selftest else 'yfinance'} | "
          f"~{TARGET_DELTA:.2f}d 1mo puts | IV=HV*{VRP_MULT} | topN={TOP_N}")
    print("=" * 78)

    universe = eq + BENCHMARKS
    if selftest:
        prices = synthetic_prices(universe, start, end)
    else:
        print(f"Fetching {len(universe)} tickers ...")
        prices = fetch_prices(universe, start, end)
    print(f"Loaded {len(prices)} price series.")

    quality = None
    if do_quality and not selftest:
        print("Fetching static (current) fundamentals for the BIASED quality diagnostic ...")
        quality = static_quality(eq)

    sd, ed = date.fromisoformat(start), (date.today() if end == 'today' else date.fromisoformat(end))
    expiries = third_fridays(sd, ed)
    cycles = list(zip(expiries[:-1], expiries[1:]))
    print(f"{len(cycles)} monthly cycles.\n")

    series = []     # one row per cycle
    trades = []     # every simulated trade (for transparency / CSV)
    for entry_d, expiry_d in cycles:
        cyc = build_cycle(prices, entry_d, expiry_d)
        if cyc.empty:
            continue
        if quality is not None:
            cyc = cyc.merge(quality, on='ticker', how='left')
        trades.append(cyc.assign(cycle=expiry_d))
        ranked = cyc.sort_values('score', ascending=False)
        n = min(TOP_N, len(ranked))
        row = {'cycle': expiry_d, 'pool': len(cyc),
               'ScoreTopN': ranked.head(n)['ret'].mean(),
               'ScoreBotN': ranked.tail(n)['ret'].mean(),
               'EqualWeight': cyc['ret'].mean(),
               'QQQ': index_return(prices, 'QQQ', entry_d, expiry_d),
               'SPY': index_return(prices, 'SPY', entry_d, expiry_d)}
        for q in (1, 2, 3, 4, 5):
            row[f'sQ{q}'] = cyc.loc[cyc['score_q'] == q, 'ret'].mean()
            if quality is not None:
                row[f'qQ{q}'] = cyc.loc[cyc['quality_q'] == q, 'ret'].mean()
        series.append(row)

    if not series:
        print("No cycles produced trades — check data window.")
        return
    res = pd.DataFrame(series).set_index('cycle').sort_index()

    print("─" * 78)
    print("HEADLINE  (return on collateral, per ~1-month cycle)")
    print("─" * 78)
    for col in ['ScoreTopN', 'EqualWeight', 'ScoreBotN', 'QQQ', 'SPY']:
        print(f"  {col:<12} {_fmt(perf(res[col]))}")
    edge = res['ScoreTopN'].mean() - res['EqualWeight'].mean()
    print(f"\n  Selection edge (TopN − EqualWeight), avg/cycle: {edge*100:+.2f}%  "
          f"({'score adds value' if edge > 0 else 'no edge from score'})")

    print("\n" + "─" * 78)
    print("TECHNICAL-SCORE QUINTILES  (Q1 worst → Q5 best; want monotone ↑ in CAGR)")
    print("─" * 78)
    for q in (1, 2, 3, 4, 5):
        print(f"  sQ{q}  {_fmt(perf(res[f'sQ{q}']))}")

    if quality is not None:
        print("\n" + "─" * 78)
        print("QUALITY QUINTILES  ⚠ BIASED (static current fundamentals; disqualifier only)")
        print("─" * 78)
        for q in (1, 2, 3, 4, 5):
            print(f"  qQ{q}  {_fmt(perf(res[f'qQ{q}']))}")

    # ── Does the score do its ACTUAL job — fewer/smaller assignments? ──
    # (return-on-collateral is dominated by premium size; this isolates risk.)
    all_tr = pd.concat(trades, ignore_index=True)
    all_tr['breach'] = (all_tr['strike'] - all_tr['Sx']) / all_tr['strike']   # adverse move past strike

    def _risk_block(col, title):
        if col not in all_tr.columns or all_tr[col].notna().sum() == 0:
            return
        print("\n" + "─" * 78); print(title); print("─" * 78)
        print("  Q       n   assign%   avgRet   ret|assigned   breachDepth|assigned")
        for q in (1, 2, 3, 4, 5):
            g = all_tr[all_tr[col] == q]
            if g.empty:
                continue
            a = g[g['assigned']]
            ra = a['ret'].mean() * 100 if len(a) else float('nan')
            bd = a['breach'].mean() * 100 if len(a) else float('nan')
            print(f"  Q{q}  {len(g):>6}   {g['assigned'].mean()*100:5.1f}%  {g['ret'].mean()*100:6.2f}%   "
                  f"{ra:7.2f}%        {bd:7.2f}%")

    _risk_block('score_q', "ASSIGNMENT & LOSS BY TECHNICAL-SCORE QUINTILE  (want assign% ↓ toward Q5)")
    _risk_block('quality_q', "ASSIGNMENT & LOSS BY QUALITY QUINTILE  ⚠ BIASED")
    print(f"\n  Overall assignment rate: {all_tr['assigned'].mean()*100:.1f}%  ({len(all_tr)} trades)")

    # Per-year stability of the headline (relative numbers are what matter)
    print("\n" + "─" * 78)
    print("BY YEAR  (avg per-cycle return)")
    print("─" * 78)
    yr = res.copy()
    yr['year'] = [d.year for d in yr.index]
    by = yr.groupby('year')[['ScoreTopN', 'EqualWeight', 'ScoreBotN', 'QQQ']].mean()
    print((by * 100).round(2).to_string())

    if not selftest:
        os.makedirs(S.REPORTS_DIR, exist_ok=True)
        res.to_csv(os.path.join(S.REPORTS_DIR, 'backtest_cycles.csv'))
        pd.concat(trades, ignore_index=True).to_csv(
            os.path.join(S.REPORTS_DIR, 'backtest_trades.csv'), index=False)
        print(f"\nSaved → reports/backtest_cycles.csv, reports/backtest_trades.csv")
    print("\nReminder: premiums are simulated (HV*VRP); trust RELATIVE gaps, not absolute CAGR.")


def main():
    global TOP_N
    ap = argparse.ArgumentParser()
    ap.add_argument('--start', default=START_DEFAULT)
    ap.add_argument('--end', default='today')
    ap.add_argument('--top', type=int, default=TOP_N)
    ap.add_argument('--selftest', action='store_true')
    ap.add_argument('--no-quality', action='store_true')
    a = ap.parse_args()
    TOP_N = a.top
    if a.selftest:
        run('2015-01-01', '2020-01-01', selftest=True, do_quality=False)
    else:
        run(a.start, a.end, selftest=False, do_quality=not a.no_quality)


if __name__ == '__main__':
    main()

"""
IBKR Position Monitor
Connects to IB Gateway, pulls ALL open option positions, and flags:
  - 70% profit reached  → close for profit
  - DTE ≤ 21            → time-based close (avoid gamma risk near expiry)

Combo detection: positions sharing (ticker, expiry) are tagged COMBO and
flagged together — if any leg triggers, the whole group is flagged.

Requires IB Gateway running on PORT below.
"""

from ib_insync import IB
import yfinance as yf
from datetime import date
import pandas as pd
import numpy as np
from scipy.stats import norm
import warnings

import screener as S          # reuse screener gates + scoring for roll candidates
warnings.filterwarnings('ignore')

# ── Config (defaults; overridden by config.json via screener) ─────────────────
PORT              = 4001   # 4001 live / 4002 paper
CLIENT_ID         = 3      # different from screener (2) and test (1)
_m = S.CFG.get('monitor', {}) if isinstance(S.CFG, dict) else {}
PROFIT_TARGET_PCT = _m.get('profit_target_pct', 0.70)   # close at this profit
HARD_CLOSE_DTE    = _m.get('hard_close_dte', 21)        # close at this DTE
ROLL_TOP_N        = _m.get('roll_top_n', 3)             # roll candidates per flagged put
NEAR_ATM_BUFFER   = _m.get('near_atm_buffer', 0.03)     # short put "challenged" if stock <= strike*(1+this)

# Covered-call suggestions (for shares you hold) — defaults overridden by config.json
_cc = S.CFG.get('covered_calls', {}) if isinstance(S.CFG, dict) else {}
CC_DELTA_MIN  = _cc.get('delta_min', 0.15)              # conservative OTM call band
CC_DELTA_MAX  = _cc.get('delta_max', 0.25)
CC_W_OPTION   = _cc.get('w_option', 0.6)               # score = option-edge ...
CC_W_RESIST   = _cc.get('w_resist', 0.4)               # ... + resistance cushion
CC_RESIST_WIN = int(_cc.get('resist_window', 20))      # near-term resistance lookback (trading days)
CC_LONG_DAYS  = int(_cc.get('long_high_days', 63))     # ~3-month high lookback
CC_LONG_BONUS = _cc.get('long_high_bonus', 6.0)        # capped bonus when strike clears / stock near the long high
CC_NEAR_HIGH  = _cc.get('near_high_pct', 0.03)         # "stock near its long high" tolerance
CC_TOP_N      = int(_cc.get('top_n', 3))               # suggestions shown per held stock
CC_RESPECT_COVER = _cc.get('respect_coverage', True)   # don't suggest more calls than uncovered lots
# ─────────────────────────────────────────────────────────────────────────────


def _md(s):
    """ISO date 'YYYY-MM-DD' -> compact 'M/D'; pass through anything else."""
    s = str(s)
    if len(s) >= 10 and s[4] == '-' and s[7] == '-':
        try:
            return f"{int(s[5:7])}/{int(s[8:10])}"
        except ValueError:
            return s
    return s


def get_current_option_price(ticker: str, expiry_yyyymmdd: str,
                              strike: float, right: str) -> float | None:
    """Fetch current mid or last price for an option via yfinance."""
    try:
        exp_date = date(
            int(expiry_yyyymmdd[:4]),
            int(expiry_yyyymmdd[4:6]),
            int(expiry_yyyymmdd[6:8]),
        )
        exp_yf = exp_date.strftime('%Y-%m-%d')

        yf_t = yf.Ticker(ticker)
        if exp_yf not in yf_t.options:
            return None

        chain = yf_t.option_chain(exp_yf)
        df    = chain.puts if right == 'P' else chain.calls
        row   = df[df['strike'] == strike]
        if row.empty:
            return None
        row = row.iloc[0]

        bid  = float(row.get('bid', 0)      or 0)
        ask  = float(row.get('ask', 0)       or 0)
        last = float(row.get('lastPrice', 0) or 0)

        if bid > 0 and ask > 0:
            return (bid + ask) / 2
        return last if last > 0 else None
    except Exception:
        return None


def get_stock_price(ticker):
    try:
        return S.get_price(yf.Ticker(ticker))
    except Exception:
        return None


def build_roll_suggestions(df, iv_hist_df, holdings_returns, top_n=ROLL_TOP_N):
    """For each CLOSE-flagged single-leg short PUT, score later-expiry puts on the
    SAME ticker with the screener framework and return the top-N rolls + net credit.
    Net credit (per share) = new put mid - cost to buy back the current put.
    Returns a list of (position_row, candidates_df_or_None)."""
    out = []
    flagged = df[((df['action'].astype(str).str.startswith('CLOSE')) |
                  (df['action'] == 'ROLL?')) &
                 (df['type'] == 'P') & (df['qty'] < 0) & (df['combo'] != 'COMBO')]
    for _, pos in flagged.iterrows():
        tkr, cur_exp, buyback = pos['ticker'], pos['expiry'], pos['current']
        try:
            results, _ = S.screen_ticker(tkr, iv_hist_df, holdings_returns, verbose=False)
        except Exception:
            results = []
        cand = pd.DataFrame(results)
        if not cand.empty:
            cand = S.score_candidates(cand, iv_hist_df)
            cand = cand[cand['expiry'] > cur_exp]          # roll OUT to a later expiry only
        if cand.empty:
            out.append((pos, None))
            continue
        cand = cand.copy()
        cand['net_credit'] = ((cand['mid'] - float(buyback)).round(2)
                              if buyback is not None else None)
        # Show DTE variety: best-scoring strike PER expiry, then the nearest top_n expiries,
        # so you can compare several different DTEs rather than 3 strikes in one expiry.
        cand = (cand.sort_values('score', ascending=False)
                    .groupby('expiry', as_index=False).head(1)
                    .sort_values('dte'))
        out.append((pos, cand.head(top_n)))
    return out


def print_roll_suggestions(rolls):
    """Render roll suggestions and save roll_suggestions.csv."""
    if not rolls:
        return
    print("\n" + "=" * 90)
    print(f"ROLL SUGGESTIONS  (close-flagged or ATM/ITM short puts — top {ROLL_TOP_N} by composite score)")
    print("Net credit (per share) = new put mid − buyback of current put. Rolls to a later expiry only.")
    print("=" * 90)
    cols = ['expiry', 'dte', 'strike', 'mid', 'net_credit', 'delta', 'iv_rank',
            'iv_hv', 'ann_ret_pct', 'score_option', 'score_technical',
            'score_diversify', 'score']
    flat = []
    for pos, top in rolls:
        bb = f"${pos['current']}" if pos['current'] is not None else "n/a"
        print(f"\n{pos['ticker']} P {pos['strike']:g}  exp {pos['expiry']} ({pos['dte']}d)"
              f"  | buyback {bb} | flag: {pos['reason']}")
        if top is None or top.empty:
            print("   no qualifying roll (ticker gated or no later expiry) → recommend CLOSE")
            continue
        show = [c for c in cols if c in top.columns]
        print(top[show].to_string(index=False))
        for _, r in top.iterrows():
            flat.append({'pos_ticker': pos['ticker'], 'pos_strike': pos['strike'],
                         'pos_expiry': pos['expiry'], 'pos_dte': pos['dte'],
                         'flag': pos['reason'], 'buyback': pos['current'],
                         'roll_expiry': r['expiry'], 'roll_dte': r['dte'],
                         'roll_strike': r['strike'], 'roll_mid': r['mid'],
                         'net_credit': r.get('net_credit'), 'delta': r['delta'],
                         'iv_rank': r.get('iv_rank'), 'score': r['score']})
    if flat:
        pd.DataFrame(flat).to_csv('roll_suggestions.csv', index=False)
        print("\nSaved → roll_suggestions.csv")


def _call_delta(stock, strike, T, iv):
    """Black-Scholes call delta = N(d1). r≈RISK_FREE (delta is insensitive to it)."""
    if T <= 0 or iv <= 0 or stock <= 0 or strike <= 0:
        return None
    d1 = (np.log(stock / strike) + (S.RISK_FREE + 0.5 * iv * iv) * T) / (iv * np.sqrt(T))
    return float(norm.cdf(d1))


def build_covered_calls(holdings, iv_hist_df):
    """holdings: {ticker: shares}. For each stock you own (>=100 sh), score OTM calls in
    the CC_DELTA_MIN..MAX band, combining:
      • option-edge  — IV rank, IV/HV, annualized premium (percentile-ranked across the pool)
      • resistance   — how far the strike sits above near-term resistance (20-day upper
                       Bollinger / swing high), percentile-ranked
      • long-high bonus (small, capped) — when the strike clears the ~3-month high, and/or
                       the stock is trading near that high (writing at the top of the range)
    No gates — every eligible call is scored and surfaced. Returns a scored DataFrame."""
    today = date.today()
    rows = []
    for tkr, lots, basis in holdings:
        if lots < 1:
            continue
        yf_t = yf.Ticker(tkr)
        price = S.get_price(yf_t)
        if not price or price <= 0:
            print(f"  CC {tkr} ({basis}): no price from yfinance — skipped")
            continue
        start, n_otm, n_exp = len(rows), 0, 0
        hist = S.get_price_history(yf_t)
        hv = S.compute_hv(hist) if hist is not None else None
        iv_rank, iv_src, _, _ = S.ticker_iv_rank(iv_hist_df, tkr)
        earnings = S.get_next_earnings(yf_t)
        # resistance levels
        resist_near = long_high = None
        try:
            close = hist['Close'].dropna()
            high  = hist['High'].dropna() if 'High' in hist else close
            if len(close) >= CC_RESIST_WIN:
                mid = close.rolling(CC_RESIST_WIN).mean().iloc[-1]
                sd  = close.rolling(CC_RESIST_WIN).std().iloc[-1]
                upper = float(mid + 2 * sd) if sd and sd > 0 else None
                swing = float(high.rolling(CC_RESIST_WIN).max().iloc[-1])
                resist_near = max([x for x in (upper, swing) if x is not None], default=swing)
            if len(close) >= CC_LONG_DAYS:
                long_high = float(high.rolling(CC_LONG_DAYS).max().iloc[-1])
        except Exception:
            pass
        for exp_str in yf_t.options:
            try:
                exp_date = date.fromisoformat(exp_str)
            except Exception:
                continue
            dte = (exp_date - today).days
            if not (S.MIN_DTE <= dte <= S.MAX_DTE):
                continue
            T = dte / 365.0
            try:
                calls = yf_t.option_chain(exp_str).calls
            except Exception:
                continue
            if calls is None or len(calls) == 0:
                continue
            n_exp += 1
            for _, r in calls.iterrows():
                strike = float(r['strike'])
                if strike <= price:                       # OTM calls only
                    continue
                bid = S._num(r.get('bid')); ask = S._num(r.get('ask')); last = S._num(r.get('lastPrice'))
                mid = (bid + ask) / 2 if bid > 0 and ask > 0 else last
                if mid <= 0:
                    continue
                iv = S._num(r.get('impliedVolatility'))
                if iv <= 0:
                    continue
                delta = _call_delta(price, strike, T, iv)
                if delta is None:
                    continue
                n_otm += 1                                 # OTM call we could price + delta
                if not (CC_DELTA_MIN <= delta <= CC_DELTA_MAX):
                    continue
                ann_ret = (mid / price) / dte * 365 * 100        # premium yield on the shares, annualized
                iv_hv = (iv / hv) if (hv and hv > 0) else None
                rc = ((strike - resist_near) / price) if resist_near else ((strike - price) / price)
                rows.append({
                    'ticker': tkr, 'basis': basis, 'lots': lots,
                    'stock_price': round(price, 2),
                    'expiry': exp_date.strftime('%Y-%m-%d'), 'dte': dte,
                    'earnings': str(earnings) if earnings else None,
                    'strike': strike, 'otm_%': round((strike - price) / price * 100, 1),
                    'mid': round(mid, 2), 'delta': round(delta, 3),
                    'iv_pct': round(iv * 100, 1),
                    'iv_hv': round(iv_hv, 2) if iv_hv else None,
                    'iv_rank': round(iv_rank, 0) if iv_rank is not None else None,
                    'iv_src': iv_src,
                    'ann_ret_pct': round(ann_ret, 1),
                    'income': round(mid * 100 * lots),
                    'resist_cushion_%': round(rc * 100, 1),
                    'high_3m': round(long_high, 2) if long_high else None,
                    'strike_vs_3mhigh_%': round((strike - long_high) / price * 100, 1) if long_high else None,
                    'open_int': int(S._num(r.get('openInterest'))),
                    '_ann': ann_ret, '_ivhv': iv_hv if iv_hv else 0.0,
                    '_ivr': iv_rank if iv_rank is not None else 0.0, '_rc': rc,
                    '_long_high': long_high, '_price': price, '_strike': strike,
                })
        print(f"  CC {tkr} ({basis}, {lots} lots, ${price:.0f}): "
              f"{len(rows) - start} in {CC_DELTA_MIN:.2f}-{CC_DELTA_MAX:.2f}Δ band "
              f"(of {n_otm} priced OTM calls across {n_exp} expiries in "
              f"{S.MIN_DTE}-{S.MAX_DTE} DTE)")
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    pr = lambda s: s.rank(pct=True) * 100                 # percentile across the whole pool
    opt = (pr(df['_ann']) + pr(df['_ivhv']) + pr(df['_ivr'])) / 3
    res = pr(df['_rc'])

    def long_bonus(row):
        lh = row['_long_high']
        if not lh:
            return 0.0
        b = 0.0
        if row['_strike'] >= lh:                          # strike clears the ~3-month high
            b += CC_LONG_BONUS * 0.6
        if row['_price'] >= lh * (1 - CC_NEAR_HIGH):      # stock writing near the top of its range
            b += CC_LONG_BONUS * 0.4
        return min(b, CC_LONG_BONUS)

    bonus = df.apply(long_bonus, axis=1)
    df['score_option'] = opt.round(1)
    df['score_resist'] = res.round(1)
    df['long_bonus']   = bonus.round(1)
    df['score'] = (CC_W_OPTION * opt + CC_W_RESIST * res + bonus).clip(0, 100).round(1)
    return df.sort_values('score', ascending=False).drop(
        columns=['_ann', '_ivhv', '_ivr', '_rc', '_long_high', '_price', '_strike'])


def print_covered_calls(df):
    """Render covered-call suggestions (top CC_TOP_N per held stock) and save covered_calls.csv."""
    if df is None or df.empty:
        print("\nNo call-write suggestions (no eligible holdings, or no calls in the delta band).")
        return
    print("\n" + "=" * 100)
    print(f"CALL-WRITE SUGGESTIONS  (covered calls on shares; roll-ups/spreads vs long calls; "
          f"OTM {CC_DELTA_MIN:.2f}-{CC_DELTA_MAX:.2f}Δ; "
          f"{CC_W_OPTION:.0%} option-edge + {CC_W_RESIST:.0%} resistance + 3-mo-high bonus)")
    print("=" * 100)
    cols = ['ticker', 'basis', 'lots', 'stock_price', 'expiry', 'dte', 'earnings', 'strike',
            'otm_%', 'mid', 'delta', 'iv_rank', 'iv_hv', 'ann_ret_pct', 'income',
            'resist_cushion_%', 'high_3m', 'strike_vs_3mhigh_%', 'score']
    top = (df.sort_values('score', ascending=False)
             .groupby('ticker', as_index=False).head(CC_TOP_N)
             .sort_values(['ticker', 'score'], ascending=[True, False]))
    top.to_csv('covered_calls.csv', index=False)         # CSV keeps ISO dates
    disp = top.copy()
    if 'earnings' in disp.columns:
        disp['earnings'] = disp['earnings'].map(_md)      # console shows M/D
    show = [c for c in cols if c in disp.columns]
    print(disp[show].to_string(index=False))
    print("\nSaved → covered_calls.csv")


def main():
    # ── Connect to IBKR ───────────────────────────────────────────────────────
    ib = IB()
    try:
        ib.connect('127.0.0.1', PORT, clientId=CLIENT_ID, timeout=15)
    except Exception as e:
        print(f"✗ Could not connect to IB Gateway on port {PORT}: {e}")
        print("  Is IB Gateway running and logged in? Skipping monitor "
              "(the screener/report will still run).")
        return
    print(f"Connected: {ib.isConnected()}  |  Server: {ib.client.serverVersion()}")

    positions = ib.positions()

    # Account NetLiquidation → persist for the screener's position sizing
    try:
        nlv = next((float(v.value) for v in ib.accountSummary()
                    if v.tag == 'NetLiquidation'), None)
    except Exception:
        nlv = None
    if nlv and S.save_account_size(nlv):
        print(f"Account NetLiquidation: ${nlv:,.0f}  → saved for screener sizing")

    ib.disconnect()

    # ── Filter to ALL option positions (short AND long legs of combos) ─────────
    all_opts = [
        p for p in positions
        if p.contract.secType == 'OPT'
    ]

    # Underlyings to write calls against, NET of calls you've already sold:
    #   writable lots = shares/100 + long calls − short calls already written
    #   (so a fully-covered name like 200sh + 2 short calls nets to 0 → skipped)
    share_lots, long_call_lots, short_call_lots = {}, {}, {}
    for p in positions:
        sym, pos = p.contract.symbol, int(p.position)
        if p.contract.secType == 'STK' and pos >= 100:
            share_lots[sym] = share_lots.get(sym, 0) + pos // 100
        elif p.contract.secType == 'OPT' and p.contract.right == 'C':
            if pos > 0:
                long_call_lots[sym] = long_call_lots.get(sym, 0) + pos
            elif pos < 0:
                short_call_lots[sym] = short_call_lots.get(sym, 0) + (-pos)
    call_holdings, covered = [], []
    for sym in sorted(set(share_lots) | set(long_call_lots)):
        gross = share_lots.get(sym, 0) + long_call_lots.get(sym, 0)
        avail = gross - (short_call_lots.get(sym, 0) if CC_RESPECT_COVER else 0)
        basis = 'shares' if share_lots.get(sym, 0) > 0 else 'long call'
        if avail >= 1:
            call_holdings.append((sym, avail, basis))
        elif gross >= 1:
            covered.append(f"{sym}({gross}/{gross} written)")
    iv_hist_df = S.load_iv_history()
    lots_label = "uncovered lots" if CC_RESPECT_COVER else "all lots, coverage ignored"
    print(f"\nCall-write candidates ({lots_label}): "
          f"{[(t, n, b) for t, n, b in call_holdings] or 'none'}")
    if covered:
        print(f"Fully covered (skipped — already written): {', '.join(covered)}")

    if not all_opts and not call_holdings:
        print("\nNo open option or stock positions found.")
        return

    if not all_opts:
        print("\nNo open option positions. Showing call-write suggestions for your holdings.")
        print_covered_calls(build_covered_calls(call_holdings, iv_hist_df))
        return

    print(f"\n{len(all_opts)} option position(s) found.\n")

    today = date.today()
    rows  = []
    stock_prices = {t: get_stock_price(t)
                    for t in sorted({p.contract.symbol for p in all_opts})}
    earn_dates = {t: S.get_next_earnings(yf.Ticker(t)) for t in stock_prices}

    for pos in all_opts:
        c          = pos.contract
        ticker     = c.symbol
        expiry_str = c.lastTradeDateOrContractMonth   # YYYYMMDD
        strike     = c.strike
        right      = c.right                          # 'P' or 'C'
        qty        = int(pos.position)                # negative = short, positive = long
        # IBKR avgCost is per-contract (×100); divide by 100 for per-share
        avg_cost   = pos.avgCost / 100

        exp_date = date(
            int(expiry_str[:4]),
            int(expiry_str[4:6]),
            int(expiry_str[6:8]),
        )
        dte = (exp_date - today).days

        current = get_current_option_price(ticker, expiry_str, strike, right)

        # P&L: for short (qty < 0) profit when current < entry
        #       for long  (qty > 0) profit when current > entry
        if current is not None and avg_cost and avg_cost > 0:
            if qty < 0:
                pnl_pct = (avg_cost - current) / avg_cost
            else:
                pnl_pct = (current - avg_cost) / avg_cost
        else:
            pnl_pct = None

        # Moneyness for short puts (challenged = at/in the money)
        stock = stock_prices.get(ticker)
        challenged = (right == 'P' and qty < 0 and stock is not None
                      and stock <= strike * (1 + NEAR_ATM_BUFFER))
        if right == 'P' and stock is not None:
            money = 'ITM' if stock < strike else ('ATM' if challenged else 'OTM')
        else:
            money = ''

        # Exposure = max loss at the -X% stop for short puts: strike * X% * 100 * |qty|
        exposure = (round(strike * S.ASSUMED_DRAWDOWN * 100 * abs(qty))
                    if (right == 'P' and qty < 0) else None)

        # Per-leg close triggers (only apply profit target to short legs)
        leg_reasons = []
        if qty < 0 and pnl_pct is not None and pnl_pct >= PROFIT_TARGET_PCT:
            leg_reasons.append(f"{pnl_pct * 100:.0f}% profit")
        if 0 <= dte <= HARD_CLOSE_DTE:
            leg_reasons.append(f"{dte} DTE ≤ {HARD_CLOSE_DTE}")

        e = earn_dates.get(ticker)
        rows.append({
            'ticker':       ticker,
            'type':         right,
            'expiry':       exp_date.strftime('%Y-%m-%d'),
            '_expiry_str':  expiry_str,   # internal key for grouping
            'dte':          dte,
            'earnings':     str(e) if e else None,
            'strike':       strike,
            'stock':        round(stock, 2) if stock else None,
            'money':        money,
            'exposure':     exposure,
            'qty':          qty,
            'entry':        round(avg_cost, 2) if avg_cost else None,
            'current':      round(current, 2)  if current  else None,
            'pnl_%':        round(pnl_pct * 100, 1) if pnl_pct is not None else None,
            '_leg_trigger': bool(leg_reasons),
            '_leg_reason':  '  +  '.join(leg_reasons),
            '_challenged':  bool(challenged),
        })

    df = pd.DataFrame(rows)

    # ── Combo detection: group by (ticker, expiry) ────────────────────────────
    group_counts = df.groupby(['ticker', '_expiry_str']).size()

    def get_combo_tag(row):
        count = group_counts.get((row['ticker'], row['_expiry_str']), 1)
        return 'COMBO' if count > 1 else ''

    df['combo'] = df.apply(get_combo_tag, axis=1)

    # If ANY leg in a combo group triggers, flag ALL legs in that group
    trigger_groups = set(
        df.loc[df['_leg_trigger'], ['ticker', '_expiry_str']]
        .apply(tuple, axis=1)
    )

    def resolve_action(row):
        key = (row['ticker'], row['_expiry_str'])
        if row['_leg_trigger']:
            return 'CLOSE ⚡'
        if row['combo'] == 'COMBO' and key in trigger_groups:
            return 'CLOSE ⚡'   # sibling leg triggered — close together
        if row['_challenged'] and row['combo'] != 'COMBO':
            return 'ROLL?'      # at/in the money — consider rolling down-and-out
        return 'HOLD'

    def resolve_reason(row):
        key = (row['ticker'], row['_expiry_str'])
        if row['_leg_trigger']:
            return row['_leg_reason']
        if row['combo'] == 'COMBO' and key in trigger_groups:
            return 'combo leg triggered'
        if row['_challenged'] and row['combo'] != 'COMBO':
            return f"{row['money']} (stock {row['stock']} vs strike {row['strike']:g})"
        return ''

    df['action'] = df.apply(resolve_action, axis=1)
    df['reason'] = df.apply(resolve_reason, axis=1)

    # ── Clean up and sort ─────────────────────────────────────────────────────
    df = (df
          .drop(columns=['_expiry_str', '_leg_trigger', '_leg_reason', '_challenged'])
          .sort_values(
              ['ticker', 'dte', 'type', 'strike'],
              ascending=[True, True, True, True]
          )
          .reset_index(drop=True))

    # Reorder columns for readability
    df = df[['ticker', 'combo', 'type', 'expiry', 'dte', 'earnings', 'strike', 'stock', 'money',
             'qty', 'entry', 'current', 'pnl_%', 'exposure', 'action', 'reason']]

    print("=" * 90)
    print("POSITION MONITOR")
    print(f"Exit rules: {int(PROFIT_TARGET_PCT * 100)}% profit (short legs)  or  ≤{HARD_CLOSE_DTE} DTE")
    print("Combo: legs sharing ticker+expiry are grouped — any trigger closes all legs")
    print("=" * 90)
    _disp = df.copy()
    if 'earnings' in _disp.columns:
        _disp['earnings'] = _disp['earnings'].map(_md)
    print(_disp.to_string(index=False))

    close_ct = (df['action'].str.startswith('CLOSE')).sum()
    roll_ct  = (df['action'] == 'ROLL?').sum()
    hold_ct  = (df['action'] == 'HOLD').sum()
    long_ct  = (df['qty'] > 0).sum()
    print(f"\n→ Close: {close_ct}   Roll?: {roll_ct}   Hold: {hold_ct}   (Long/hedge legs: {long_ct})")

    total_exp = int(df['exposure'].dropna().sum()) if 'exposure' in df.columns else 0
    dd = int(S.ASSUMED_DRAWDOWN * 100)
    if nlv:
        print(f"→ Short-put exposure (max loss at strike −{dd}%): ${total_exp:,} = "
              f"{total_exp / nlv * 100:.1f}% of ${nlv:,.0f} NLV")
    else:
        print(f"→ Short-put exposure (max loss at strike −{dd}%): ${total_exp:,}  (NLV n/a — run with Gateway)")

    df.to_csv('monitor_output.csv', index=False)
    print(f"Saved → monitor_output.csv")

    # ── Roll suggestions: reuse screener scoring on the same ticker ────────────
    holdings_returns = S.fetch_returns(sorted(df['ticker'].dropna().unique()))
    rolls = build_roll_suggestions(df, iv_hist_df, holdings_returns)
    print_roll_suggestions(rolls)

    # ── Call-write suggestions (covered calls on shares; roll-ups vs long calls) ──
    if call_holdings:
        print_covered_calls(build_covered_calls(call_holdings, iv_hist_df))


if __name__ == '__main__':
    main()

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
import warnings

import screener as S          # reuse screener gates + scoring for roll candidates
warnings.filterwarnings('ignore')

# ── Config ────────────────────────────────────────────────────────────────────
PORT              = 4001   # 4001 live / 4002 paper
CLIENT_ID         = 3      # different from screener (2) and test (1)
PROFIT_TARGET_PCT = 0.70   # close at 70% profit
HARD_CLOSE_DTE    = 21     # close at 21 DTE regardless of profit
ROLL_TOP_N        = 3      # roll candidates to show per flagged short put
NEAR_ATM_BUFFER   = 0.03   # short put is "challenged" (ATM/ITM) if stock <= strike*(1+this)
# ─────────────────────────────────────────────────────────────────────────────


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
        out.append((pos, cand.sort_values('score', ascending=False).head(top_n)))
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

    if not all_opts:
        print("\nNo open option positions found.")
        return

    print(f"\n{len(all_opts)} option position(s) found.\n")

    today = date.today()
    rows  = []
    stock_prices = {t: get_stock_price(t)
                    for t in sorted({p.contract.symbol for p in all_opts})}

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

        rows.append({
            'ticker':       ticker,
            'type':         right,
            'expiry':       exp_date.strftime('%Y-%m-%d'),
            '_expiry_str':  expiry_str,   # internal key for grouping
            'dte':          dte,
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
    df = df[['ticker', 'combo', 'type', 'expiry', 'dte', 'strike', 'stock', 'money',
             'qty', 'entry', 'current', 'pnl_%', 'exposure', 'action', 'reason']]

    print("=" * 90)
    print("POSITION MONITOR")
    print(f"Exit rules: {int(PROFIT_TARGET_PCT * 100)}% profit (short legs)  or  ≤{HARD_CLOSE_DTE} DTE")
    print("Combo: legs sharing ticker+expiry are grouped — any trigger closes all legs")
    print("=" * 90)
    print(df.to_string(index=False))

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
    iv_hist_df = S.load_iv_history()
    holdings_returns = S.fetch_returns(sorted(df['ticker'].dropna().unique()))
    rolls = build_roll_suggestions(df, iv_hist_df, holdings_returns)
    print_roll_suggestions(rolls)


if __name__ == '__main__':
    main()

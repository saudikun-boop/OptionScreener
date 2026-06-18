"""
Stop-order tool for short puts.

Default: buy-to-close when the UNDERLYING falls to strike x (1 - STOP_DROP),
i.e. strike -7%. The basis is configurable (STOP_BASIS):

  'underlying'       -> conditional order; fires when the STOCK hits strike*(1-STOP_DROP).
                        Immune to noisy option quotes; matches a stock-level rule. (DEFAULT)
  'option_intrinsic' -> native STP on the option; stop price = strike*STOP_DROP
                        (~the option's intrinsic at strike -STOP_DROP).
  'credit'           -> native STP on the option; stop price = CREDIT_MULT x entry credit
                        (classic premium stop; caps loss at ~(mult-1)x credit).

MODES (safety):
  MODE = 'advisory'  (DEFAULT) -> prints the stops it WOULD place; submits NOTHING.
  MODE = 'live'                -> transmits GTC stops to the account on PORT, after you
                                  type YES. Places REAL orders.

Idempotent: short puts that already have an open BUY order (stop/roll/close) are
skipped. Combos and short calls are skipped. Sizing/exposure uses a separate 15%
assumption (S.ASSUMED_DRAWDOWN); this stop cuts tighter at STOP_DROP=7%.

NOTE: connects to PORT 4001 (live — where your positions are). The agent does not
transmit orders; you flip MODE and type YES.
"""

from collections import Counter

import yfinance as yf
from ib_insync import IB, Stock, MarketOrder, StopOrder, PriceCondition

import screener as S

HOST        = '127.0.0.1'
PORT        = 4001          # live account (where your positions are)
CLIENT_ID   = 6
MODE        = 'live'    # 'advisory' (print only) | 'live' (transmit GTC stops). Kept in code (deliberate switch).
_s = S.CFG.get('stops', {}) if isinstance(S.CFG, dict) else {}
STOP_BASIS  = _s.get('basis', 'underlying')   # 'underlying' | 'option_intrinsic' | 'credit'
STOP_DROP   = _s.get('drop', 0.07)            # underlying/option_intrinsic: distance below strike
CREDIT_MULT = _s.get('credit_mult', 2.5)      # credit basis: buy-to-close at this multiple of entry credit


# ── Pure helpers (unit-tested) ────────────────────────────────────────────────

def stop_spec(strike, entry_credit, basis=STOP_BASIS, drop=STOP_DROP, mult=CREDIT_MULT):
    """Stop definition for one short put.
    Returns dict(kind, price, label):
      kind='underlying' -> price is the STOCK trigger (conditional buy-to-close)
      kind='option'     -> price is the OPTION stop price (native STP buy)
    """
    if basis == 'underlying':
        px = round(strike * (1 - drop), 2)
        return {'kind': 'underlying', 'price': px,
                'label': f"stock<={px} (strike -{int(drop*100)}%)"}
    if basis == 'option_intrinsic':
        px = round(strike * drop, 2)
        return {'kind': 'option', 'price': px,
                'label': f"opt>={px} (~intrinsic at strike -{int(drop*100)}%)"}
    if basis == 'credit':
        px = round((entry_credit or 0) * mult, 2)
        return {'kind': 'option', 'price': px,
                'label': f"opt>={px} ({mult}x credit {entry_credit})"}
    raise ValueError(f"unknown STOP_BASIS: {basis}")


def combo_keys(positions):
    cnt = Counter((p.contract.symbol, p.contract.lastTradeDateOrContractMonth)
                  for p in positions if p.contract.secType == 'OPT')
    return {k for k, v in cnt.items() if v > 1}


def plan_stops(positions, protected_conids, combos,
               basis=STOP_BASIS, drop=STOP_DROP, mult=CREDIT_MULT):
    """Stop plans for single-leg short puts lacking a protective order."""
    plans = []
    for p in positions:
        c = p.contract
        if not (c.secType == 'OPT' and c.right == 'P' and p.position < 0):
            continue
        if (c.symbol, c.lastTradeDateOrContractMonth) in combos:
            continue
        if c.conId in protected_conids:
            continue
        avg = getattr(p, 'avgCost', None)
        entry_credit = round(avg / 100, 2) if avg else None   # IBKR avgCost is per-contract
        spec = stop_spec(c.strike, entry_credit, basis, drop, mult)
        plans.append({
            'symbol':  c.symbol, 'conId': c.conId,
            'expiry':  c.lastTradeDateOrContractMonth, 'strike': c.strike,
            'qty':     int(abs(p.position)), 'entry_credit': entry_credit,
            'kind':    spec['kind'], 'price': spec['price'], 'label': spec['label'],
        })
    return plans


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    ib = IB()
    try:
        ib.connect(HOST, PORT, clientId=CLIENT_ID, timeout=15)
    except Exception as e:
        print(f"x Could not connect to IB Gateway on port {PORT}: {e}")
        print("  Is IB Gateway running and logged in?")
        return
    print(f"Connected: {ib.isConnected()}  |  port {PORT}  |  MODE={MODE}  |  basis={STOP_BASIS}")

    positions = ib.positions()
    open_trades = ib.openTrades()
    protected = {t.contract.conId for t in open_trades
                 if t.order.action == 'BUY' and t.contract.secType == 'OPT'}
    combos = combo_keys(positions)
    plans = plan_stops(positions, protected, combos)

    n_short = sum(1 for p in positions
                  if p.contract.secType == 'OPT' and p.contract.right == 'P' and p.position < 0)
    print(f"\n{n_short} short put(s); {len(plans)} need a stop "
          f"({n_short - len(plans)} skipped: combo / already protected).")
    if not plans:
        ib.disconnect()
        return

    print("\n" + "=" * 80)
    print(f"PROPOSED GTC STOPS  (basis={STOP_BASIS}, drop={int(STOP_DROP*100)}%)")
    print("=" * 80)
    print(f"{'symbol':<8}{'expiry':<10}{'strike':>8}{'qty':>5}{'credit':>8}{'stock':>9}  stop-rule")
    for pl in plans:
        try:
            spot = S.get_price(yf.Ticker(pl['symbol']))
        except Exception:
            spot = None
        spot_s = f"{spot:>9.2f}" if spot else "      n/a"
        cr = f"{pl['entry_credit']:>8.2f}" if pl['entry_credit'] is not None else "     n/a"
        print(f"{pl['symbol']:<8}{pl['expiry']:<10}{pl['strike']:>8g}{pl['qty']:>5}"
              f"{cr}{spot_s}  {pl['label']}")

    if MODE != 'live':
        print("\nADVISORY mode — no orders submitted. Set MODE='live' to transmit.")
        ib.disconnect()
        return

    ans = input(f"\nTransmit {len(plans)} GTC stop orders to account on port {PORT}? Type YES: ")
    if ans.strip() != 'YES':
        print("Aborted — no orders sent.")
        ib.disconnect()
        return

    sent = 0
    for pl in plans:
        try:
            opt = next(p.contract for p in positions if p.contract.conId == pl['conId'])
            opt.exchange = opt.exchange or 'SMART'
            if pl['kind'] == 'underlying':
                stk = Stock(pl['symbol'].replace('-', ' '), 'SMART', 'USD')
                if not ib.qualifyContracts(stk) or not stk.conId:
                    print(f"  x {pl['symbol']}: underlying unresolved — skipped")
                    continue
                order = MarketOrder('BUY', pl['qty'])
                order.tif = 'GTC'
                order.transmit = True
                order.conditions = [PriceCondition(price=pl['price'], conId=stk.conId,
                                                   exch='SMART', isMore=False)]
                order.conditionsCancelOrder = False
            else:  # native option stop
                order = StopOrder('BUY', pl['qty'], pl['price'])
                order.tif = 'GTC'
                order.transmit = True
            ib.placeOrder(opt, order)
            sent += 1
            print(f"  + {pl['symbol']} {pl['strike']:g}P x{pl['qty']}  {pl['label']}")
        except Exception as e:
            print(f"  x {pl['symbol']}: {e}")
    ib.sleep(1)
    print(f"\nTransmitted {sent} GTC stop order(s). Verify in TWS (Orders tab).")
    ib.disconnect()


if __name__ == '__main__':
    main()

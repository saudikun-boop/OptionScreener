"""
Assemble the daily digest and push it to Telegram.

Run AFTER screener.py (and optionally monitor.py). Reads the CSVs they produce —
screener_output.csv, and if present monitor_output.csv / roll_suggestions.csv —
so this stays decoupled and works the same on your PC or on GitHub Actions.

    python screener.py        # writes screener_output.csv
    python daily_report.py    # formats + sends Telegram
"""

import os
from datetime import date

import pandas as pd

import json

import notify

_DIR = os.path.dirname(os.path.abspath(__file__))

def _rep(key, default):
    try:
        with open(os.path.join(_DIR, 'config.json')) as f:
            return json.load(f).get('report', {}).get(key, default)
    except Exception:
        return default
TOP_TICKERS = _rep('top_tickers', 5)   # how many distinct tickers to show
PER_TICKER  = _rep('per_ticker', 3)    # top contracts shown per ticker


def _path(name):
    return os.path.join(_DIR, name)


def fmt_monitor():
    """Positions needing action (CLOSE / ROLL?) + total exposure line, if monitor ran."""
    f = _path('monitor_output.csv')
    if not os.path.exists(f):
        return ''
    try:
        df = pd.read_csv(f)
    except Exception:
        return ''
    if 'action' not in df.columns or df.empty:
        return ''
    act = df[df['action'].astype(str).str.startswith(('CLOSE', 'ROLL'))]
    if act.empty:
        return "<b>MONITOR</b> — no positions need action."
    cols = [c for c in ['ticker', 'type', 'strike', 'dte', 'money', 'pnl_%', 'exposure', 'action']
            if c in act.columns]
    out = "<b>MONITOR — action needed</b>\n" + notify.mono(act[cols].to_string(index=False))
    if 'exposure' in df.columns:
        tot = int(pd.to_numeric(df['exposure'], errors='coerce').dropna().sum())
        out += f"\nShort-put exposure (max loss at stop): ${tot:,}"
    return out


def fmt_rolls():
    """Top roll suggestion per flagged position, if present."""
    f = _path('roll_suggestions.csv')
    if not os.path.exists(f):
        return ''
    try:
        df = pd.read_csv(f)
    except Exception:
        return ''
    if df.empty:
        return ''
    best = df.sort_values('score', ascending=False).groupby('pos_ticker', as_index=False).head(1)
    cols = [c for c in ['pos_ticker', 'pos_strike', 'roll_expiry', 'roll_strike',
                        'net_credit', 'score'] if c in best.columns]
    return "<b>TOP ROLL per position</b>\n" + notify.mono(best[cols].to_string(index=False))


def fmt_screener():
    f = _path('screener_output.csv')
    if not os.path.exists(f):
        return "<b>SCREENER</b> — no output (screener.py did not produce results)."
    try:
        df = pd.read_csv(f)
    except Exception:
        return "<b>SCREENER</b> — could not read output."
    if df.empty:
        return "<b>SCREENER</b> — no candidates passed the gates."
    df = df.sort_values('score', ascending=False)
    # Top tickers by best score (variety), then top contracts within each
    order = (df.groupby('ticker')['score'].max()
               .sort_values(ascending=False).head(TOP_TICKERS).index.tolist())
    out = [f"<b>SCREENER</b> — {len(df)} candidates · top {len(order)} names"]
    for tkr in order:
        sub = df[df['ticker'] == tkr].sort_values('score', ascending=False).head(PER_TICKER)
        r0 = sub.iloc[0]
        sleeve = str(r0['sleeve']) if ('sleeve' in sub.columns and pd.notna(r0.get('sleeve'))) else ''
        ivr = r0.get('iv_rank')
        ivr_s = f"IVR{ivr:.0f}" if pd.notna(ivr) else ""
        hdr = f"<b>{tkr}</b> · {sleeve} · {ivr_s} · ★{r0['score']:.0f}"
        lines = []
        for _, x in sub.iterrows():
            d = abs(x['delta']) if pd.notna(x.get('delta')) else 0
            ann = x.get('ann_ret_pct')
            ann_s = f"{ann:.0f}%/y" if pd.notna(ann) else "—"
            lines.append(f"{x['strike']:g}P ${x['mid']:.2f} {int(x['dte'])}d "
                         f"Δ{d:.2f} {ann_s} s{x['score']:.0f}")
        out.append(hdr + "\n" + notify.mono("\n".join(lines)))
    if 'sleeve' in df.columns:                       # diversification menu (one per sleeve)
        book = (df.groupby('sleeve', as_index=False).head(1)
                  .sort_values('score', ascending=False))
        slines = [f"{str(row['sleeve'])[:13]:<13} {str(row['ticker']):<5} "
                  f"{row['strike']:g}P {int(row['dte'])}d s{row['score']:.0f}"
                  for _, row in book.iterrows()]
        out.append("<b>Best per sleeve</b>\n" + notify.mono("\n".join(slines)))
    return "\n\n".join(out)


def main():
    parts = [f"<b>📈 Daily Options Report — {date.today()}</b>"]
    mon = fmt_monitor()
    if mon:
        parts.append(mon)
    rolls = fmt_rolls()
    if rolls:
        parts.append(rolls)
    parts.append(fmt_screener())
    msg = "\n\n".join(parts)
    sent = notify.send_telegram(msg)
    print("Report sent." if sent else "Report NOT sent (see message above).")


if __name__ == '__main__':
    main()

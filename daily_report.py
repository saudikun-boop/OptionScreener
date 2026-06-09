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

import notify

_DIR = os.path.dirname(os.path.abspath(__file__))
TOP_N = 10   # candidates in the screener section


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
    cols = [c for c in ['ticker', 'expiry', 'dte', 'strike', 'mid', 'delta',
                        'iv_rank', 'ann_ret_pct', 'score'] if c in df.columns]
    out = [f"<b>SCREENER</b> — {len(df)} candidates (top {TOP_N})",
           notify.mono(df[cols].head(TOP_N).to_string(index=False))]
    if 'sleeve' in df.columns:
        book = df.groupby('sleeve', as_index=False).head(1)
        scols = [c for c in ['sleeve', 'ticker', 'strike', 'dte', 'ann_ret_pct', 'score']
                 if c in book.columns]
        out.append("<b>Best per sleeve</b>")
        out.append(notify.mono(book[scols].to_string(index=False)))
    return "\n".join(out)


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

"""
Assemble the daily digest and push it to Telegram.

Run AFTER screener.py (and optionally monitor.py). Reads the CSVs they produce —
screener_output.csv, and if present monitor_output.csv / roll_suggestions.csv —
so this stays decoupled and works the same on your PC or on GitHub Actions.

    python screener.py        # writes screener_output.csv
    python daily_report.py    # formats + sends Telegram
"""

import os
import sys
from datetime import date

import pandas as pd

import json
import glob

import notify

for _s in (sys.stdout, sys.stderr):          # UTF-8 so non-cp932 chars don't crash logging
    try:
        _s.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)                       # project root (parent of code/)
_REPORTS = os.path.join(_ROOT, 'reports')            # where the CSV/xlsx outputs live
os.makedirs(_REPORTS, exist_ok=True)

def _rep(key, default):
    try:
        with open(os.path.join(_ROOT, 'config.json')) as f:
            return json.load(f).get('report', {}).get(key, default)
    except Exception:
        return default
TOP_TICKERS = _rep('top_tickers', 5)   # how many distinct tickers to show
PER_TICKER  = _rep('per_ticker', 3)    # top contracts shown per ticker
TOP_DIVIDENDS = _rep('top_dividends', 3)  # dividend-payer section size
ATTACH_CSV  = _rep('attach_csv', True) # also attach the full CSVs to Telegram

# Short (5-6 char) sleeve labels so the "Best per sleeve" line fits a phone screen.
SLEEVE_ABBR = {
    'Equity Index': 'EQIDX', 'Intl Equity': 'INTLEQ', 'Bonds': 'BONDS',
    'Commodity': 'COMMOD', 'REIT': 'REIT', 'Energy': 'ENERGY',
    'Financials': 'FINANC', 'ETF': 'ETF',
    'Technology': 'TECH', 'Financial Services': 'FINSVC', 'Healthcare': 'HEALTH',
    'Consumer Cyclical': 'CONCYC', 'Consumer Defensive': 'CONDEF',
    'Communication Services': 'COMMS', 'Industrials': 'INDUS', 'Utilities': 'UTILS',
    'Real Estate': 'RLEST', 'Basic Materials': 'MATER', 'Equity': 'EQUITY',
}


def _ab(sleeve):
    s = str(sleeve)
    return SLEEVE_ABBR.get(s, s[:6].upper())


# Column order + names for the Excel "Screener" tab (per the field-layout spec).
_SCR_ORDER = ['ticker', 'sleeve', 'type', 'stock_price', 'strike', 'otm_%', 'expiry', 'dte',
              'earnings', 'mid', 'spread_pct', 'open_int', 'volume', 'delta', 'theta', 'iv_hv',
              'ann_ret_pct', 'score', 'score_option', 'score_technical', 'score_diversify',
              'score_fundamental', 'collat_ct', 'risk_ct', 'income', 'lots', 'div_corr',
              'div_score', 'fwd_pe', 'roe', 'rev_growth', 'debt_to_equity', 'current_ratio',
              'bb_z', '_rsi', '_bb_pctb', '_support_margin', 'div_yield', 'iv_rank', 'iv_src',
              'iv_pct', 'hv_pct']
_SCR_RENAME = {'spread_pct': 'spread%', 'ann_ret_pct': 'ann_ret%', 'iv_pct': 'iv%',
               'hv_pct': 'hv%', '_bb_pctb': '%B',
               '_support_margin': 'support_margin', '_rsi': 'rsi',
               'rev_growth': 'rev_gr', 'debt_to_equity': 'd/e', 'current_ratio': 'curr_r',
               'score_option': 'sc_opt', 'score_technical': 'sc_tech',
               'score_diversify': 'sc_dvsfy', 'score_fundamental': 'sc_fund'}


def _screener_view(df):
    """Reorder / rename / clean the screener columns for the Excel tab (drop etf, shorten
    sleeve, round delta+theta, _pct->%)."""
    d = df.copy()
    if 'etf' in d.columns:
        d = d.drop(columns=['etf'])
    if 'sleeve' in d.columns:
        d['sleeve'] = d['sleeve'].map(lambda s: _ab(s) if pd.notna(s) else s)
    for c in ('delta', 'theta'):
        if c in d.columns:
            d[c] = pd.to_numeric(d[c], errors='coerce').round(3)
    cols = [c for c in _SCR_ORDER if c in d.columns]
    cols += [c for c in d.columns if c not in cols]      # keep any extras at the end
    return d[cols].rename(columns=_SCR_RENAME)


def _path(name):
    return os.path.join(_REPORTS, name)


def _md(s):
    """ISO 'YYYY-MM-DD' -> compact 'M/D'; pass anything else through."""
    s = str(s)
    if len(s) >= 10 and s[4] == '-' and s[7] == '-':
        try:
            return f"{int(s[5:7])}/{int(s[8:10])}"
        except ValueError:
            return s
    return s


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
    lines = []
    for _, x in act.iterrows():
        a = 'CLOSE' if str(x['action']).startswith('CLOSE') else 'ROLL'
        pnl = x.get('pnl_%')
        pnl_s = f"{pnl:+.0f}%" if pd.notna(pnl) else "—"
        money = str(x['money']) if pd.notna(x.get('money')) else ''
        e = x.get('earnings')
        e_s = f" E{_md(e)}" if pd.notna(e) and str(e) not in ('', 'nan') else ""
        lines.append(f"{x['ticker']} {x['strike']:g}{x['type']} {int(x['dte'])}d "
                     f"{money} {pnl_s} {a}{e_s}")
    out = "<b>MONITOR — action</b>\n" + notify.mono("\n".join(lines))
    # Book totals (over all positions)
    ent = pd.to_numeric(df.get('entry'), errors='coerce')
    cur = pd.to_numeric(df.get('current'), errors='coerce')
    q = pd.to_numeric(df.get('qty'), errors='coerce')
    if ent is not None and q is not None and q.notna().any():
        prem = (ent * 100 * q.abs()).where(q < 0).sum()
        pnl = ((cur - ent) * 100 * q).sum()
        pct = f" ({pnl / prem * 100:+.0f}%)" if prem else ""
        out += f"\nPremium collected: ${prem:,.0f}  |  Open P&amp;L: ${pnl:,.0f}{pct}"
    if 'exposure' in df.columns:
        tot = int(pd.to_numeric(df['exposure'], errors='coerce').dropna().sum())
        out += f"\nExposure (max loss at stop): ${tot:,}"
    return out


def fmt_rolls():
    """Roll suggestions per flagged position — a few different DTEs, if present."""
    f = _path('roll_suggestions.csv')
    if not os.path.exists(f):
        return ''
    try:
        df = pd.read_csv(f)
    except Exception:
        return ''
    if df.empty:
        return ''
    keep = (df.sort_values('score', ascending=False)
              .groupby('pos_ticker', as_index=False).head(3))
    sort_k = ['pos_ticker'] + (['roll_dte'] if 'roll_dte' in keep.columns else [])
    keep = keep.sort_values(sort_k)
    lines = []
    for _, r in keep.iterrows():
        cr = r.get('net_credit')
        cr_s = f"+{cr:.2f}" if pd.notna(cr) else "—"
        ps = r.get('pos_strike')
        roll = f"{ps:g}>{r['roll_strike']:g}P" if pd.notna(ps) else f"{r['roll_strike']:g}P"
        lines.append(f"{str(r['pos_ticker']):<5} {roll} {int(r['roll_dte'])}d {cr_s} s{r['score']:.0f}")
    # One aligned monospace block, like the other sections.
    return "<b>ROLLS</b>  <i>cur&gt;new strike · several DTEs</i>\n" + notify.mono("\n".join(lines))


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
    # Top tickers by best score (variety), then top contracts within each — one compact block
    order = (df.groupby('ticker')['score'].max()
               .sort_values(ascending=False).head(TOP_TICKERS).index.tolist())
    sub = (df[df['ticker'].isin(order)].sort_values('score', ascending=False)
             .groupby('ticker', as_index=False).head(PER_TICKER)
             .sort_values(['ticker', 'score'], ascending=[True, False]))
    lines = []
    for _, x in sub.iterrows():
        d = abs(x['delta']) if pd.notna(x.get('delta')) else 0
        d_s = ("%.2f" % d).lstrip("0") or "0"
        ann = x.get('ann_ret_pct')
        ann_s = f"{ann:.0f}%" if pd.notna(ann) else "—"
        e = x.get('earnings')
        e_s = f" E{_md(e)}" if pd.notna(e) and str(e) not in ('', 'nan') else ""
        lines.append(f"{str(x['ticker']):<5} {x['strike']:g}P {int(x['dte'])}d "
                     f"Δ{d_s} {ann_s} s{x['score']:.0f}{e_s}")
    # One aligned monospace block, like the other sections (chunking keeps it intact).
    out = [f"<b>SCREENER</b> — {len(df)} candidates · top {len(order)} names\n"
           + notify.mono("\n".join(lines))]
    if 'sleeve' in df.columns:                       # diversification menu (one per sleeve)
        book = (df.groupby('sleeve', as_index=False).head(1)
                  .sort_values('score', ascending=False))
        slines = []
        for _, row in book.iterrows():
            d = abs(row['delta']) if pd.notna(row.get('delta')) else 0
            d_s = ("%.2f" % d).lstrip("0") or "0"   # .19 instead of 0.19 (saves a char)
            y = row.get('ann_ret_pct')
            y_s = f"{y:.0f}%" if pd.notna(y) else "—"
            slines.append(f"{_ab(row['sleeve']):<6} {str(row['ticker']):<5} "
                          f"{row['strike']:g}P {int(row['dte'])}d "
                          f"Δ{d_s} {y_s} s{row['score']:.0f}")
        out.append("<b>Best per sleeve</b>  <i>Δ=delta · %=ann.yield</i>\n"
                   + notify.mono("\n".join(slines)))
    return "\n\n".join(out)


def fmt_covered_calls():
    """Covered-call suggestions for shares you hold, grouped by ticker (top few each)."""
    f = _path('covered_calls.csv')
    if not os.path.exists(f):
        return ''
    try:
        df = pd.read_csv(f)
    except Exception:
        return ''
    if df.empty:
        return ''
    df = df.sort_values('score', ascending=False)
    top = (df.groupby('ticker', as_index=False).head(PER_TICKER)
             .sort_values(['ticker', 'score'], ascending=[True, False]))
    lines = []
    for _, x in top.iterrows():
        d = abs(x['delta']) if pd.notna(x.get('delta')) else 0
        d_s = ("%.2f" % d).lstrip("0") or "0"
        ann = x.get('ann_ret_pct')
        ann_s = f"{ann:.0f}%" if pd.notna(ann) else "—"
        e = x.get('earnings')
        e_s = f" E{_md(e)}" if pd.notna(e) and str(e) not in ('', 'nan') else ""
        tkr = str(x['ticker']) + ('*' if x.get('cc_open') else '')
        lines.append(f"{tkr:<6} {x['strike']:g}C {int(x['dte'])}d "
                     f"Δ{d_s} {ann_s} s{x['score']:.0f}{e_s}")
    return ("<b>CALL WRITES</b>  <i>* = call already open</i>\n"
            + notify.mono("\n".join(lines)))


def fmt_dividends():
    """Top dividend-paying stocks across ALL stocks scanned (ungated watchlist), with div %."""
    f = _path('dividends.csv')
    if not os.path.exists(f):
        return ''
    try:
        df = pd.read_csv(f)
    except Exception:
        return ''
    if df.empty or 'div_yield' not in df.columns:
        return ''
    top = df.sort_values('div_yield', ascending=False).head(TOP_DIVIDENDS)
    lines = []
    for _, x in top.iterrows():
        px = f"${x['stock_price']:g}" if pd.notna(x.get('stock_price')) else ""
        lines.append(f"{str(x['ticker']):<5} {x['div_yield']:.1f}%  {px}")
    return ("<b>DIVIDENDS</b>  <i>top yield · all stocks (ungated)</i>\n"
            + notify.mono("\n".join(lines)))


def build_workbook():
    """Combine the run's CSVs into one multi-tab .xlsx. Returns the path, or None.
    Prints a clear reason on any failure so the log shows why it fell back to CSV."""
    sheets = [('screener_output.csv', 'Screener'), ('monitor_output.csv', 'Monitor'),
              ('roll_suggestions.csv', 'Rolls'), ('covered_calls.csv', 'CallWrites'),
              ('dividends.csv', 'Dividends')]
    present = [(f, n) for f, n in sheets if os.path.exists(_path(f))]
    if not present:
        print("Workbook: no CSVs present to combine.")
        return None
    try:
        import openpyxl  # noqa: F401  (explicit so a missing dep is obvious)
    except Exception as e:
        print("Workbook: openpyxl not importable —", e)
        return None
    # Dated filename so an .xlsx left open on a device can't lock today's write.
    out = _path(f"daily_report_{date.today()}.xlsx")
    # Don't accumulate: remove previous report files (keep only this run's).
    for old in glob.glob(_path('daily_report_*.xlsx')) + [_path('daily_report.csv')]:
        if os.path.abspath(old) != os.path.abspath(out) and os.path.exists(old):
            try:
                os.remove(old)
            except OSError:
                pass
    wrote = 0
    try:
        with pd.ExcelWriter(out, engine='openpyxl') as xw:
            from openpyxl.utils import get_column_letter
            for f, n in present:
                try:
                    sdf = pd.read_csv(_path(f))
                    if n == 'Screener':
                        sdf = _screener_view(sdf)            # reorder/rename per the field spec
                    sdf.to_excel(xw, sheet_name=n, index=False)
                    ws = xw.sheets[n]                         # auto-size columns to content (tight)
                    for ci, col in enumerate(sdf.columns, start=1):
                        body = sdf[col].head(300).astype(str)
                        maxlen = max([len(str(col))] + [len(v) for v in body])
                        ws.column_dimensions[get_column_letter(ci)].width = min(max(maxlen + 1, 5), 16)
                    ws.freeze_panes = 'B2'                    # keep ticker + header visible when scrolling
                    wrote += 1
                except Exception as e:
                    print(f"Workbook: sheet {n} skipped — {e}")
            if wrote == 0:                                  # never save an empty workbook
                pd.DataFrame({'note': ['no rows in any section']}).to_excel(
                    xw, sheet_name='Empty', index=False)
        print(f"Workbook built: {os.path.basename(out)} ({wrote} sheet(s))")
        return out
    except Exception as e:
        print("Workbook build FAILED —", repr(e))
        return None


def build_combined_csv():
    """Fallback when openpyxl is missing: stack all CSVs into ONE file with a 'section'
    column (so you still get a single attachment, never four)."""
    sheets = [('screener_output.csv', 'Screener'), ('monitor_output.csv', 'Monitor'),
              ('roll_suggestions.csv', 'Rolls'), ('covered_calls.csv', 'CallWrites'),
              ('dividends.csv', 'Dividends')]
    frames = []
    for f, n in sheets:
        p = _path(f)
        if os.path.exists(p):
            try:
                d = pd.read_csv(p)
                d.insert(0, 'section', n)
                frames.append(d)
            except Exception:
                pass
    if not frames:
        return None
    out = _path('daily_report.csv')
    pd.concat(frames, ignore_index=True).to_csv(out, index=False)
    return out


def attach_outputs():
    """Attach ONE combined file to Telegram: a multi-tab .xlsx if openpyxl is available,
    otherwise a single combined .csv. Never sends four separate CSVs."""
    today = date.today()
    wb = build_workbook()
    if wb and notify.send_document(wb, caption=f"Daily report — all tables — {today}"):
        print("Attached daily_report.xlsx")
        return
    print("Excel unavailable (install openpyxl) — sending one combined CSV instead.")
    cb = build_combined_csv()
    if cb and notify.send_document(cb, caption=f"Daily report — all tables — {today}"):
        print("Attached daily_report.csv (combined)")


def main():
    parts = [f"<b>📈 Daily Options Report — {date.today()}</b>"]
    mon = fmt_monitor()
    if mon:
        parts.append(mon)
    rolls = fmt_rolls()
    if rolls:
        parts.append(rolls)
    cc = fmt_covered_calls()
    if cc:
        parts.append(cc)
    parts.append(fmt_screener())
    dvd = fmt_dividends()
    if dvd:
        parts.append(dvd)
    msg = "\n\n".join(parts)
    sent = notify.send_telegram(msg)
    print("Report sent." if sent else "Report NOT sent (see message above).")

    # Attach the full tables (combined workbook) so they open cleanly on the phone
    if ATTACH_CSV:
        attach_outputs()


if __name__ == '__main__':
    main()

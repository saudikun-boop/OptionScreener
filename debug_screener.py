"""Quick debug: shows what yfinance returns for AAPL in the DTE window."""
import yfinance as yf
from datetime import date
import warnings
warnings.filterwarnings('ignore')

today  = date.today()
ticker = 'AAPL'
MIN_DTE, MAX_DTE = 30, 45

yf_t  = yf.Ticker(ticker)
price = yf_t.fast_info.last_price or yf_t.fast_info.previous_close
print(f"Price: {price}")
from datetime import timedelta
print(f"Today: {today}  |  Window: {today + timedelta(days=MIN_DTE)} – {today + timedelta(days=MAX_DTE)}")
print(f"\nAll expirations: {list(yf_t.options)}\n")

for exp_str in yf_t.options:
    exp_date = date.fromisoformat(exp_str)
    dte = (exp_date - today).days
    if MIN_DTE <= dte <= MAX_DTE:
        print(f"=== {exp_str}  ({dte} DTE) ===")
        puts = yf_t.option_chain(exp_str).puts
        nearby = puts[(puts['strike'] >= price * 0.75) & (puts['strike'] <= price * 1.02)]
        print(nearby[['strike', 'bid', 'ask', 'lastPrice', 'impliedVolatility', 'volume', 'openInterest']].to_string())
        print()

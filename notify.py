"""
Telegram notifier (free Bot API).

Credentials (in order):
  1. env vars  TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID   (used by GitHub Actions secrets)
  2. telegram_config.json next to this file: {"bot_token": "...", "chat_id": "..."}

Setup: message @BotFather -> /newbot -> copy the token. Get your chat_id by messaging
your bot once, then visiting https://api.telegram.org/bot<token>/getUpdates and reading
result[].message.chat.id  (or message @userinfobot).
"""

import os
import json
import html

import requests

_CFG = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'telegram_config.json')
_API = "https://api.telegram.org/bot{token}/sendMessage"
_DOC = "https://api.telegram.org/bot{token}/sendDocument"
_MAX = 3900   # Telegram hard limit is 4096; leave headroom


def _creds():
    tok = os.environ.get('TELEGRAM_BOT_TOKEN')
    chat = os.environ.get('TELEGRAM_CHAT_ID')
    if tok and chat:
        return tok, chat
    try:
        with open(_CFG) as f:
            c = json.load(f)
        return c.get('bot_token'), c.get('chat_id')
    except Exception:
        return None, None


def _chunks(text, n=_MAX):
    """Split on line boundaries so each message stays under Telegram's limit."""
    buf = ''
    for ln in text.split('\n'):
        if len(buf) + len(ln) + 1 > n:
            if buf:
                yield buf
            buf = ln[:n]
        else:
            buf = (buf + '\n' + ln) if buf else ln
    if buf:
        yield buf


def mono(table_str):
    """Wrap a (monospace) block for Telegram HTML, escaping &<>."""
    return "<pre>" + html.escape(table_str) + "</pre>"


def send_telegram(text, token=None, chat=None):
    token = token or _creds()[0]
    chat = chat or _creds()[1]
    if not token or not chat:
        print("Telegram not configured — set TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID "
              "or create telegram_config.json. (Message not sent.)")
        return False
    ok = True
    for chunk in _chunks(text):
        try:
            r = requests.post(_API.format(token=token),
                              data={'chat_id': chat, 'text': chunk,
                                    'parse_mode': 'HTML',
                                    'disable_web_page_preview': True},
                              timeout=20)
            if r.status_code != 200:
                print("Telegram error:", r.status_code, r.text[:300])
                ok = False
        except Exception as e:
            print("Telegram send failed:", e)
            ok = False
    return ok


def send_document(path, caption='', token=None, chat=None):
    """Upload a file (e.g. a CSV) to Telegram so it can be opened on the phone."""
    token = token or _creds()[0]
    chat = chat or _creds()[1]
    if not token or not chat:
        print("Telegram not configured — document not sent:", path)
        return False
    if not os.path.exists(path):
        return False
    try:
        with open(path, 'rb') as fh:
            r = requests.post(
                _DOC.format(token=token),
                data={'chat_id': chat, 'caption': caption[:1024], 'parse_mode': 'HTML'},
                files={'document': (os.path.basename(path), fh, 'text/csv')},
                timeout=60)
        if r.status_code != 200:
            print("Telegram doc error:", r.status_code, r.text[:300])
            return False
        return True
    except Exception as e:
        print("Telegram document send failed:", e)
        return False


if __name__ == '__main__':
    # quick test: python notify.py
    send_telegram("✅ Test message from your options screener notifier.")

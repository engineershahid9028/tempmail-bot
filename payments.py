import os, time, hmac, hashlib, requests
from urllib.parse import urlencode
from db import db, Payment

BINANCE_API_KEY = os.getenv("BINANCE_API_KEY")
BINANCE_SECRET = os.getenv("BINANCE_SECRET")

BASE = "https://api.binance.com"

# ---------------- Binance helpers ----------------

def _sign(params):
    query = urlencode(params)
    signature = hmac.new(
        BINANCE_SECRET.encode(), query.encode(), hashlib.sha256
    ).hexdigest()
    return query + "&signature=" + signature

def _headers():
    return {"X-MBX-APIKEY": BINANCE_API_KEY}

def get_recent_deposits(minutes=60):
    end = int(time.time() * 1000)
    start = end - minutes * 60 * 1000

    params = {
        "startTime": start,
        "endTime": end,
        "timestamp": int(time.time() * 1000),
        "recvWindow": 5000,
    }

    url = BASE + "/sapi/v1/capital/deposit/hisrec?" + _sign(params)
    r = requests.get(url, headers=_headers(), timeout=20).json()

    return r if isinstance(r, list) else []

def verify_deposit(txid: str, amount: float, asset: str, minutes=120):
    deposits = get_recent_deposits(minutes=minutes)

    for d in deposits:
        if str(d.get("txId")) == txid and d.get("coin", "").upper() == asset.upper():
            try:
                dep_amount = float(d.get("amount", 0))
            except:
                dep_amount = 0

            if dep_amount >= float(amount) and d.get("status") == 1:  # success
                return True, d

    return False, None

# ---------------- Database payment ----------------

def create_payment(user_id, txid, amount, currency):
    s = db()
    p = Payment(
        user_id=user_id,
        txid=txid,
        amount=str(amount),
        currency=currency,
        status="approved",  # auto-approved after verification
    )
    s.add(p)
    s.commit()
    s.refresh(p)
    s.close()
    return p

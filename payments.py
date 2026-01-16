# payments.py

from db import db, Payment
from datetime import datetime


def create_payment(user_id, txid, amount, currency):
    session = db()

    payment = Payment(
        user_id=user_id,
        txid=txid,
        amount=str(amount),
        currency=currency,
        status="pending",
        created_at=datetime.utcnow()
    )

    session.add(payment)
    session.commit()
    session.refresh(payment)
    session.close()

    return payment


# Dummy verifier (replace later with Binance API)
def verify_deposit(txid, amount, asset, minutes=120):
    """
    For now this always returns True so payments work.
    Later we can connect Binance API here.
    """
    return True, {}

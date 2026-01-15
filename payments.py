
from db import db, Payment

def create_payment(user_id, txid, amount, currency):
    s = db()
    p = Payment(user_id=user_id, txid=txid, amount=amount, currency=currency, status='pending')
    s.add(p); s.commit(); s.refresh(p); s.close()
    return p

def pending():
    s = db()
    rows = s.query(Payment).filter(Payment.status=='pending').all()
    s.close()
    return rows

def approve(pid):
    s = db()
    p = s.query(Payment).filter(Payment.id==pid).first()
    if p:
        p.status='approved'; s.commit()
    s.close()
    return p

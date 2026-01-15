
from db import db, User, Email, Inbox, Payment

def get_stats():
    s = db()
    out = {
        "users": s.query(User).count(),
        "emails": s.query(Email).count(),
        "messages": s.query(Inbox).count(),
        "payments": s.query(Payment).count(),
        "pending": s.query(Payment).filter(Payment.status=='pending').count()
    }
    s.close()
    return out

import os
from datetime import datetime
from sqlalchemy import create_engine, Column, Integer, BigInteger, String, DateTime, Text
from sqlalchemy.orm import declarative_base, sessionmaker

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///data.db")

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


# ---------------- Users ----------------

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    telegram_id = Column(BigInteger, unique=True, index=True)
    plan = Column(String, default="free")
    daily_quota = Column(Integer, default=2)
    bonus_quota = Column(Integer, default=0)
    referrals = Column(Integer, default=0)
    referral_code = Column(String, index=True)
    last_reset = Column(String)
    premium_until = Column(DateTime, nullable=True)


# ---------------- Emails ----------------

class Email(Base):
    __tablename__ = "emails"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer)
    email = Column(String)
    token = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)


# ---------------- Inbox (Full HTML Support) ----------------

class Inbox(Base):
    __tablename__ = "inbox"
    id = Column(Integer, primary_key=True, index=True)
    email_id = Column(Integer)
    sender = Column(String)
    subject = Column(String)

    # plain text version (for preview)
    body = Column(Text)

    # full html email (for buttons & redirects)
    html = Column(Text)

    created_at = Column(DateTime, default=datetime.utcnow)


# ---------------- Payments ----------------

class Payment(Base):
    __tablename__ = "payments"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer)
    txid = Column(String)
    amount = Column(String)
    currency = Column(String)
    status = Column(String, default="pending")
    created_at = Column(DateTime, default=datetime.utcnow)


# ---------------- Init ----------------

def init_db():
    Base.metadata.create_all(bind=engine)


def db():
    return SessionLocal()

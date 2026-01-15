# ===========================
# bot.py — Full Working File
# ===========================

import os, re, time, threading
from datetime import datetime, UTC
from dateutil.relativedelta import relativedelta
import telebot
from telebot.types import (
    LabeledPrice,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
import qrcode
from io import BytesIO

# ---- App modules ----
from providers import PROVIDER
from ui import main_menu
from db import init_db, db, User, Email, Inbox, Payment
from analytics import get_stats
from payments import create_payment, verify_deposit
from stars import stars_invoice

# ================= CONFIG =================

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

USDT_ADDRESS = os.getenv("USDT_TRC20_ADDRESS")
PAY_AMOUNT = os.getenv("PAYMENT_AMOUNT", "10")
PAY_ASSET = os.getenv("PAYMENT_ASSET", "USDT")

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is not set")
if not USDT_ADDRESS:
    raise RuntimeError("USDT_TRC20_ADDRESS is not set")

bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")
init_db()

listeners = {}

# ================= UI HELPERS =================

def checkout_keyboard():
    kb = InlineKeyboardMarkup()
    kb.row(
        InlineKeyboardButton("📋 Copy Address", callback_data="copy_addr"),
        InlineKeyboardButton("📷 QR Code", callback_data="show_qr"),
    )
    return kb

def generate_qr(address: str):
    img = qrcode.make(address)
    bio = BytesIO()
    img.save(bio, format="PNG")
    bio.seek(0)
    return bio

# ================= HELPERS =================

def admin_only(func):
    def wrapper(msg):
        if msg.chat.id != ADMIN_ID:
            return
        return func(msg)
    return wrapper

def extract_otp(text: str):
    m = re.search(r"(?:otp|code|verification)?[^0-9]{0,10}(\d{4,8})", text, re.I)
    return m.group(1) if m else None

def get_user(tg_id: int):
    s = db()
    u = s.query(User).filter(User.telegram_id == tg_id).first()
    if not u:
        u = User(
            telegram_id=tg_id,
            referral_code=f"REF{tg_id}",
            last_reset=str(time.time()),
            daily_quota=2,
            plan="free",
        )
        s.add(u)
        s.commit()
        s.refresh(u)
    s.close()
    return u

def reset_quota(u: User):
    today = datetime.now(UTC).date().isoformat()
    if u.last_reset != today:
        base = 5 if u.plan == "premium" else 2
        u.daily_quota = base + (u.bonus_quota or 0)
        u.last_reset = today

def save_user(u: User):
    s = db()
    s.merge(u)
    s.commit()
    s.close()

# ================= OTP LISTENER =================

def start_listener(chat_id: int, email_id: int, token: str):
    if email_id in listeners:
        return

    def loop():
        seen = set()
        while True:
            try:
                for m in PROVIDER.messages(token):
                    mid = m["id"]
                    if mid in seen:
                        continue
                    seen.add(mid)

                    mail = PROVIDER.message(token, mid)
                    sender = mail["from"]["address"]
                    subject = mail["subject"]
                    body = mail.get("text", "")

                    s = db()
                    s.add(Inbox(email_id=email_id, sender=sender, subject=subject, body=body))
                    s.commit()
                    s.close()

                    otp = extract_otp(body)
                    text = (
                        "📩 <b>New Email</b>\n\n"
                        f"<b>From:</b> {sender}\n"
                        f"<b>Subject:</b> {subject}\n"
                    )
                    if otp:
                        text += f"\n🔐 <b>OTP:</b> <code>{otp}</code>"

                    bot.send_message(chat_id, text, reply_markup=main_menu())

                time.sleep(6)
            except Exception:
                time.sleep(10)

    t = threading.Thread(target=loop, daemon=True)
    listeners[email_id] = t
    t.start()

# ================= USER COMMANDS =================

@bot.message_handler(commands=["start"])
def start(msg):
    get_user(msg.chat.id)
    bot.send_message(
        msg.chat.id,
        "👋 <b>Welcome to TempMail Premium Bot!</b>\nWe provide fast temp emails with auto OTP.",
        reply_markup=main_menu(),
    )

@bot.callback_query_handler(func=lambda c: c.data == "newmail")
def newmail(call):
    u = get_user(call.message.chat.id)
    reset_quota(u)

    if u.daily_quota <= 0:
        bot.send_message(call.message.chat.id, "❌ Daily quota reached", reply_markup=main_menu())
        return

    email, token = PROVIDER.create()

    s = db()
    e = Email(user_id=u.id, email=email, token=token)
    s.add(e)
    s.commit()
    s.refresh(e)
    s.close()

    u.daily_quota -= 1
    save_user(u)

    bot.send_message(
        call.message.chat.id,
        f"📧 <b>Your Temp Email</b>\n<code>{email}</code>\n\nAuto-fetch enabled",
        reply_markup=main_menu(),
    )

    start_listener(call.message.chat.id, e.id, token)

@bot.callback_query_handler(func=lambda c: c.data == "reuse")
def reuse(call):
    u = get_user(call.message.chat.id)
    if u.plan != "premium":
        bot.send_message(call.message.chat.id, "❌ Premium only", reply_markup=main_menu())
        return

    s = db()
    e = s.query(Email).filter(Email.user_id == u.id).order_by(Email.id.desc()).first()
    s.close()

    if not e:
        bot.send_message(call.message.chat.id, "No previous email", reply_markup=main_menu())
        return

    bot.send_message(
        call.message.chat.id,
        f"♻️ <b>Reusing Email</b>\n<code>{e.email}</code>\n\nAuto-fetch enabled",
        reply_markup=main_menu(),
    )
    start_listener(call.message.chat.id, e.id, e.token)

@bot.callback_query_handler(func=lambda c: c.data == "inbox")
def inbox(call):
    u = get_user(call.message.chat.id)

    s = db()
    rows = (
        s.query(Inbox, Email)
        .join(Email, Inbox.email_id == Email.id)
        .filter(Email.user_id == u.id)
        .order_by(Inbox.id.desc())
        .limit(10)
        .all()
    )
    s.close()

    if not rows:
        bot.send_message(call.message.chat.id, "📭 Inbox empty", reply_markup=main_menu())
        return

    text = "📥 <b>Your Inbox</b>\n\n"
    for r, _e in rows:
        otp = extract_otp(r.body or "")
        text += f"<b>From:</b> {r.sender}\n<b>Subject:</b> {r.subject}\n"
        if otp:
            text += f"🔐 OTP: <code>{otp}</code>\n"
        text += "\n"

    bot.send_message(call.message.chat.id, text, reply_markup=main_menu())

@bot.callback_query_handler(func=lambda c: c.data == "referral")
def referral(call):
    u = get_user(call.message.chat.id)
    link = f"https://t.me/{bot.get_me().username}?start={u.referral_code}"
    bot.send_message(
        call.message.chat.id,
        f"🎁 <b>Referral Program</b>\nInvite friends and get +1 email/day\n\n{link}",
        reply_markup=main_menu(),
    )

# ================= CHECKOUT =================

@bot.callback_query_handler(func=lambda c: c.data == "upgrade")
def upgrade(call):
    text = (
        "💎 <b>Premium Upgrade — 30 Days</b>\n\n"
        f"Price: <b>{PAY_AMOUNT} {PAY_ASSET}</b>\n"
        "Network: <b>TRC20</b>\n\n"
        "📥 Send payment to this address:\n"
        f"<code>{USDT_ADDRESS}</code>\n\n"
        "After sending, confirm with:\n"
        f"<code>/pay TXID {PAY_AMOUNT} {PAY_ASSET}</code>"
    )
    bot.send_message(call.message.chat.id, text, reply_markup=checkout_keyboard())

@bot.callback_query_handler(func=lambda c: c.data == "copy_addr")
def copy_address(call):
    bot.answer_callback_query(call.id, "Address copied!")
    bot.send_message(call.message.chat.id, f"<code>{USDT_ADDRESS}</code>")

@bot.callback_query_handler(func=lambda c: c.data == "show_qr")
def show_qr(call):
    qr = generate_qr(USDT_ADDRESS)
    bot.send_photo(call.message.chat.id, qr, caption="Scan to pay")

# ================= PAYMENTS =================

@bot.message_handler(commands=["pay"])
def pay(msg):
    """
    Usage:
      /pay TXID 10 USDT
    """
    try:
        _, txid, amount, asset = msg.text.split()
        amount = float(amount)
        asset = asset.upper()

        u = get_user(msg.chat.id)

        # Verify on Binance (last 2 hours)
        ok, _data = verify_deposit(txid, amount, asset, minutes=120)
        if not ok:
            bot.send_message(msg.chat.id, "❌ Deposit not found on Binance yet. Try again after confirmations.")
            return

        # Save payment (auto-approved after verification)
        p = create_payment(u.id, txid, str(amount), asset)
        p.status = "approved"

        # Activate premium
        u.plan = "premium"
        u.premium_until = datetime.now(UTC) + relativedelta(days=30)
        save_user(u)

        bot.send_message(
            msg.chat.id,
            "✅ Payment verified on Binance!\n\n💎 Premium activated for 30 days."
        )

        if ADMIN_ID:
            bot.send_message(
                ADMIN_ID,
                f"💰 Auto-approved payment\nUser: {u.telegram_id}\nTXID: {txid}\nAmount: {amount} {asset}"
            )

    except ValueError:
        bot.send_message(msg.chat.id, "Usage: /pay TXID AMOUNT ASSET  (e.g., /pay <txid> 10 USDT)")
    except Exception:
        bot.send_message(msg.chat.id, "❌ Verification error. Please try again later.")

# ================= ADMIN (MANUAL OVERRIDE) =================

@bot.message_handler(commands=["approve"])
@admin_only
def approve_payment(msg):
    try:
        _, pid = msg.text.split()
        pid = int(pid)

        s = db()
        p = s.query(Payment).filter(Payment.id == pid).first()
        if not p:
            bot.send_message(msg.chat.id, "❌ Payment not found")
            s.close()
            return

        user = s.query(User).filter(User.id == p.user_id).first()
        if not user:
            bot.send_message(msg.chat.id, "❌ User not found")
            s.close()
            return

        user.plan = "premium"
        user.premium_until = datetime.now(UTC) + relativedelta(days=30)
        p.status = "approved"

        s.commit()
        telegram_id = user.telegram_id
        s.close()

        bot.send_message(telegram_id, "🎉 <b>Your payment has been approved!</b>\n\n💎 Premium activated for 30 days.")
        bot.send_message(msg.chat.id, f"✅ Payment #{pid} approved and user notified.")
    except:
        bot.send_message(msg.chat.id, "Usage: /approve PAYMENT_ID")

@bot.message_handler(commands=["reject"])
@admin_only
def reject_payment(msg):
    try:
        _, pid = msg.text.split()
        pid = int(pid)

        s = db()
        p = s.query(Payment).filter(Payment.id == pid).first()
        if not p:
            bot.send_message(msg.chat.id, "❌ Payment not found")
            s.close()
            return

        p.status = "rejected"
        s.commit()

        user = s.query(User).filter(User.id == p.user_id).first()
        telegram_id = user.telegram_id if user else None
        s.close()

        if telegram_id:
            bot.send_message(telegram_id, "❌ Your payment was rejected. Please contact support.")
        bot.send_message(msg.chat.id, f"❌ Payment #{pid} rejected and user notified.")
    except:
        bot.send_message(msg.chat.id, "Usage: /reject PAYMENT_ID")

# ================= TELEGRAM STARS =================

@bot.message_handler(commands=["stars"])
def stars(msg):
    inv = stars_invoice(msg.chat.id, 500)
    prices = [LabeledPrice(label="Premium 30 Days", amount=inv["prices"][0]["amount"])]
    bot.send_invoice(
        msg.chat.id,
        inv["title"],
        inv["description"],
        inv["payload"],
        provider_token="",
        currency=inv["currency"],
        prices=prices,
    )

@bot.pre_checkout_query_handler(func=lambda q: True)
def checkout(q):
    bot.answer_pre_checkout_query(q.id, ok=True)

@bot.message_handler(content_types=["successful_payment"])
def paid(msg):
    u = get_user(msg.chat.id)
    u.plan = "premium"
    u.premium_until = datetime.now(UTC) + relativedelta(days=30)
    save_user(u)
    bot.send_message(msg.chat.id, "🎉 <b>Premium Activated for 30 days!</b>")

# ================= STATUS (USER + ADMIN DASHBOARD) =================

@bot.callback_query_handler(func=lambda c: c.data == "status")
def status_callback(call):
    chat_id = call.message.chat.id

    # Admin dashboard
    if chat_id == ADMIN_ID:
        s = db()
        total_users = s.query(User).count()
        total_emails = s.query(Email).count()

        today = datetime.now(UTC).date()
        start = datetime.combine(today, datetime.min.time(), tzinfo=UTC)

        emails_today = s.query(Email).filter(Email.created_at >= start).count()

        revenue_today = 0.0
        payments = s.query(Payment).filter(
            Payment.status == "approved",
            Payment.created_at >= start,
        ).all()

        for p in payments:
            try:
                revenue_today += float(p.amount)
            except:
                pass

        s.close()

        text = (
            "📊 <b>Admin Dashboard</b>\n\n"
            f"👤 Total Users: {total_users}\n"
            f"📧 Total Emails: {total_emails}\n"
            f"📅 Emails Today: {emails_today}\n"
            f"💰 Revenue Today: {revenue_today}\n"
        )
        bot.send_message(chat_id, text, reply_markup=main_menu())
        return

    # Normal user status
    u = get_user(chat_id)
    if u.plan == "premium" and u.premium_until and u.premium_until > datetime.now(UTC):
        bot.send_message(chat_id, f"💎 Premium active until {u.premium_until.date()}", reply_markup=main_menu())
    else:
        bot.send_message(chat_id, f"🆓 Free user\nDaily quota: {u.daily_quota}", reply_markup=main_menu())

# ================= AUTO-EXPIRY WATCHER =================

def subscription_watcher():
    while True:
        try:
            s = db()
            now = datetime.now(UTC)

            expired = s.query(User).filter(
                User.plan == "premium",
                User.premium_until < now,
            ).all()

            for u in expired:
                u.plan = "free"
                u.daily_quota = 2
                bot.send_message(
                    u.telegram_id,
                    "⚠️ Your premium has expired. Renew with /pay to continue premium features."
                )

            s.commit()
            s.close()
        except:
            pass

        time.sleep(3600)  # check every hour

# ================= START =================

print("Bot running...")
threading.Thread(target=subscription_watcher, daemon=True).start()
bot.infinity_polling(skip_pending=True, allowed_updates=["message", "callback_query"])

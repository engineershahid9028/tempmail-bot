# ===========================
# TempMail Enterprise Bot
# ===========================

import os, re, time, threading
from datetime import datetime, UTC
from dateutil.relativedelta import relativedelta

import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

from bs4 import BeautifulSoup
import html2text

from providers import PROVIDER
from ui import main_menu
from db import init_db, db, User, Email, Inbox, Payment
from payments import create_payment, verify_deposit

# ================= CONFIG =================

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

USDT_ADDRESS = os.getenv("USDT_TRC20_ADDRESS")
PAY_AMOUNT = os.getenv("PAYMENT_AMOUNT", "10")
PAY_ASSET = os.getenv("PAYMENT_ASSET", "USDT")

bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")
init_db()

listeners = {}

# ================= HELPERS =================

def extract_otp(text):
    if not text:
        return None

    patterns = [
        r"\b(\d{4,8})\b",
        r"code[^0-9]{0,10}(\d{4,8})",
        r"otp[^0-9]{0,10}(\d{4,8})",
        r"verification[^0-9]{0,10}(\d{4,8})",
    ]

    for p in patterns:
        m = re.search(p, text, re.I)
        if m:
            return m.group(1)

    return None

def extract_otp_from_html(html):
    if not html:
        return None
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(" ", strip=True)
    return extract_otp(text)

def html_to_text(html):
    h = html2text.HTML2Text()
    h.ignore_links = False
    h.ignore_images = True
    h.body_width = 0
    return h.handle(html).strip()

def extract_links(html):
    soup = BeautifulSoup(html, "html.parser")
    links = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        text = a.get_text(strip=True) or "Open Link"
        links.append((text[:32], href))
    return links[:5]

def get_user(tg_id):
    s = db()
    u = s.query(User).filter(User.telegram_id == tg_id).first()
    if not u:
        u = User(telegram_id=tg_id, referral_code=f"REF{tg_id}", last_reset=str(time.time()))
        s.add(u)
        s.commit()
        s.refresh(u)
    s.close()
    return u

def reset_quota(u):
    today = datetime.now(UTC).date().isoformat()
    if u.last_reset != today:
        base = 5 if u.plan == "premium" else 2
        u.daily_quota = base + (u.bonus_quota or 0)
        u.last_reset = today

def save_user(u):
    s = db()
    s.merge(u)
    s.commit()
    s.close()

# ================= EMAIL LISTENER =================

def start_listener(chat_id, email_id, token):
    if email_id in listeners:
        return

    def loop():
        seen = set()
        while True:
            try:
                messages = PROVIDER.messages(token)

                for m in messages:
                    mid = m["id"]
                    if mid in seen:
                        continue
                    seen.add(mid)

                    mail = PROVIDER.message(token, mid)

                    sender = mail.get("from", {}).get("address", "Unknown")
                    subject = mail.get("subject", "No subject")

                    html = mail.get("html") or mail.get("body_html") or ""
                    text = mail.get("text") or mail.get("body") or ""

                    body = html_to_text(html) if html else text

                    otp = (
                        extract_otp(text)
                        or extract_otp(body)
                        or extract_otp_from_html(html)
                    )

                    links = extract_links(html) if html else []

                    # Save email
                    s = db()
                    s.add(Inbox(email_id=email_id, sender=sender, subject=subject, body=body))
                    s.commit()
                    s.close()

                    msg = (
                        "📩 <b>New Email</b>\n\n"
                        f"<b>From:</b> {sender}\n"
                        f"<b>Subject:</b> {subject}\n\n"
                    )

                    if otp:
                        msg += f"🔐 <b>OTP:</b> <code>{otp}</code>\n\n"

                    msg += body[:3000]

                    markup = InlineKeyboardMarkup()

                    for title, url in links:
                        markup.add(InlineKeyboardButton(title, url=url))

                    bot.send_message(chat_id, msg, reply_markup=markup)

                time.sleep(5)

            except Exception as e:
                print("Listener error:", e)
                time.sleep(10)

    t = threading.Thread(target=loop, daemon=True)
    listeners[email_id] = t
    t.start()

# ================= USER COMMANDS =================

@bot.message_handler(commands=["start"])
def start(msg):
    get_user(msg.chat.id)
    bot.send_message(msg.chat.id, "👋 Welcome to TempMail Bot", reply_markup=main_menu())

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

    bot.send_message(call.message.chat.id, f"📧 <b>Your Temp Email</b>\n<code>{email}</code>", reply_markup=main_menu())
    start_listener(call.message.chat.id, e.id, token)

@bot.callback_query_handler(func=lambda c: c.data == "inbox")
def inbox(call):
    u = get_user(call.message.chat.id)

    s = db()
    rows = s.query(Inbox, Email).join(Email, Inbox.email_id == Email.id).filter(
        Email.user_id == u.id
    ).order_by(Inbox.id.desc()).limit(10).all()
    s.close()

    if not rows:
        bot.send_message(call.message.chat.id, "📭 Inbox empty", reply_markup=main_menu())
        return

    text = "📥 <b>Your Inbox</b>\n\n"
    for r, _ in rows:
        otp = extract_otp(r.body)
        text += f"<b>From:</b> {r.sender}\n<b>Subject:</b> {r.subject}\n"
        if otp:
            text += f"🔐 OTP: <code>{otp}</code>\n"
        text += "\n"

    bot.send_message(call.message.chat.id, text, reply_markup=main_menu())

# ================= PAYMENTS =================

@bot.message_handler(commands=["pay"])
def pay(msg):
    try:
        _, txid, amount, asset = msg.text.split()
        amount = float(amount)

        u = get_user(msg.chat.id)

        ok, _ = verify_deposit(txid, amount, asset, minutes=120)
        if not ok:
            bot.send_message(msg.chat.id, "❌ Deposit not found yet")
            return

        p = create_payment(u.id, txid, str(amount), asset)
        p.status = "approved"

        u.plan = "premium"
        u.premium_until = datetime.now(UTC) + relativedelta(days=30)
        save_user(u)

        bot.send_message(msg.chat.id, "✅ Payment verified!\n💎 Premium activated for 30 days.")

    except:
        bot.send_message(msg.chat.id, "Usage: /pay TXID AMOUNT ASSET")

# ================= STATUS =================

@bot.callback_query_handler(func=lambda c: c.data == "status")
def status_callback(call):
    u = get_user(call.message.chat.id)

    if u.plan == "premium" and u.premium_until and u.premium_until > datetime.now(UTC):
        bot.send_message(call.message.chat.id, f"💎 Premium active until {u.premium_until.date()}", reply_markup=main_menu())
    else:
        bot.send_message(call.message.chat.id, f"🆓 Free user\nDaily quota: {u.daily_quota}", reply_markup=main_menu())

# ================= START =================

print("Bot running...")
bot.infinity_polling(skip_pending=True, allowed_updates=["message", "callback_query"])
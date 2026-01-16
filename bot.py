from payments import verify_deposit
import os, re, time, threading
from datetime import datetime, UTC
from dateutil.relativedelta import relativedelta

import telebot
from bs4 import BeautifulSoup
import html2text
from telebot.types import LabeledPrice
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import qrcode
from io import BytesIO

from flask import Flask

from providers import PROVIDER
from ui import main_menu
from db import init_db, db, User, Email, Inbox, Payment
from analytics import get_stats
from payments import create_payment
from stars import stars_invoice


# ================= CONFIG =================

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

USDT_ADDRESS = os.getenv("USDT_TRC20_ADDRESS")
PAY_AMOUNT = os.getenv("PAYMENT_AMOUNT", "10")
PAY_ASSET = os.getenv("PAYMENT_ASSET", "USDT")

bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")
init_db()

listeners = {}

# ================= FLASK SERVER (FOR RAILWAY + APK) =================

app = Flask(__name__)

@app.route("/")
def home():
    return "TempMail Backend Running"

# ================= UI HELPERS =================

def checkout_keyboard():
    kb = InlineKeyboardMarkup()
    kb.row(
        InlineKeyboardButton("📋 Copy Address", callback_data="copy_addr"),
        InlineKeyboardButton("📷 QR Code", callback_data="show_qr"),
    )
    return kb

def generate_qr(address):
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

def extract_otp(text):
    m = re.search(r"(?:otp|code|verification)?[^0-9]{0,10}(\d{4,8})", text, re.I)
    return m.group(1) if m else None

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
        title = a.get_text(strip=True) or "Open Link"
        url = a["href"]
        links.append((title[:32], url))
    return links[:5]

def get_user(tg_id):
    s = db()
    u = s.query(User).filter(User.telegram_id == tg_id).first()
    if not u:
        u = User(
            telegram_id=tg_id,
            referral_code=f"REF{tg_id}",
            last_reset=str(time.time()),
            daily_quota=2,
            plan="free"
        )
        s.add(u)
        s.commit()
        s.refresh(u)
    s.close()
    return u

def reset_quota(u):
    today = datetime.now(UTC).date().isoformat()
    if u.last_reset != today:
        base = 5 if u.plan == "premium" else 2
        u.daily_quota = base
        u.last_reset = today

def save_user(u):
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
                    subject = mail.get("subject", "No Subject")

                    html = ""
                    if "html" in mail and mail["html"]:
                        html = mail["html"][0]

                    text = mail.get("text", "")

                    if html:
                        body = html_to_text(html)
                        links = extract_links(html)
                    else:
                        body = text
                        links = []

                    s = db()
                    s.add(Inbox(
                        email_id=email_id,
                        sender=sender,
                        subject=subject,
                        body=body,
                    ))
                    s.commit()
                    s.close()

                    otp = extract_otp(body)

                    msg = (
                        "📩 <b>New Email</b>\n\n"
                        f"<b>From:</b> {sender}\n"
                        f"<b>Subject:</b> {subject}\n\n"
                    )

                    if otp:
                        msg += f"🔐 <b>OTP:</b> <code>{otp}</code>\n\n"

                    msg += body[:3500]

                    markup = InlineKeyboardMarkup()
                    for title, url in links:
                        markup.add(InlineKeyboardButton(title, url=url))

                    bot.send_message(chat_id, msg, reply_markup=markup)

                time.sleep(6)
            except Exception as e:
                print("Listener error:", e)
                time.sleep(10)

    t = threading.Thread(target=loop, daemon=True)
    listeners[email_id] = t
    t.start()

# ================= USER COMMANDS =================

@bot.message_handler(commands=['start'])
def start(msg):
    get_user(msg.chat.id)
    bot.send_message(
        msg.chat.id,
        "👋 <b>Welcome to TempMail Premium Bot!</b>",
        reply_markup=main_menu()
    )

@bot.callback_query_handler(func=lambda c: c.data == 'newmail')
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
        reply_markup=main_menu()
    )

    start_listener(call.message.chat.id, e.id, token)

# ================= START SERVICES =================

def subscription_watcher():
    while True:
        try:
            s = db()
            now = datetime.utcnow()

            expired = s.query(User).filter(
                User.plan == "premium",
                User.premium_until < now
            ).all()

            for u in expired:
                u.plan = "free"
                u.daily_quota = 2
                bot.send_message(
                    u.telegram_id,
                    "⚠️ Your premium has expired."
                )

            s.commit()
            s.close()
        except:
            pass

        time.sleep(3600)

def run_bot():
    bot.infinity_polling(skip_pending=True, allowed_updates=["message", "callback_query"])

# ================= MAIN =================

print("Bot running...")

threading.Thread(target=subscription_watcher, daemon=True).start()
threading.Thread(target=run_bot, daemon=True).start()

port = int(os.environ.get("PORT", 8080))
app.run(host="0.0.0.0", port=port)
import os, re, time, threading
from datetime import datetime
from dateutil.relativedelta import relativedelta
import telebot
from telebot.types import LabeledPrice

from providers import PROVIDER
from ui import main_menu
from db import init_db, db, User, Email, Inbox, Payment
from analytics import get_stats
from payments import create_payment
from stars import stars_invoice

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID","0"))

bot = telebot.TeleBot(BOT_TOKEN)
init_db()

listeners = {}

# ---------- Helpers ----------

def admin_only(func):
    def wrapper(msg):
        if msg.chat.id != ADMIN_ID:
            return
        return func(msg)
    return wrapper

def extract_otp(text):
    m = re.search(r"(?:otp|code|verification)?[^0-9]{0,10}(\d{4,8})", text, re.I)
    return m.group(1) if m else None

def get_user(tg_id):
    s = db()
    u = s.query(User).filter(User.telegram_id==tg_id).first()
    if not u:
        u = User(telegram_id=tg_id, referral_code=f"REF{tg_id}", last_reset=str(time.time()))
        s.add(u); s.commit(); s.refresh(u)
    s.close()
    return u

def reset_quota(u):
    today = datetime.utcnow().date().isoformat()
    if u.last_reset != today:
        base = 5 if u.plan=="premium" else 2
        u.daily_quota = base + (u.bonus_quota or 0)
        u.last_reset = today

def save_user(u):
    s=db(); s.merge(u); s.commit(); s.close()

# ---------- OTP Listener ----------

def start_listener(chat_id, email_id, token):
    if email_id in listeners: return
    def loop():
        seen=set()
        while True:
            try:
                for m in PROVIDER.messages(token):
                    mid=m["id"]
                    if mid in seen: continue
                    seen.add(mid)
                    mail=PROVIDER.message(token, mid)
                    sender=mail["from"]["address"]
                    subject=mail["subject"]
                    body=mail.get("text","")

                    s=db()
                    s.add(Inbox(email_id=email_id, sender=sender, subject=subject, body=body))
                    s.commit()
                    s.close()

                    otp=extract_otp(body)
                    text=f"📩 New Email\n\nFrom: {sender}\nSubject: {subject}\n"
                    if otp: text+=f"\n🔐 OTP: {otp}"
                    bot.send_message(chat_id, text, reply_markup=main_menu())
                time.sleep(6)
            except:
                time.sleep(10)

    t=threading.Thread(target=loop, daemon=True)
    listeners[email_id]=t
    t.start()

# ---------- User Commands ----------

@bot.message_handler(commands=['start'])
def start(msg):
    get_user(msg.chat.id)
    bot.send_message(msg.chat.id, "👋 Welcome to TempMail Bot!", reply_markup=main_menu())

@bot.callback_query_handler(func=lambda c: c.data=='newmail')
def newmail(call):
    u=get_user(call.message.chat.id)
    reset_quota(u)
    if u.daily_quota<=0:
        bot.send_message(call.message.chat.id, "❌ Daily quota reached", reply_markup=main_menu())
        return

    email, token = PROVIDER.create()
    s=db()
    e=Email(user_id=u.id, email=email, token=token)
    s.add(e); s.commit(); s.refresh(e); s.close()

    u.daily_quota-=1
    save_user(u)

    bot.send_message(call.message.chat.id, f"📧 Your Temp Email:\n{email}\n\nAuto-fetch enabled", reply_markup=main_menu())
    start_listener(call.message.chat.id, e.id, token)

@bot.callback_query_handler(func=lambda c: c.data=='reuse')
def reuse(call):
    u=get_user(call.message.chat.id)
    if u.plan!='premium':
        bot.send_message(call.message.chat.id, "❌ Premium only", reply_markup=main_menu())
        return

    s=db()
    e=s.query(Email).filter(Email.user_id==u.id).order_by(Email.id.desc()).first()
    s.close()

    if not e:
        bot.send_message(call.message.chat.id, "No previous email", reply_markup=main_menu())
        return

    bot.send_message(call.message.chat.id, f"♻️ Reusing:\n{e.email}\nAuto-fetch enabled", reply_markup=main_menu())
    start_listener(call.message.chat.id, e.id, e.token)

@bot.callback_query_handler(func=lambda c: c.data=='inbox')
def inbox(call):
    u=get_user(call.message.chat.id)
    s=db()
    rows=s.query(Inbox, Email).join(Email, Inbox.email_id==Email.id).filter(Email.user_id==u.id).order_by(Inbox.id.desc()).limit(10).all()
    s.close()

    if not rows:
        bot.send_message(call.message.chat.id, "📭 Inbox empty", reply_markup=main_menu())
        return

    text="📥 Your Inbox\n\n"
    for r,e in rows:
        otp=extract_otp(r.body or "")
        text+=f"From: {r.sender}\nSubject: {r.subject}\n"
        if otp: text+=f"OTP: {otp}\n"
        text+="\n"

    bot.send_message(call.message.chat.id, text, reply_markup=main_menu())

@bot.callback_query_handler(func=lambda c: c.data=='referral')
def referral(call):
    u=get_user(call.message.chat.id)
    link=f"https://t.me/{bot.get_me().username}?start={u.referral_code}"
    bot.send_message(call.message.chat.id, f"🎁 Referral\nInvite friends for +1/day\n\n{link}", reply_markup=main_menu())

@bot.callback_query_handler(func=lambda c: c.data=='upgrade')
def upgrade(call):
    bot.send_message(call.message.chat.id, "💎 Upgrade Options:\n1) /pay TXID AMOUNT CUR\n2) /stars (Telegram Stars)")

# ---------- Payments ----------

@bot.message_handler(commands=['pay'])
def pay(msg):
    try:
        _, txid, amount, cur = msg.text.split()
        u=get_user(msg.chat.id)
        p=create_payment(u.id, txid, amount, cur)

        bot.send_message(msg.chat.id, "✅ Payment submitted. Waiting for admin approval.")

        if ADMIN_ID:
            bot.send_message(
                ADMIN_ID,
                f"💳 New Payment Request\n\n"
                f"Payment ID: {p.id}\n"
                f"User: {u.telegram_id}\n"
                f"TXID: {txid}\n"
                f"Amount: {amount} {cur}\n\n"
                f"Approve: /approve {p.id}\n"
                f"Reject: /reject {p.id}"
            )
    except:
        bot.send_message(msg.chat.id, "Usage: /pay TXID AMOUNT CUR")

# ---------- Admin Approval ----------

@bot.message_handler(commands=['approve'])
@admin_only
def approve_payment(msg):
    try:
        _, pid = msg.text.split()
        pid = int(pid)

        s=db()
        p = s.query(Payment).filter(Payment.id==pid).first()
        if not p:
            bot.send_message(msg.chat.id, "❌ Payment not found")
            return

        p.status = "approved"
        user = s.query(User).filter(User.id==p.user_id).first()
        user.plan = "premium"
        user.premium_until = datetime.utcnow() + relativedelta(days=30)

        s.commit()
        s.close()

        bot.send_message(msg.chat.id, f"✅ Payment #{pid} approved")
        bot.send_message(user.telegram_id, "🎉 Your premium has been activated for 30 days!")

    except:
        bot.send_message(msg.chat.id, "Usage: /approve PAYMENT_ID")

@bot.message_handler(commands=['reject'])
@admin_only
def reject_payment(msg):
    try:
        _, pid = msg.text.split()
        pid = int(pid)

        s=db()
        p = s.query(Payment).filter(Payment.id==pid).first()
        if not p:
            bot.send_message(msg.chat.id, "❌ Payment not found")
            return

        p.status = "rejected"
        s.commit()
        s.close()

        bot.send_message(msg.chat.id, f"❌ Payment #{pid} rejected")

    except:
        bot.send_message(msg.chat.id, "Usage: /reject PAYMENT_ID")

# ---------- Telegram Stars ----------

@bot.message_handler(commands=['stars'])
def stars(msg):
    inv=stars_invoice(msg.chat.id, 500)
    prices=[LabeledPrice(label='Premium 30 Days', amount=inv['prices'][0]['amount'])]
    bot.send_invoice(msg.chat.id, inv['title'], inv['description'], inv['payload'], provider_token="", currency=inv['currency'], prices=prices)

@bot.pre_checkout_query_handler(func=lambda q: True)
def checkout(q):
    bot.answer_pre_checkout_query(q.id, ok=True)

@bot.message_handler(content_types=['successful_payment'])
def paid(msg):
    u=get_user(msg.chat.id)
    u.plan='premium'
    u.premium_until=datetime.utcnow()+relativedelta(days=30)
    save_user(u)
    bot.send_message(msg.chat.id, "🎉 Premium Activated for 30 days!")

# ---------- Status & Stats ----------

@bot.message_handler(commands=['status'])
def status(msg):
    u=get_user(msg.chat.id)
    if u.plan=='premium' and u.premium_until and u.premium_until>datetime.utcnow():
        bot.send_message(msg.chat.id, f"💎 Premium active until {u.premium_until.date()}", reply_markup=main_menu())
    else:
        bot.send_message(msg.chat.id, f"🆓 Free user\nDaily quota: {u.daily_quota}", reply_markup=main_menu())

@bot.message_handler(commands=['stats'])
@admin_only
def stats(msg):
    s=get_stats()
    bot.send_message(msg.chat.id, f"📊 Stats\nUsers:{s['users']} Emails:{s['emails']} Messages:{s['messages']} Payments:{s['payments']} Pending:{s['pending']}")

print("Bot running...")
bot.infinity_polling()

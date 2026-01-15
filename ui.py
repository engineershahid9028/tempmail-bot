
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

def main_menu():
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("📧 New Email", callback_data="newmail"),
        InlineKeyboardButton("📥 Inbox", callback_data="inbox"),
        InlineKeyboardButton("♻️ Reuse Email", callback_data="reuse"),
        InlineKeyboardButton("🎁 Referral", callback_data="referral"),
        InlineKeyboardButton("💎 Upgrade", callback_data="upgrade"),
        InlineKeyboardButton("📊 Status", callback_data="status"),
    )
    return kb


import os, redis, psycopg2
import telebot

BOT_TOKEN = os.getenv("BOT_TOKEN")
REDIS_URL = os.getenv("REDIS_URL")
DATABASE_URL = os.getenv("DATABASE_URL")

r = redis.from_url(REDIS_URL)
db = psycopg2.connect(DATABASE_URL)
bot = telebot.TeleBot(BOT_TOKEN)

@bot.message_handler(commands=['start'])
def start(msg):
    bot.send_message(msg.chat.id, "🚀 Welcome to TempMail Enterprise Plus")

print("Bot running...")
bot.infinity_polling()

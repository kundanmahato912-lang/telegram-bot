import json
import os
import random
import string
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes
from datetime import datetime

BOT_TOKEN = '8295141633:AAFCy_rNDTdSEm6O7Wtbd9SqmTB1DIeJ2zg'
CHANNEL_ID = -100123456789  # Replace with your actual channel ID

# Load or initialize user codes
if os.path.exists("user_codes.json"):
    with open("user_codes.json", "r") as f:
        user_codes = json.load(f)
else:
    user_codes = {}

def save_codes():
    with open("user_codes.json", "w", encoding="utf-8") as f:
        json.dump(user_codes, f, ensure_ascii=False)

def generate_code():
    return ''.join(random.choices(string.ascii_uppercase, k=8))

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.message.from_user.id)

    if user_id not in user_codes:
        user_codes[user_id] = generate_code()
        save_codes()

    keyboard = [
        [InlineKeyboardButton("Join Channel", url="https://t.me/earning_don_00")],
        [InlineKeyboardButton("Verify", callback_data="verify")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Hello! Join the telegram channel and verify", reply_markup=reply_markup)

async def verify(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.callback_query.from_user.id)
    chat_member = await context.bot.get_chat_member(chat_id=CHANNEL_ID, user_id=int(user_id))

    if chat_member.status in ['member', 'administrator', 'creator']:
        code = user_codes.get(user_id)
        print(f"[{datetime.now()}] ✅ User {user_id} verified with code: {code}")

        keyboard = [[InlineKeyboardButton("Scratch Card", url="https://scratchcard.page.gd")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.callback_query.message.reply_text(
            f"🎉 Congratulations! You win a scratch card\nYour code: `{code}`",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
    else:
        keyboard = [
            [InlineKeyboardButton("Join Channel", url="https://t.me/earning_don_00")],
            [InlineKeyboardButton("Verify", callback_data="verify")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.callback_query.message.reply_text("❌ Try again! Please join the channel first.", reply_markup=reply_markup)

import asyncio

async def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(verify, pattern="verify"))
    await app.run_polling()

if __name__ == '__main__':
    asyncio.run(main())

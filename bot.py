import os, threading
from flask import Flask
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes

BOT_TOKEN = '8295141633:AAFCy_rNDTdSEm6O7Wtbd9SqmTB1DIeJ2zg'
CHANNEL_USERNAME = '@earning_don_00'

# Load or initialize user codes
if os.path.exists("user_codes.json"):
    with open("user_codes.json", "r") as f:
        user_codes = json.load(f)
else:
    user_codes = {}

def save_codes():
    with open("user_codes.json", "w") as f:
        json.dump(user_codes, f)

def generate_code():
    return ''.join(random.choices(string.ascii_uppercase, k=8))

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.message.from_user.id)

    # Assign code only once
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
    chat_member = await context.bot.get_chat_member(chat_id=CHANNEL_USERNAME, user_id=int(user_id))

    if chat_member.status in ['member', 'administrator', 'creator']:
        code = user_codes.get(user_id)
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

def run_bot():
    app = ApplicationBuilder().token(os.getenv("BOT_TOKEN")).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(verify, pattern="verify"))
    app.run_polling()

flask_app = Flask(__name__)

@flask_app.route("/")
def health():
    return "ok"

if __name__ == "__main__":
    threading.Thread(target=run_bot, daemon=True).start()
    port = int(os.getenv("PORT", 10000))
    flask_app.run(host="0.0.0.0", port=port)
    

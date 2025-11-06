import os
import json
import string
import secrets
import logging
import asyncio
from pathlib import Path
from threading import Thread
from flask import Flask, request, abort

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ChatMemberStatus, ParseMode
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)

# ================== CONFIG (Env से) ==================
BOT_TOKEN = os.environ.get("BOT_TOKEN")  # required
CHANNEL_USERNAME = os.environ.get("CHANNEL_USERNAME", "@earning_don_00")  # default दिया
WEBHOOK_URL = os.environ.get("WEBHOOK_URL")  # required: https://<app>.onrender.com/webhook
SECRET_TOKEN = os.environ.get("SECRET_TOKEN", "change-me")  # Telegram header verify
CODES_FILE = Path("user_codes.json")
# =====================================================

# ---- basic checks ----
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN env var is required")
if not WEBHOOK_URL:
    raise RuntimeError("WEBHOOK_URL env var is required (full https url to /webhook)")

# Logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("flask-bot")

# Flask app
app = Flask(__name__)

# Telegram Application (PTB v20)
application = ApplicationBuilder().token(BOT_TOKEN).build()

# Async event loop in background thread (ताकि Flask sync रह सके)
loop = asyncio.new_event_loop()

# ---------------- Utils / Storage ----------------
def generate_code(length: int = 8) -> str:
    alphabet = string.ascii_uppercase
    return "".join(secrets.choice(alphabet) for _ in range(length))

user_codes: dict[str, str] = {}
codes_lock = asyncio.Lock()

async def load_codes() -> None:
    """user_codes.json load करें"""
    global user_codes
    if CODES_FILE.exists():
        try:
            async with codes_lock:
                user_codes = json.loads(CODES_FILE.read_text(encoding="utf-8"))
                log.info("Loaded %d user codes", len(user_codes))
        except Exception as e:
            log.warning("Failed to read user_codes.json: %s", e)
            user_codes = {}
    else:
        user_codes = {}

async def save_codes() -> None:
    """user_codes.json save करें"""
    try:
        async with codes_lock:
            CODES_FILE.write_text(
                json.dumps(user_codes, ensure_ascii=False),
                encoding="utf-8",
            )
    except Exception as e:
        log.error("Failed to write user_codes.json: %s", e)

def main_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Join Channel", url="https://t.me/earning_don_00")],
        [InlineKeyboardButton("Verify", callback_data="verify")]
    ])

# ---------------- Handlers ----------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    log.info("Handling /start for user: %s", user.id if user else None)
    if not user:
        return
    uid = str(user.id)

    if uid not in user_codes:
        user_codes[uid] = generate_code()
        await save_codes()

    await update.effective_chat.send_message(
        "Hello! Join the telegram channel and verify",
        reply_markup=main_keyboard(),
    )

async def verify(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return
    await query.answer()

    uid = str(query.from_user.id)
    log.info("Verify pressed by user: %s", uid)

    try:
        member = await context.bot.get_chat_member(chat_id=CHANNEL_USERNAME, user_id=int(uid))
        is_member = member.status in {
            ChatMemberStatus.MEMBER,
            ChatMemberStatus.ADMINISTRATOR,
            ChatMemberStatus.OWNER,
        }
    except Exception as e:
        log.warning("get_chat_member failed: %s", e)
        is_member = False

    if is_member:
        code = user_codes.get(uid)
        kb = InlineKeyboardMarkup(
            [[InlineKeyboardButton("Scratch Card", url="https://scratchcard.page.gd")]]
        )
        await query.message.reply_text(
            f"🎉 Congratulations! You win a scratch card\nYour code: `{code}`",
            reply_markup=kb,
            parse_mode=ParseMode.MARKDOWN,
        )
    else:
        await query.message.reply_text(
            "❌ Try again! Please join the channel first.",
            reply_markup=main_keyboard(),
        )

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    log.exception("Handler error: %s", context.error)

# ------------- PTB startup/shutdown -------------
async def ptb_startup():
    # register handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(verify, pattern="^verify$"))
    application.add_error_handler(error_handler)

    await load_codes()
    await application.initialize()
    await application.start()

    # set webhook (drop old updates)
    await application.bot.set_webhook(
        url=WEBHOOK_URL,
        secret_token=SECRET_TOKEN,
        drop_pending_updates=True,
    )
    log.info("Webhook set to %s", WEBHOOK_URL)

async def ptb_shutdown():
    try:
        await application.bot.delete_webhook(drop_pending_updates=True)
    except Exception:
        pass
    await application.stop()
    await application.shutdown()

def run_loop_forever():
    asyncio.set_event_loop(loop)
    loop.run_forever()


bot_started = False

@app.before_first_request
def start_bot_in_worker():
    global bot_started
    if bot_started:
        return
    bot_started = True
    # background loop/thread start
    bg = Thread(target=run_loop_forever, daemon=True)
    bg.start()
    asyncio.run_coroutine_threadsafe(ptb_startup(), loop)
    log.info("PTB started in gunicorn worker")


# ---------------- Flask routes ----------------
@app.route("/", methods=["GET"])
def index():
    return "Bot is alive", 200

@app.route("/webhook", methods=["POST"])
def telegram_webhook():
    # Verify Telegram secret token (set in set_webhook above)
    if request.headers.get("X-Telegram-Bot-Api-Secret-Token") != SECRET_TOKEN:
        log.warning("Webhook hit with wrong/missing secret")
        abort(403)

    data = request.get_json(force=True, silent=True)
    if not data:
        log.warning("Webhook got empty/invalid JSON")
        return "no json", 400

    # helpful trace
    try:
        txt = data.get("message", {}).get("text")
        cb  = data.get("callback_query", {}).get("data")
        log.info("Webhook update: %s", txt or cb)
    except Exception:
        pass

    update = Update.de_json(data, application.bot)
    # hand over to PTB (non-blocking)
    asyncio.run_coroutine_threadsafe(application.process_update(update), loop)
    return "ok", 200

# graceful shutdown (optional)
@app.route("/shutdown", methods=["POST"])
def shutdown():
    asyncio.run_coroutine_threadsafe(ptb_shutdown(), loop)
    return "shutting down", 200

# local dev entrypoint
if __name__ == "__main__":
    # For local testing with something like ngrok tunneling:
    # export BOT_TOKEN=..., WEBHOOK_URL=https://<ngrok-id>.ngrok.io/webhook
    port = int(os.environ.get("PORT", 8000))
    app.run(host="0.0.0.0", port=port)

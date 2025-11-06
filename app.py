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

# ================== ENV CONFIG ==================
BOT_TOKEN = os.environ.get("BOT_TOKEN")  # required
CHANNEL_USERNAME = os.environ.get("CHANNEL_USERNAME", "@earning_don_00")
WEBHOOK_URL = os.environ.get("WEBHOOK_URL")  # required: https://<app>.onrender.com/webhook
SECRET_TOKEN = os.environ.get("SECRET_TOKEN", "change-me")
CODES_FILE = Path("user_codes.json")
# =================================================

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN env var is required")
if not WEBHOOK_URL:
    raise RuntimeError("WEBHOOK_URL env var is required (full https url to /webhook)")

# -------- Logging --------
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("flask-bot")

# -------- Flask --------
app = Flask(__name__)

# -------- PTB (v20) --------
application = ApplicationBuilder().token(BOT_TOKEN).build()

# Single event loop in a background thread
loop = asyncio.new_event_loop()
ptb_started = False  # guard so we don't start twice

# -------- Storage / Utils --------
def generate_code(length: int = 8) -> str:
    alphabet = string.ascii_uppercase
    return "".join(secrets.choice(alphabet) for _ in range(length))

user_codes: dict[str, str] = {}
codes_lock = asyncio.Lock()

async def load_codes() -> None:
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

# -------- Handlers --------
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
    log.info("Sent /start reply to %s", uid)

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

# -------- PTB lifecycle --------
async def ptb_startup():
    global ptb_started
    if ptb_started:
        return
    ptb_started = True

    # register handlers (idempotent)
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(verify, pattern="^verify$"))
    application.add_error_handler(error_handler)

    await load_codes()
    await application.initialize()
    await application.start()

    await application.bot.set_webhook(
        url=WEBHOOK_URL,
        secret_token=SECRET_TOKEN,
        drop_pending_updates=True,
    )
    log.info("Webhook set to %s", WEBHOOK_URL)

async def ptb_shutdown():
    global ptb_started
    if not ptb_started:
        return
    try:
        await application.bot.delete_webhook(drop_pending_updates=True)
    except Exception:
        pass
    await application.stop()
    await application.shutdown()
    ptb_started = False

def run_loop_forever():
    asyncio.set_event_loop(loop)
    loop.run_forever()

# ---- start loop + PTB at import-time (safe with workers=1, no --preload) ----
bg = Thread(target=run_loop_forever, daemon=True)
bg.start()
asyncio.run_coroutine_threadsafe(ptb_startup(), loop)
log.info("PTB started (import-time)")

# ---------------- Flask routes ----------------
@app.route("/", methods=["GET"])
def index():
    return "Bot is alive", 200

@app.route("/webhook", methods=["POST"])
def telegram_webhook():
    # Verify Telegram secret token
    if request.headers.get("X-Telegram-Bot-Api-Secret-Token") != SECRET_TOKEN:
        log.warning("Webhook hit with wrong/missing secret")
        abort(403)

    data = request.get_json(force=True, silent=True)
    if not data:
        log.warning("Webhook got empty/invalid JSON")
        return "no json", 400

    # trace for debugging
    txt = (data.get("message") or {}).get("text")
    cb  = (data.get("callback_query") or {}).get("data")
    log.info("Webhook update: %s", txt or cb)

    # If for some reason PTB stopped, start it on-demand
    try:
        if not getattr(application, "running", False):
            log.warning("PTB not running. Starting on-demand...")
            asyncio.run_coroutine_threadsafe(ptb_startup(), loop)
    except Exception as e:
        log.warning("PTB running check failed: %s", e)

    update = Update.de_json(data, application.bot)
    asyncio.run_coroutine_threadsafe(application.process_update(update), loop)
    return "ok", 200

@app.route("/shutdown", methods=["POST"])
def shutdown():
    asyncio.run_coroutine_threadsafe(ptb_shutdown(), loop)
    return "shutting down", 200

# Local dev (optional)
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    app.run(host="0.0.0.0", port=port)
    

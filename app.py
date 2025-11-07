# app.py
import os
import json
import random
import string
import threading
from datetime import datetime
from flask import Flask, request, jsonify
import requests

app = Flask(__name__)

# ====== CONFIG ======
BOT_TOKEN = os.environ.get("TELEGRAM_TOKEN", "").strip()
if not BOT_TOKEN:
    raise RuntimeError("Missing TELEGRAM_TOKEN environment variable.")

API_BASE = f"https://api.telegram.org/bot{BOT_TOKEN}"
CHANNEL_USERNAME = os.environ.get("CHANNEL_USERNAME", "@earning_don_00").strip()
WEBHOOK_URL = os.environ.get("WEBHOOK_URL", "").strip()

CHANNEL_LINK = "https://t.me/earning_don_00"
SCRATCH_LINK = "https://scratchcard.page.gd"

USERS_FILE = "users.json"
LOG_FILE = "logs.txt"
_file_lock = threading.Lock()


def tg_request(method: str, payload: dict):
    url = f"{API_BASE}/{method}"
    r = requests.post(url, json=payload, timeout=20)
    try:
        return r.json()
    except Exception:
        return {"ok": False, "error": r.text}


def send_message(chat_id, text, reply_markup=None, parse_mode="HTML"):
    payload = {"chat_id": chat_id, "text": text, "parse_mode": parse_mode}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    return tg_request("sendMessage", payload)


def answer_callback_query(callback_query_id, text=None):
    payload = {"callback_query_id": callback_query_id}
    if text:
        payload["text"] = text
    return tg_request("answerCallbackQuery", payload)


def get_member_status(user_id):
    """जाँच करता है कि यूज़र चैनल में जुड़ा है या नहीं"""
    resp = requests.get(
        f"{API_BASE}/getChatMember",
        params={"chat_id": CHANNEL_USERNAME, "user_id": user_id},
        timeout=20
    ).json()

    if not resp.get("ok"):
        return False

    status = resp["result"].get("status", "")
    if status in ("member", "administrator", "creator"):
        return True

    if status == "restricted" and resp["result"].get("is_member"):
        return True

    return False


def load_users():
    with _file_lock:
        if not os.path.exists(USERS_FILE):
            return {}
        try:
            with open(USERS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}


def save_users(data):
    with _file_lock:
        with open(USERS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)


def get_or_create_code(user_id, username):
    """हर यूज़र को सिर्फ एक बार 8-digit कोड देता है"""
    users = load_users()
    key = str(user_id)
    if key in users and "code" in users[key]:
        return users[key]["code"]

    code = "".join(random.choices(string.digits, k=8))
    users[key] = {"code": code, "username": username or ""}
    save_users(users)

    # लॉग्स में सेव करें
    line = f"{datetime.utcnow().isoformat()}Z\t{username or user_id}\t{code}\n"
    with _file_lock:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line)

    return code


def join_and_verify_keyboard():
    return {
        "inline_keyboard": [
            [{"text": "Join Channel", "url": CHANNEL_LINK}],
            [{"text": "✅ Verify", "callback_data": "verify"}]
        ]
    }


def send_join_prompt(chat_id):
    text = "hello Join the telegram channel and verify"
    return send_message(chat_id, text, reply_markup=join_and_verify_keyboard())


@app.route("/", methods=["GET"])
def index():
    return jsonify({"ok": True, "msg": "Bot is running"})


@app.route("/setwebhook", methods=["GET"])
def set_webhook():
    if not WEBHOOK_URL:
        return jsonify({"ok": False, "error": "WEBHOOK_URL env var not set"}), 400
    resp = requests.post(
        f"{API_BASE}/setWebhook",
        json={"url": WEBHOOK_URL, "drop_pending_updates": True},
        timeout=20
    ).json()
    return jsonify(resp)


@app.route("/webhook", methods=["POST"])
def webhook():
    update = request.get_json(silent=True) or {}

    # Verify बटन
    if "callback_query" in update:
        cq = update["callback_query"]
        user = cq.get("from", {})
        user_id = user.get("id")
        username = ("@" + user["username"]) if user.get("username") else user.get("first_name", "")
        chat_id = cq["message"]["chat"]["id"]
        data = cq.get("data")

        if data == "verify":
            answer_callback_query(cq["id"], "Checking your membership...")
            if get_member_status(user_id):
                code = get_or_create_code(user_id, username)
                text = f"congratulation you win a scratch card\n\nYour code: <code>{code}</code>"
                kb = {"inline_keyboard": [[{"text": "🎟️ Open Scratch Card", "url": SCRATCH_LINK}]]}
                send_message(chat_id, text, reply_markup=kb)
            else:
                send_message(chat_id, "try again")
                send_join_prompt(chat_id)
        return jsonify({"ok": True})

    # /start कमांड
    if "message" in update:
        msg = update["message"]
        chat_id = msg["chat"]["id"]
        text = msg.get("text", "")
        if text.startswith("/start"):
            send_join_prompt(chat_id)
        else:
            send_join_prompt(chat_id)

    return jsonify({"ok": True})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    app.run(host="0.0.0.0", port=port)

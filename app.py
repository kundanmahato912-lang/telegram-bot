import os, json, random, string
from datetime import datetime
from flask import Flask, request, jsonify
import requests

app = Flask(__name__)

# ===== CONFIG =====

BOT_TOKEN = os.environ.get("TELEGRAM_TOKEN", "").strip()
API_BASE = f"https://api.telegram.org/bot{BOT_TOKEN}"

CHANNEL_USERNAME = "@earning_don_00"
CHANNEL_LINK = "https://t.me/earning_don_00"
SCRATCH_LINK = "https://scratchcard.page.gd"

BOT_USERNAME = "Scratch_card_00_bot"
ADMIN_ID = 7336276055

USERS_FILE = "users.json"
REDEEM_FILE = "redeems.json"
LOG_FILE = "logs.txt"

# ===== ENSURE FILES =====

def ensure_files():
    for f in [USERS_FILE, REDEEM_FILE, LOG_FILE]:
        if not os.path.exists(f):
            with open(f, "w", encoding="utf-8") as fp:
                fp.write("{}" if f.endswith(".json") else "")

ensure_files()

# ===== STORAGE =====

def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return {}

def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

# ===== LOG =====

def append_log(text):
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(text + "\n")

# ===== TELEGRAM HELPERS =====

def tg_request(method, payload):
    return requests.post(f"{API_BASE}/{method}", json=payload).json()

def send_message(chat_id, text, reply_markup=None):
    data = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    if reply_markup:
        data["reply_markup"] = reply_markup
    tg_request("sendMessage", data)

def get_member_status(uid):
    r = requests.get(
        f"{API_BASE}/getChatMember",
        params={"chat_id": CHANNEL_USERNAME, "user_id": uid}
    ).json()
    return r.get("ok") and r["result"]["status"] in ("member","administrator","creator")

def get_safe_username(user):
    return "@" + user["username"] if user.get("username") else f"User_{user['id']}"

# ===== REFERRAL =====

def handle_referral(new_uid, ref_uid):
    users = load_json(USERS_FILE)
    new_uid, ref_uid = str(new_uid), str(ref_uid)

    if new_uid == ref_uid or new_uid in users or ref_uid not in users:
        return

    users[new_uid] = {
        "username": "",
        "points": 0,
        "code": None,
        "referred_by": ref_uid,
        "referral_paid": False,
        "redeem_pending": False
    }
    save_json(USERS_FILE, users)

def referral_link(uid):
    return f"https://t.me/{BOT_USERNAME}?start={uid}"

# ===== SCRATCH =====

def get_or_create_code(uid, username):
    users = load_json(USERS_FILE)
    uid = str(uid)

    if uid not in users:
        users[uid] = {
            "username": username,
            "points": 0,
            "code": None,
            "referred_by": None,
            "referral_paid": False,
            "redeem_pending": False
        }

    users[uid]["username"] = username

    if users[uid]["code"]:
        return users[uid]["code"]

    code = "".join(random.choices(string.digits, k=8))
    users[uid]["code"] = code
    save_json(USERS_FILE, users)
    return code

# ===== KEYBOARDS =====

def join_kb():
    return {
        "inline_keyboard": [
            [{"text": "Join Channel", "url": CHANNEL_LINK}],
            [{"text": "✅ Verify", "callback_data": "verify"}]
        ]
    }

def main_menu(uid):
    kb = [
        ["🎁 Refer & Earn", "💰 My Points"],
        ["🏧 Redeem"]
    ]
    if int(uid) == ADMIN_ID:
        kb.append(["📊 Admin Stats"])
    return {"keyboard": kb, "resize_keyboard": True}

def redeem_kb():
    return {
        "inline_keyboard": [
            [{"text": "10 Points → ₹10", "callback_data": "redeem_10"}],
            [{"text": "20 Points → ₹20", "callback_data": "redeem_20"}],
            [{"text": "50 Points → ₹55", "callback_data": "redeem_50"}],
            [{"text": "100 Points → ₹120", "callback_data": "redeem_100"}]
        ]
    }

# ===== WEBHOOK =====

@app.route("/webhook", methods=["POST"])
def webhook():
    update = request.json or {}

    # ===== CALLBACK =====
    if "callback_query" in update:
        cq = update["callback_query"]
        uid = str(cq["from"]["id"])
        chat_id = cq["message"]["chat"]["id"]
        data = cq["data"]

        users = load_json(USERS_FILE)

        if data == "verify":
            if get_member_status(uid):
                code = get_or_create_code(uid, get_safe_username(cq["from"]))

                if users[uid]["referred_by"] and not users[uid]["referral_paid"]:
                    ref = users[uid]["referred_by"]
                    users[ref]["points"] += 2
                    users[uid]["referral_paid"] = True
                    save_json(USERS_FILE, users)
                    append_log(f"{datetime.utcnow()} REFERRAL +2 | {ref}")

                send_message(chat_id,
                    f"🎉 Scratch Code:\n<code>{code}</code>",
                    {"inline_keyboard":[[{"text":"🎟 Open Scratch","url":SCRATCH_LINK}]]}
                )
                send_message(chat_id, "👇 Choose option", main_menu(uid))
            else:
                send_message(chat_id, "❌ Join channel first", join_kb())

        if data.startswith("redeem_"):
            amount = int(data.split("_")[1])
            if users[uid]["points"] < amount:
                tg_request("answerCallbackQuery", {
                    "callback_query_id": cq["id"],
                    "text": f"❌ Not enough points\nYour points: {users[uid]['points']}",
                    "show_alert": True
                })
                return jsonify(ok=True)

            users[uid]["redeem_pending"] = amount
            save_json(USERS_FILE, users)
            send_message(chat_id, "💰 Enter your UPI ID:")

        tg_request("answerCallbackQuery", {"callback_query_id": cq["id"]})

    # ===== MESSAGE =====
    if "message" in update:
        msg = update["message"]
        uid = str(msg["chat"]["id"])
        text = msg.get("text", "")

        users = load_json(USERS_FILE)
        redeems = load_json(REDEEM_FILE)

        if text.startswith("/start"):
            parts = text.split()
            if len(parts) > 1:
                handle_referral(uid, parts[1])
            send_message(uid, "Join channel & verify", join_kb())

        elif text == "🏧 Redeem":
            send_message(uid, f"🎁 YOUR POINTS - ({users[uid]['points']})", redeem_kb())

        elif "@" in text and users[uid].get("redeem_pending"):
            amt = users[uid]["redeem_pending"]
            users[uid]["points"] -= amt
            users[uid]["redeem_pending"] = False
            save_json(USERS_FILE, users)

            rid = str(len(redeems) + 1)
            redeems[rid] = {
                "user": uid,
                "upi": text,
                "amount": amt,
                "time": str(datetime.utcnow())
            }
            save_json(REDEEM_FILE, redeems)

            append_log(
                f"{datetime.utcnow()} REDEEM | USER:{uid} | UPI:{text} | POINTS:{amt}"
            )

            send_message(
                uid,
                "✅ Your points redeemed successfully\n"
                "💸 Payment received within 24 hours\n\n"
                f"🎁 Your current points - ({users[uid]['points']})"
            )

    return jsonify(ok=True)

@app.route("/")
def home():
    return "Bot running"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))

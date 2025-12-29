# app.py
import os, json, random, string, threading
from datetime import datetime
from flask import Flask, request, jsonify
import requests

app = Flask(__name__)

# ===== CONFIG =====
BOT_TOKEN = os.environ.get("TELEGRAM_TOKEN", "").strip()
API_BASE = f"https://api.telegram.org/bot{BOT_TOKEN}"

CHANNEL_USERNAME = os.environ.get("CHANNEL_USERNAME", "@earning_don_00")
CHANNEL_LINK = "https://t.me/earning_don_00"
SCRATCH_LINK = "https://scratchcard.page.gd"

BOT_USERNAME = "YOUR_BOT_USERNAME"   # 🔴 CHANGE THIS

USERS_FILE = "users.json"
LOG_FILE = "logs.txt"
_file_lock = threading.Lock()

pending_redeem = {}

# ===== TELEGRAM HELPERS =====
def tg_request(method, payload):
    return requests.post(f"{API_BASE}/{method}", json=payload, timeout=20).json()

def send_message(chat_id, text, reply_markup=None):
    data = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    if reply_markup:
        data["reply_markup"] = reply_markup
    tg_request("sendMessage", data)

def answer_callback_query(cid, text=""):
    tg_request("answerCallbackQuery", {"callback_query_id": cid, "text": text})

def get_member_status(uid):
    r = requests.get(
        f"{API_BASE}/getChatMember",
        params={"chat_id": CHANNEL_USERNAME, "user_id": uid},
        timeout=20
    ).json()
    return r.get("ok") and r["result"]["status"] in ("member","administrator","creator")

# ===== STORAGE =====
def load_users():
    if not os.path.exists(USERS_FILE):
        return {}
    with open(USERS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_users(data):
    with open(USERS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

# ===== REFERRAL (NO POINTS YET) =====
def handle_referral(new_uid, ref_uid):
    users = load_users()
    new_uid, ref_uid = str(new_uid), str(ref_uid)

    if new_uid == ref_uid:
        return
    if new_uid in users:
        return
    if ref_uid not in users:
        return

    users[new_uid] = {
        "username": "",
        "code": None,
        "points": 0,
        "referred_by": ref_uid,
        "referral_paid": False
    }
    save_users(users)

def referral_link(uid):
    return f"https://t.me/{BOT_USERNAME}?start={uid}"

# ===== SCRATCH CODE =====
def get_or_create_code(uid, username):
    users = load_users()
    uid = str(uid)

    if uid not in users:
        users[uid] = {
            "username": username,
            "points": 0,
            "referred_by": None,
            "referral_paid": True
        }

    if users[uid].get("code"):
        return users[uid]["code"]

    code = "".join(random.choices(string.digits, k=8))
    users[uid]["code"] = code
    save_users(users)

    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(f"{datetime.utcnow()} SCRATCH {username} {code}\n")

    return code

# ===== UI =====
def join_kb():
    return {
        "inline_keyboard": [
            [{"text": "Join Channel", "url": CHANNEL_LINK}],
            [{"text": "✅ Verify", "callback_data": "verify"}]
        ]
    }

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

    # CALLBACK
    if "callback_query" in update:
        cq = update["callback_query"]
        uid = str(cq["from"]["id"])
        chat_id = cq["message"]["chat"]["id"]
        data = cq["data"]

        # VERIFY
        if data == "verify":
            if get_member_status(uid):
                code = get_or_create_code(uid, cq["from"].get("username",""))
                send_message(chat_id,
                    f"🎉 Scratch Card Code:\n<code>{code}</code>",
                    {"inline_keyboard":[[{"text":"🎟 Open Scratch","url":SCRATCH_LINK}]]}
                )

                # 🔐 REAL REFERRAL PAYOUT
                users = load_users()
                ref = users[uid].get("referred_by")
                if ref and not users[uid]["referral_paid"] and ref in users:
                    users[ref]["points"] = users[ref].get("points",0) + 2
                    users[uid]["referral_paid"] = True
                    save_users(users)

                    send_message(ref,
                        f"🎉 Your refer completed\nYour points - ({users[ref]['points']})"
                    )
            else:
                send_message(chat_id, "❌ Join channel first", join_kb())

        # REDEEM SELECT
        elif data.startswith("redeem_"):
            need = int(data.split("_")[1])
            users = load_users()
            if users.get(uid,{}).get("points",0) < need:
                answer_callback_query(cq["id"], "Not enough points ❌")
            else:
                pending_redeem[uid] = need
                send_message(chat_id, "💳 Enter your UPI ID:")

        return jsonify(ok=True)

    # MESSAGE
    if "message" in update:
        msg = update["message"]
        uid = str(msg["chat"]["id"])
        text = msg.get("text","")

        # UPI INPUT
        if uid in pending_redeem:
            amount = pending_redeem.pop(uid)
            users = load_users()
            users[uid]["points"] -= amount
            if users[uid]["points"] < 0:
                users[uid]["points"] = 0
            save_users(users)

            with open(LOG_FILE,"a",encoding="utf-8") as f:
                f.write(f"{datetime.utcnow()} REDEEM {uid} {amount} {text}\n")

            send_message(uid,
                "✅ Your redeem successfully\n"
                "💰 Payment received on your UPI within 24 hours"
            )
            return jsonify(ok=True)

        # START
        if text.startswith("/start"):
            parts = text.split()
            if len(parts) > 1:
                handle_referral(uid, parts[1])
            send_message(uid, "Join channel & verify", join_kb())

        elif text == "/refer":
            users = load_users()
            pts = users.get(uid,{}).get("points",0)
            send_message(uid,
                "👥 <b>Refer & Earn</b>\n\n"
                "1 Refer = 2 Points\n"
                "1 Point = ₹1\n\n"
                f"🔗 {referral_link(uid)}\n\n"
                f"🎁 Your points - ({pts})"
            )

        elif text == "/points":
            pts = load_users().get(uid,{}).get("points",0)
            send_message(uid, f"🎁 Your Points - ({pts})")

        elif text == "/redeem":
            pts = load_users().get(uid,{}).get("points",0)
            send_message(uid, f"🎁 Your Points - ({pts})", redeem_kb())

    return jsonify(ok=True)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT",8000)))

# app.py
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

BOT_USERNAME = "Scratch_card_00_bot"   # ❌ no @
ADMIN_ID = 7336276055

USERS_FILE = "users.json"
LOG_FILE = "logs.txt"
REDEEM_FILE = "redeems.json"

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

def get_safe_username(user):
    if user.get("username"):
        return "@" + user["username"]
    return f"{user.get('first_name','User')}_{user.get('id')}"

# ===== STORAGE =====
def load_json(path):
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

# ===== REFERRAL =====
def handle_referral(new_uid, ref_uid):
    users = load_json(USERS_FILE)
    new_uid, ref_uid = str(new_uid), str(ref_uid)

    if new_uid == ref_uid or new_uid in users or ref_uid not in users:
        return

    users[new_uid] = {
        "username": "",
        "code": None,
        "points": 0,
        "referred_by": ref_uid,
        "referral_paid": False
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
            "referred_by": None,
            "referral_paid": True
        }
    else:
        users[uid]["username"] = username

    if users[uid].get("code"):
        return users[uid]["code"]

    code = "".join(random.choices(string.digits, k=8))
    users[uid]["code"] = code
    save_json(USERS_FILE, users)

    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(f"{datetime.utcnow()} SCRATCH USER:{username} CODE:{code}\n")

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

def main_menu(is_admin=False):
    kb = [
        ["🎁 Refer & Earn", "💰 My Points"],
        ["🏧 Redeem"]
    ]
    if is_admin:
        kb.append(["🛠 Admin Dashboard"])
    return {"keyboard": kb, "resize_keyboard": True}

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

        if data == "verify":
            if get_member_status(uid):
                safe_username = get_safe_username(cq["from"])
                code = get_or_create_code(uid, safe_username)

                send_message(
                    chat_id,
                    f"🎉 congratulations you win a scratch card 
                    Scratch Card Code:\n<code>{code}</code>",
                    {"inline_keyboard":[[{"text":"🎟 Open Scratch","url":SCRATCH_LINK}]]}
                )
                send_message(
                    chat_id,
                    "👇 Choose an option",
                    reply_markup=main_menu(is_admin=int(uid)==ADMIN_ID)
                )

                users = load_json(USERS_FILE)
                ref = users[uid].get("referred_by")
                if ref and not users[uid]["referral_paid"] and ref in users:
                    users[ref]["points"] += 2
                    users[uid]["referral_paid"] = True
                    save_json(USERS_FILE, users)
                    send_message(ref, f"🎉 Your refer completed\nYour points - ({users[ref]['points']})")
            else:
                send_message(chat_id, "❌ Join channel first", join_kb())

        elif data.startswith("redeem_"):
            need = int(data.split("_")[1])
            users = load_json(USERS_FILE)
            if users.get(uid,{}).get("points",0) < need:
                answer_callback_query(cq["id"], "Not enough points ❌")
            else:
                pending_redeem[uid] = need
                send_message(chat_id, "💳 Enter your UPI ID:")

        elif data.startswith("admin_") and int(uid) == ADMIN_ID:
            _, action, rid = data.split("_")
            redeems = load_json(REDEEM_FILE)
            r = redeems.get(rid)
            if not r:
                return jsonify(ok=True)

            r["status"] = "paid" if action=="paid" else "rejected"
            save_json(REDEEM_FILE, redeems)

            send_message(
                r["user_id"],
                "✅ Payment sent" if action=="paid" else "❌ Redeem rejected"
            )

            with open(LOG_FILE,"a",encoding="utf-8") as f:
                f.write(
                    f"{datetime.utcnow()} ADMIN_{r['status']} "
                    f"USER:{r['username']} AMOUNT:{r['amount']} UPI:{r['upi']}\n"
                )

        return jsonify(ok=True)

    # MESSAGE
    if "message" in update:
        msg = update["message"]
        uid = str(msg["chat"]["id"])
        text = msg.get("text","")

        # UPI INPUT
        if uid in pending_redeem:
            amount = pending_redeem.pop(uid)
            users = load_json(USERS_FILE)
            users[uid]["points"] -= amount
            save_json(USERS_FILE, users)

            redeems = load_json(REDEEM_FILE)
            rid = str(int(datetime.utcnow().timestamp()))
            redeems[rid] = {
                "user_id": uid,
                "username": users[uid]["username"],
                "amount": amount,
                "upi": text,
                "status": "pending"
            }
            save_json(REDEEM_FILE, redeems)

            with open(LOG_FILE,"a",encoding="utf-8") as f:
                f.write(
                    f"{datetime.utcnow()} REDEEM USER:{users[uid]['username']} "
                    f"POINTS:{amount} UPI:{text}\n"
                )

            send_message(uid, "✅ Redeem request submitted\nPayment within 24 hours")
            return jsonify(ok=True)

        # ADMIN COMMAND ALWAYS WORK
        if text == "/admin" and int(uid) == ADMIN_ID:
            redeems = load_json(REDEEM_FILE)
            pending = {k:v for k,v in redeems.items() if v["status"]=="pending"}

            if not pending:
                send_message(uid, "✅ No pending redeems")
                return jsonify(ok=True)

            for rid, r in pending.items():
                kb = {"inline_keyboard":[[
                    {"text":"✅ Paid","callback_data":f"admin_paid_{rid}"},
                    {"text":"❌ Reject","callback_data":f"admin_reject_{rid}"}
                ]]}
                send_message(uid,
                    f"👤 {r['username']}\n💰 ₹{r['amount']}\n💳 {r['upi']}",
                    kb
                )
            return jsonify(ok=True)

        # START
        if text.startswith("/start"):
            parts = text.split()
            if len(parts) > 1:
                handle_referral(uid, parts[1])
            send_message(uid, "Join channel & verify", join_kb())

        elif text in ["🎁 Refer & Earn", "/refer"]:
            users = load_json(USERS_FILE)
            pts = users.get(uid,{}).get("points",0)
            send_message(uid,
                "👥 <b>Refer & Earn</b>\n\n"
                "1 Refer = 2 Points\n"
                "1 Point = ₹1\n\n"
                f"{referral_link(uid)}\n\n"
                f"🎁 Your Points - ({pts})"
            )

        elif text in ["💰 My Points", "/points"]:
            pts = load_json(USERS_FILE).get(uid,{}).get("points",0)
            send_message(uid, f"🎁 Your Points - ({pts})")

        elif text in ["🏧 Redeem", "/redeem"]:
            pts = load_json(USERS_FILE).get(uid,{}).get("points",0)
            send_message(uid, f"🎁 Your Points - ({pts})", redeem_kb())

    return jsonify(ok=True)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT",8000)))

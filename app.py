import os, json, random, string, base64
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

# ===== LOGGING =====

def append_log(text):
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(text + "\n")
    except:
        pass

# ===== TELEGRAM =====

def tg_request(method, payload):
    return requests.post(f"{API_BASE}/{method}", json=payload).json()

def send_message(chat_id, text, reply_markup=None):
    data = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    if reply_markup:
        data["reply_markup"] = reply_markup
    tg_request("sendMessage", data)

def answer_callback_query(cid):
    tg_request("answerCallbackQuery", {"callback_query_id": cid})

def get_member_status(uid):
    r = requests.get(
        f"{API_BASE}/getChatMember",
        params={"chat_id": CHANNEL_USERNAME, "user_id": uid}
    ).json()
    return r.get("ok") and r["result"]["status"] in ("member", "administrator", "creator")

def get_safe_username(user):
    return "@" + user["username"] if user.get("username") else f"User_{user['id']}"

# ===== STORAGE =====

def load_json(path):
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return {}

def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

# ===== REFERRAL =====

def handle_referral(new_uid, ref_uid):
    users = load_json(USERS_FILE)
    new_uid, ref_uid = str(new_uid), str(ref_uid)

    if new_uid == ref_uid:
        return
    if new_uid in users:
        return
    if ref_uid not in users:
        return

    users[new_uid] = {
        "username": "",
        "points": 0,
        "code": None,
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

    return code

# ===== KEYBOARDS =====

def join_kb():
    return {
        "inline_keyboard": [
            [{"text": "Join Channel", "url": CHANNEL_LINK}],
            [{"text": "✅ Verify", "callback_data": "verify"}]
        ]
    }

def main_menu(is_admin=False):
    kb = [
        ["🎁 Refer & Earn", "💰 My Points"],
        ["🏧 Redeem"]
    ]
    if is_admin:
        kb.append(["📊 Admin Stats"])
    return {"keyboard": kb, "resize_keyboard": True}

# ===== WEBHOOK =====

@app.route("/webhook", methods=["POST"])
def webhook():
    update = request.json or {}

    # CALLBACK
    if "callback_query" in update:
        cq = update["callback_query"]
        uid = cq["from"]["id"]
        chat_id = cq["message"]["chat"]["id"]

        if cq["data"] == "verify":
            if get_member_status(uid):
                uname = get_safe_username(cq["from"])
                code = get_or_create_code(uid, uname)

                # 🔥 REFERRAL POINTS FIX
                users = load_json(USERS_FILE)
                uid_str = str(uid)

                if (
                    uid_str in users and
                    users[uid_str].get("referred_by") and
                    not users[uid_str].get("referral_paid")
                ):
                    ref_uid = users[uid_str]["referred_by"]
                    if ref_uid in users:
                        users[ref_uid]["points"] += 2
                        users[uid_str]["referral_paid"] = True
                        save_json(USERS_FILE, users)

                        append_log(
                            f"{datetime.utcnow()} REFERRAL +2 FROM {uid_str} TO {ref_uid}"
                        )

                send_message(
                    chat_id,
                    f"🎉 Scratch Card Won!\n\n<code>{code}</code>",
                    {"inline_keyboard": [[{"text": "🎟 Open Scratch", "url": SCRATCH_LINK}]]}
                )
                send_message(chat_id, "👇 Choose option", main_menu(uid == ADMIN_ID))
            else:
                send_message(chat_id, "❌ Join channel first", join_kb())

        answer_callback_query(cq["id"])

    # MESSAGE
    if "message" in update:
        msg = update["message"]
        uid = msg["chat"]["id"]
        text = msg.get("text", "")

        if text.startswith("/start"):
            parts = text.split()
            if len(parts) > 1:
                handle_referral(uid, parts[1])
            send_message(uid, "Join channel & verify", join_kb())

        elif text == "🎁 Refer & Earn":
            users = load_json(USERS_FILE)
            pts = users.get(str(uid), {}).get("points", 0)
            send_message(
                uid,
                f"👥 Refer & Earn\n\n1 Refer = 2 Points\n\n"
                f"🔗 Link:\n{referral_link(uid)}\n\n"
                f"🎁 Points: {pts}"
            )

        elif text == "💰 My Points":
            pts = load_json(USERS_FILE).get(str(uid), {}).get("points", 0)
            send_message(uid, f"🎁 Your Points: {pts}")

    return jsonify(ok=True)

@app.route("/")
def home():
    return "Bot running"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))

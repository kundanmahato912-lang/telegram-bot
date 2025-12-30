import os
import json
import random
import string
import base64
from datetime import datetime
from flask import Flask, request, jsonify
import requests

app = Flask(__name__)

# ================= CONFIG =================

BOT_TOKEN = os.environ.get("TELEGRAM_TOKEN", "").strip()
API_BASE = f"https://api.telegram.org/bot{BOT_TOKEN}"

CHANNEL_USERNAME = "@earning_don_00"
CHANNEL_LINK = "https://t.me/earning_don_00"
SCRATCH_LINK = "https://scratchcard.page.gd"

BOT_USERNAME = "Scratch_card_00_bot"
ADMIN_ID = int(os.environ.get("ADMIN_ID", "7336276055"))

USERS_FILE = "users.json"
REDEEM_FILE = "redeems.json"
LOG_FILE = "logs.txt"

# GitHub log config (Render env vars)
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
GITHUB_REPO = os.environ.get("GITHUB_REPO")          # username/repo
GITHUB_LOG_PATH = os.environ.get("GITHUB_LOG_PATH", "logs.txt")

# ================= FILE HELPERS =================

def ensure_files():
    for f in [USERS_FILE, REDEEM_FILE, LOG_FILE]:
        if not os.path.exists(f):
            with open(f, "w", encoding="utf-8") as fp:
                fp.write("{}" if f.endswith(".json") else "")

ensure_files()

def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return {}

def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

# ================= GITHUB LOG PUSH =================

def push_log_to_github(line):
    if not (GITHUB_TOKEN and GITHUB_REPO):
        return

    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{GITHUB_LOG_PATH}"
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    }

    sha = None
    old_content = ""

    r = requests.get(url, headers=headers)
    if r.status_code == 200:
        data = r.json()
        sha = data.get("sha")
        old_content = base64.b64decode(data.get("content", "")).decode()

    new_content = old_content + line + "\n"

    payload = {
        "message": "Update logs.txt",
        "content": base64.b64encode(new_content.encode()).decode()
    }
    if sha:
        payload["sha"] = sha

    requests.put(url, headers=headers, json=payload)

def log(text):
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(text + "\n")
    except:
        pass
    try:
        push_log_to_github(text)
    except:
        pass

# ================= TELEGRAM HELPERS =================

def tg(method, payload):
    return requests.post(f"{API_BASE}/{method}", json=payload).json()

def send(chat_id, text, reply_markup=None):
    data = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    if reply_markup:
        data["reply_markup"] = reply_markup
    tg("sendMessage", data)

def is_member(uid):
    r = requests.get(
        f"{API_BASE}/getChatMember",
        params={"chat_id": CHANNEL_USERNAME, "user_id": uid}
    ).json()
    return r.get("ok") and r["result"]["status"] in ("member", "administrator", "creator")

def uname(user):
    return "@" + user["username"] if user.get("username") else f"User_{user['id']}"

# ================= REFERRAL =================

def handle_referral(new_uid, ref_uid):
    users = load_json(USERS_FILE)
    new_uid = str(new_uid)
    ref_uid = str(ref_uid)

    if new_uid == ref_uid or new_uid in users or ref_uid not in users:
        return

    users[new_uid] = {
        "username": "",
        "points": 0,
        "code": None,
        "referred_by": ref_uid,
        "referral_paid": False,
        "redeem_pending": 0
    }
    save_json(USERS_FILE, users)

def ref_link(uid):
    return f"https://t.me/{BOT_USERNAME}?start={uid}"

# ================= SCRATCH =================

def scratch(uid, name):
    users = load_json(USERS_FILE)
    uid = str(uid)

    if uid not in users:
        users[uid] = {
            "username": name,
            "points": 0,
            "code": None,
            "referred_by": None,
            "referral_paid": False,
            "redeem_pending": 0
        }

    users[uid]["username"] = name

    if users[uid]["code"]:
        code = users[uid]["code"]
    else:
        code = "".join(random.choices(string.digits, k=8))
        users[uid]["code"] = code
        save_json(USERS_FILE, users)

    log(f"{datetime.utcnow()} SCRATCH | Name:{name} | Code:{code}")
    return code

# ================= KEYBOARDS =================

def join_kb():
    return {
        "inline_keyboard": [
            [{"text": "Join Channel", "url": CHANNEL_LINK}],
            [{"text": "✅ Verify", "callback_data": "verify"}]
        ]
    }

def menu(uid):
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

# ================= WEBHOOK =================

@app.route("/webhook", methods=["POST"])
def webhook():
    up = request.json or {}

    # ----- CALLBACK QUERY -----
    if "callback_query" in up:
        cq = up["callback_query"]
        uid = str(cq["from"]["id"])
        data = cq["data"]
        users = load_json(USERS_FILE)

        if data == "verify":
            if is_member(uid):
                name = uname(cq["from"])
                code = scratch(uid, name)

                if users.get(uid, {}).get("referred_by") and not users[uid]["referral_paid"]:
                    ref = users[uid]["referred_by"]
                    users[ref]["points"] += 2
                    users[uid]["referral_paid"] = True
                    save_json(USERS_FILE, users)

                send(
                    uid,
                    f"🎉 Congratulations!\n\nYour Scratch Code:\n<code>{code}</code>",
                    {"inline_keyboard": [[{"text": "🎟 Open Scratch", "url": SCRATCH_LINK}]]}
                )
                send(uid, "👇 Choose option", menu(uid))
            else:
                send(uid, "❌ Join channel first", join_kb())

        elif data.startswith("redeem_"):
            amt = int(data.split("_")[1])
            if users.get(uid, {}).get("points", 0) < amt:
                tg(
                    "answerCallbackQuery",
                    {
                        "callback_query_id": cq["id"],
                        "text": f"❌ Not enough points\nYour points: {users.get(uid, {}).get('points', 0)}",
                        "show_alert": True
                    }
                )
                return jsonify(ok=True)

            users[uid]["redeem_pending"] = amt
            save_json(USERS_FILE, users)
            send(uid, "💰 Enter your UPI ID:")

        tg("answerCallbackQuery", {"callback_query_id": cq["id"]})

    # ----- MESSAGE -----
    if "message" in up:
        m = up["message"]
        uid = str(m["chat"]["id"])
        txt = m.get("text", "")
        users = load_json(USERS_FILE)
        redeems = load_json(REDEEM_FILE)

        if txt.startswith("/start"):
            p = txt.split()
            if len(p) > 1:
                handle_referral(uid, p[1])
            send(uid, "Join channel & verify", join_kb())

        elif txt == "🎁 Refer & Earn":
            pts = users.get(uid, {}).get("points", 0)
            send(
                uid,
                "👥 <b>Refer & Earn</b>\n\n"
                "1 Refer = <b>2 Points</b>\n"
                "1 Point = <b>₹1</b>\n\n"
                "🔗 <b>Your Referral Link:</b>\n"
                f"{ref_link(uid)}\n\n"
                f"🎁 <b>Your Points:</b> {pts}"
            )

        elif txt == "💰 My Points":
            send(uid, f"🎁 <b>Your Points:</b> {users.get(uid, {}).get('points', 0)}")

        elif txt == "🏧 Redeem":
            send(uid, f"🎁 YOUR POINTS - ({users.get(uid, {}).get('points', 0)})", redeem_kb())

        elif "@" in txt and users.get(uid, {}).get("redeem_pending", 0) > 0:
            amt = users[uid]["redeem_pending"]
            users[uid]["points"] -= amt
            users[uid]["redeem_pending"] = 0
            save_json(USERS_FILE, users)

            name = uname(m["from"])
            log(f"{datetime.utcnow()} REDEEM | Name:{name} | UPI:{txt} | Points:{amt}")

            send(
                uid,
                "✅ Your points redeemed successfully\n"
                "💸 Payment will be sent within 24 hours\n\n"
                f"🎁 Your current points - ({users[uid]['points']})"
            )

        elif txt == "📊 Admin Stats" and int(uid) == ADMIN_ID:
            send(
                uid,
                "📊 <b>ADMIN STATS</b>\n\n"
                f"👥 Users: {len(users)}\n"
                f"🎁 Total Points: {sum(u.get('points', 0) for u in users.values())}\n"
                f"💸 Redeems: {len(redeems)}"
            )

    return jsonify(ok=True)

@app.route("/")
def home():
    return "Bot running"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))

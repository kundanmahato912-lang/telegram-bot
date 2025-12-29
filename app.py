# app.py
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

BOT_USERNAME = "Scratch_card_00_bot"   # ⚠️ NO @
ADMIN_ID = 7336276055

RESET_ALL_USERS = False

USERS_FILE = "users.json"
REDEEM_FILE = "redeems.json"
LOG_FILE = "logs.txt"

pending_redeem = {}

# ===== ENSURE FILES EXIST =====
def ensure_files():
    for f in [USERS_FILE, REDEEM_FILE, LOG_FILE]:
        if not os.path.exists(f):
            with open(f, "w", encoding="utf-8") as fp:
                fp.write("{}" if f.endswith(".json") else "")
ensure_files()
    
# ===== GITHUB LOGGING =====
def github_append_log(line):
    token = os.environ.get("GITHUB_TOKEN")
    repo = os.environ.get("GITHUB_REPO")
    branch = os.environ.get("GITHUB_BRANCH", "main")
    path = os.environ.get("GITHUB_LOG_PATH", "logs.txt")

    if not token or not repo:
        return

    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github+json"
    }

    url = f"https://api.github.com/repos/{repo}/contents/{path}"
    r = requests.get(url, headers=headers, params={"ref": branch})

    content = ""
    sha = None

    if r.status_code == 200:
        data = r.json()
        sha = data["sha"]
        content = base64.b64decode(data["content"]).decode("utf-8")
    elif r.status_code != 404:
        return

    content += line + "\n"
    encoded = base64.b64encode(content.encode()).decode()

    payload = {
        "message": f"append log {datetime.utcnow().isoformat()}",
        "content": encoded,
        "branch": branch
    }
    if sha:
        payload["sha"] = sha

    requests.put(url, headers=headers, json=payload)

# ===== SAFE LOG WRITE =====
def append_log(text):
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(text + "\n")
            f.flush()
            os.fsync(f.fileno())
    except Exception as e:
        print("LOCAL LOG ERROR:", e)

    try:
        github_append_log(text)
    except Exception as e:
        print("GITHUB LOG ERROR:", e)

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
    try:
        with open(path, "r", encoding="utf-8") as f:
            d = f.read().strip()
            return json.loads(d) if d else {}
    except Exception:
        return {}

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

    append_log(f"{datetime.utcnow()} SCRATCH USER:{username} CODE:{code}")
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
        kb.append(["📊 Admin Stats", "🛠 Admin Dashboard"])
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
                uname = get_safe_username(cq["from"])
                code = get_or_create_code(uid, uname)

                send_message(
                    chat_id,
                    f"🎉 Congratulations! You win a scratch card\n\n"
                    f"Scratch Card Code:\n<code>{code}</code>",
                    {"inline_keyboard":[[{"text":"🎟 Open Scratch","url":SCRATCH_LINK}]]}
                )
                send_message(
                    chat_id,
                    "👇 Choose an option",
                    reply_markup=main_menu(int(uid)==ADMIN_ID)
                )
            else:
                send_message(chat_id, "❌ Join channel first", join_kb())

        elif data.startswith("admin_") and int(uid) == ADMIN_ID:
            answer_callback_query(cq["id"], "Processing...")
            _, action, rid = data.split("_")
            redeems = load_json(REDEEM_FILE)
            if rid not in redeems:
                answer_callback_query(cq["id"], "Already done")
                return jsonify(ok=True)

            r = redeems[rid]
            r["status"] = "paid" if action=="paid" else "rejected"
            save_json(REDEEM_FILE, redeems)

            send_message(
                r["user_id"],
                "✅ Payment sent" if action=="paid" else "❌ Redeem rejected"
            )

            append_log(
                f"{datetime.utcnow()} ADMIN_{r['status']} "
                f"USER:{r['username']} AMOUNT:{r['amount']} UPI:{r['upi']}"
            )
            answer_callback_query(cq["id"], "Done ✅")

        return jsonify(ok=True)

    # MESSAGE
    if "message" in update:
        msg = update["message"]
        uid = str(msg["chat"]["id"])
        text = msg.get("text","")

        if text.startswith("/start"):
            parts = text.split()
            if len(parts) > 1:
                handle_referral(uid, parts[1])
            send_message(uid, "Join channel & verify", join_kb())

        elif text == "🎁 Refer & Earn":
            users = load_json(USERS_FILE)
            pts = users.get(uid, {}).get("points", 0)
            send_message(
                uid,
                "👥 <b>Refer & Earn</b>\n\n"
                "1 Refer = 2 Points\n"
                "1 Point = ₹1\n\n"
                f"🔗 Your Referral Link:\n{referral_link(uid)}\n\n"
                f"🎁 Your Points: {pts}"
            )

        elif text == "💰 My Points":
            pts = load_json(USERS_FILE).get(uid, {}).get("points", 0)
            send_message(uid, f"🎁 Your Points: {pts}")

        elif text == "🏧 Redeem":
            users = load_json(USERS_FILE)
            pts = users.get(uid, {}).get("points", 0)

            if pts < 10:
                send_message(uid, "❌ Minimum 10 points required to redeem")
            else:
                send_message(
                    uid,
                    f"🎁 Your Points: {pts}\n\nSelect redeem option 👇",
                    redeem_kb()
                )

        elif text in ["📊 Admin Stats", "/stats"] and int(uid) == ADMIN_ID:
            users = load_json(USERS_FILE)
            redeems = load_json(REDEEM_FILE)

            total_users = len(users)
            scratch_count = sum(1 for u in users.values() if u.get("code"))
            total_points = sum(u.get("points", 0) for u in users.values())
            total_referrals = sum(
                1 for u in users.values()
                if u.get("referred_by") and u.get("referral_paid")
            )

            pending = [r for r in redeems.values() if r.get("status") == "pending"]
            pending_count = len(pending)
            pending_amount = sum(r.get("amount", 0) for r in pending)

            send_message(
                uid,
                "📊 <b>ADMIN STATS</b>\n\n"
                f"👥 Total Users: {total_users}\n"
                f"🎟 Scratch Cards Generated: {scratch_count}\n"
                f"🔗 Successful Referrals: {total_referrals}\n"
                f"🎁 Total Points Given: {total_points}\n"
                f"⏳ Pending Redeems: {pending_count}\n"
                f"💰 Pending Amount: ₹{pending_amount}"
            )

    return jsonify(ok=True)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT",8000)))

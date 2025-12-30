import os
import random
import string
from datetime import datetime
from flask import Flask, request, jsonify
import requests
import psycopg2
import re

app = Flask(__name__)

# ================= CONFIG =================

BOT_TOKEN = os.environ.get("TELEGRAM_TOKEN", "").strip()
API_BASE = f"https://api.telegram.org/bot{BOT_TOKEN}"

CHANNEL_USERNAME = "@earning_don_00"
CHANNEL_LINK = "https://t.me/earning_don_00"
SCRATCH_LINK = "https://scratchcard.page.gd"

BOT_USERNAME = "Scratch_card_00_bot"
ADMIN_ID = int(os.environ.get("ADMIN_ID", "7336276055"))

DATABASE_URL = os.environ.get("DATABASE_URL")

UPI_REGEX = r"^[\w.\-]{2,256}@[a-zA-Z]{2,64}$"

# ================= DATABASE =================

conn = psycopg2.connect(DATABASE_URL)
conn.autocommit = True

def db():
    return conn.cursor()

def init_db():
    cur = db()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        user_id BIGINT PRIMARY KEY,
        username TEXT,
        points INTEGER DEFAULT 0,
        code TEXT,
        referred_by BIGINT,
        referral_paid BOOLEAN DEFAULT FALSE,
        redeem_pending INTEGER DEFAULT 0
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS redeems (
        id SERIAL PRIMARY KEY,
        user_id BIGINT,
        username TEXT,
        upi TEXT,
        points INTEGER,
        time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

init_db()

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

# ================= USERS =================

def get_user(uid, username=""):
    cur = db()
    cur.execute("SELECT * FROM users WHERE user_id=%s", (uid,))
    user = cur.fetchone()

    if not user:
        cur.execute(
            "INSERT INTO users (user_id, username) VALUES (%s,%s)",
            (uid, username)
        )
        cur.execute("SELECT * FROM users WHERE user_id=%s", (uid,))
        user = cur.fetchone()

    return user

def handle_referral(new_uid, ref_uid):
    if new_uid == ref_uid:
        return

    cur = db()

    cur.execute("SELECT user_id FROM users WHERE user_id=%s", (new_uid,))
    if cur.fetchone():
        return

    cur.execute("SELECT user_id FROM users WHERE user_id=%s", (ref_uid,))
    if not cur.fetchone():
        return

    cur.execute(
        "INSERT INTO users (user_id, referred_by) VALUES (%s,%s)",
        (new_uid, ref_uid)
    )

def pay_referral(uid):
    cur = db()
    cur.execute(
        "SELECT referred_by, referral_paid FROM users WHERE user_id=%s",
        (uid,)
    )
    row = cur.fetchone()

    if row and row[0] and not row[1]:
        cur.execute(
            "UPDATE users SET points = points + 2 WHERE user_id=%s",
            (row[0],)
        )
        cur.execute(
            "UPDATE users SET referral_paid=TRUE WHERE user_id=%s",
            (uid,)
        )

def ref_link(uid):
    return f"https://t.me/{BOT_USERNAME}?start={uid}"

# ================= SCRATCH =================

def scratch(uid, name):
    cur = db()
    cur.execute("SELECT code FROM users WHERE user_id=%s", (uid,))
    row = cur.fetchone()

    if row and row[0]:
        return row[0]

    code = "".join(random.choices(string.digits, k=8))
    cur.execute(
        "UPDATE users SET code=%s, username=%s WHERE user_id=%s",
        (code, name, uid)
    )
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

    # CALLBACK
    if "callback_query" in up:
        cq = up["callback_query"]
        uid = int(cq["from"]["id"])
        data = cq["data"]

        if data == "verify":
            if is_member(uid):
                name = uname(cq["from"])
                get_user(uid, name)
                code = scratch(uid, name)
                pay_referral(uid)

                send(
                    uid,
                    "🎉 <b>Congratulations!</b> You win a scratch card 🥳\n\n"
                    "━━━━━━━━━━━━━━━\n"
                    "🎟 <b>SCRATCH CARD CODE</b>\n\n"
                    f"<code>{code}</code>\n"
                    "━━━━━━━━━━━━━━━",
                    {
                        "inline_keyboard": [
                            [{"text": "🎟 Open Scratch", "url": SCRATCH_LINK}]
                        ]
                    }
                )
                send(uid, "👇 Choose option", menu(uid))
            else:
                send(uid, "❌ Join channel first", join_kb())

        elif data.startswith("redeem_"):
            amt = int(data.split("_")[1])
            cur = db()
            cur.execute("SELECT points FROM users WHERE user_id=%s", (uid,))
            pts = cur.fetchone()[0]

            if pts < amt:
                tg("answerCallbackQuery", {
                    "callback_query_id": cq["id"],
                    "text": f"❌ Not enough points\nYour points: {pts}",
                    "show_alert": True
                })
                return jsonify(ok=True)

            cur.execute(
                "UPDATE users SET redeem_pending=%s WHERE user_id=%s",
                (amt, uid)
            )
            send(uid, "💰 Enter your UPI ID:")

        tg("answerCallbackQuery", {"callback_query_id": cq["id"]})

    # MESSAGE
    if "message" in up:
        m = up["message"]
        uid = int(m["chat"]["id"])
        txt = m.get("text", "")

        if txt.startswith("/start"):
            p = txt.split()
            if len(p) > 1:
                handle_referral(uid, int(p[1]))
            send(uid, "Join channel & verify", join_kb())

        elif txt == "🎁 Refer & Earn":
            cur = db()
            cur.execute("SELECT points FROM users WHERE user_id=%s", (uid,))
            pts = cur.fetchone()[0]
            send(uid,
                f"👥 <b>Refer & Earn</b>\n\n"
                f"1 Refer = <b>2 Points</b>\n\n"
                f"1 Point = <b>₹1</b>\n\n"
                f"🔗 Link:\n{ref_link(uid)}\n\n"
                f"🎁 Points: {pts}"
            )

        elif txt == "💰 My Points":
            cur = db()
            cur.execute("SELECT points FROM users WHERE user_id=%s", (uid,))
            send(uid, f"🎁 Your Points: {cur.fetchone()[0]}")

        elif txt == "🏧 Redeem":
            cur = db()
            cur.execute("SELECT points FROM users WHERE user_id=%s", (uid,))
            send(uid, f"🎁 YOUR POINTS ({cur.fetchone()[0]})", redeem_kb())

        elif re.match(UPI_REGEX, txt):
            cur = db()
            cur.execute(
                "SELECT points, redeem_pending, username FROM users WHERE user_id=%s",
                (uid,)
            )
            pts, amt, username = cur.fetchone()

            if amt > 0 and pts >= amt:
                cur.execute(
                    "UPDATE users SET points=points-%s, redeem_pending=0 WHERE user_id=%s",
                    (amt, uid)
                )
                cur.execute(
                    "INSERT INTO redeems (user_id, username, upi, points) VALUES (%s,%s,%s,%s)",
                    (uid, username, txt, amt)
                )
                send(uid, f"✅ Redeem successful\n🎁 Remaining points: {pts-amt}")

        elif txt == "📊 Admin Stats" and uid == ADMIN_ID:
            cur = db()
            cur.execute("SELECT COUNT(*) FROM users")
            users = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM redeems")
            redeems = cur.fetchone()[0]

            send(uid,
                f"📊 <b>ADMIN STATS</b>\n\n"
                f"👥 Users: {users}\n"
                f"💸 Redeems: {redeems}"
            )

    return jsonify(ok=True)

@app.route("/")
def home():
    return "Bot running"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))

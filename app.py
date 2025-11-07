# app.py
import os
import json
import random
import string
import threading
import base64
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

# ====== GitHub settings (for committing logs.txt) ======
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "").strip()
GITHUB_REPO = os.environ.get("GITHUB_REPO", "").strip()          # e.g. "kundanmahto912-lang/telegram-bot"
GITHUB_BRANCH = os.environ.get("GITHUB_BRANCH", "main").strip()   # e.g. "main"
GITHUB_FILE_PATH = os.environ.get("GITHUB_FILE_PATH", "logs.txt").strip()


# ============== TELEGRAM HELPERS ==============
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


# ============== LOCAL STORAGE HELPERS ==============
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


# ============== GITHUB LOG APPEND ==============
def github_append_line(line: str):
    """
    logs.txt में नई line GitHub repo पर commit करता है।
    requirements:
      - GITHUB_TOKEN (repo scope)
      - GITHUB_REPO  -> "user/repo"
      - GITHUB_BRANCH -> "main"
      - GITHUB_FILE_PATH -> "logs.txt"
    """
    if not (GITHUB_TOKEN and GITHUB_REPO and GITHUB_FILE_PATH):
        # GitHub config नहीं है, तो skip कर दें
        return False, "missing_github_env"

    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json"
    }
    # 1) पहले current file fetch करें (sha और content के लिए)
    get_url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{GITHUB_FILE_PATH}"
    params = {"ref": GITHUB_BRANCH}
    r = requests.get(get_url, headers=headers, params=params, timeout=20)

    content_str = ""
    sha = None
    if r.status_code == 200:
        data = r.json()
        sha = data.get("sha")
        encoded = data.get("content", "")
        if encoded:
            try:
                content_bytes = base64.b64decode(encoded)
                content_str = content_bytes.decode("utf-8")
            except Exception:
                content_str = ""
    elif r.status_code == 404:
        # फ़ाइल अभी repo में नहीं है; हम create करेंगे
        content_str = ""
        sha = None
    else:
        return False, f"get_failed:{r.status_code}:{r.text}"

    # 2) नई line append करें
    new_content = content_str + ("" if content_str.endswith("\n") or content_str == "" else "\n") + line
    new_b64 = base64.b64encode(new_content.encode("utf-8")).decode("utf-8")

    # 3) PUT करके commit करें
    put_url = get_url
    payload = {
        "message": f"chore(logs): append entry {datetime.utcnow().isoformat()}Z",
        "content": new_b64,
        "branch": GITHUB_BRANCH,
    }
    if sha:
        payload["sha"] = sha

    pr = requests.put(put_url, headers=headers, json=payload, timeout=20)
    if pr.status_code in (200, 201):
        return True, "ok"
    else:
        return False, f"put_failed:{pr.status_code}:{pr.text}"


def get_or_create_code(user_id, username):
    """हर यूज़र को सिर्फ एक बार 8-digit कोड देता है + logs.txt (local + GitHub) में लिखता है"""
    users = load_users()
    key = str(user_id)
    if key in users and "code" in users[key]:
        return users[key]["code"]

    code = "".join(random.choices(string.digits, k=8))
    users[key] = {"code": code, "username": username or ""}
    save_users(users)

    # ---------- Local log (Render FS) ----------
    line = f"{datetime.utcnow().isoformat()}Z\t{username or user_id}\t{code}\n"
    with _file_lock:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line)

    # ---------- GitHub log (commit) ----------
    try:
        ok, info = github_append_line(line.strip("\n"))
        if not ok:
            # चाहें तो owner chat पर error भेज सकते हैं; अभी चुपचाप fail- safe
            pass
    except Exception:
        pass

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


# ============== ROUTES ==============
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

from flask import Flask, request
import requests
import random
import string
import logging

app = Flask(__name__)

# Telegram Bot Token and Channel Info
import os

BOT_TOKEN = os.getenv('BOT_TOKEN')
CHANNEL_USERNAME = os.getenv('CHANNEL_USERNAME')
SCRATCH_LINK = 'https://scratchcard.page.gd'

# Logging setup
logging.basicConfig(filename='logs.txt', level=logging.INFO)

# Telegram API URL
API_URL = f'https://api.telegram.org/bot{BOT_TOKEN}'

# Generate 8-digit mono-letter code
def generate_code():
    return ''.join(random.choices(string.ascii_uppercase, k=8))

# Check if user is a member of the channel
def is_user_in_channel(user_id):
    url = f'{API_URL}/getChatMember'
    params = {
        'chat_id': f'@earning_don_00',
        'user_id': user_id
    }
    response = requests.get(url, params=params).json()
    status = response.get('result', {}).get('status', '')
    return status in ['member', 'administrator', 'creator']

# Send message with buttons
def send_verification_prompt(chat_id):
    text = "Hello! Join the Telegram channel and verify."
    reply_markup = {
        "inline_keyboard": [
            [{"text": "Join Channel", "url": f"https://t.me/earning_don_00"}],
            [{"text": "Verify", "callback_data": "verify"}]
        ]
    }
    requests.post(f"{API_URL}/sendMessage", json={
        "chat_id": chat_id,
        "text": text,
        "reply_markup": reply_markup
    })

# Handle incoming updates
@app.route(f'/{BOT_TOKEN}', methods=['POST'])
def webhook():
    data = request.get_json()

    if 'message' in data:
        chat_id = data['message']['chat']['id']
        send_verification_prompt(chat_id)

    elif 'callback_query' in data:
        query = data['callback_query']
        user_id = query['from']['id']
        username = query['from'].get('username', 'unknown')
        chat_id = query['message']['chat']['id']
        message_id = query['message']['message_id']

        if query['data'] == 'verify':
            if is_user_in_channel(user_id):
                code = generate_code()
                text = f"🎉 Congratulations! You win a scratch card.\nYour code: `{code}`"
                reply_markup = {
                    "inline_keyboard": [
                        [{"text": "Go to Scratch Card", "url": SCRATCH_LINK}]
                    ]
                }
                requests.post(f"{API_URL}/sendMessage", json={
                    "chat_id": chat_id,
                    "text": text,
                    "reply_markup": reply_markup,
                    "parse_mode": "Markdown"
                })
                logging.info(f"{username} - {code}")
            else:
                requests.post(f"{API_URL}/sendMessage", json={
                    "chat_id": chat_id,
                    "text": "❌ Try again. Please join the channel first."
                })
                send_verification_prompt(chat_id)

    return {"ok": True}

# Home route
@app.route('/')
def home():
    return "Telegram bot is running."

if __name__ == '__main__':
    app.run(debug=True)

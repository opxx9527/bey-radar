from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage

import os
import requests
from bs4 import BeautifulSoup

app = Flask(__name__)

# ===== LINE 設定 =====
LINE_CHANNEL_SECRET = os.environ.get("LINE_CHANNEL_SECRET")
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# ===== 你的固定測試 ID =====
USER_ID = "Ud09e90892377bf2b5bef3eada8d22b5e"


# ========================
# 基本首頁
# ========================
@app.route("/", methods=["GET"])
def home():
    return "Bey Radar is running 🌀"

@app.route("/crawl_test", methods=["GET"])
def crawl_test():

    try:
        url = "https://www.threads.net/"
        headers = {
            "User-Agent": "Mozilla/5.0"
        }

        res = requests.get(url, headers=headers, timeout=10)

        soup = BeautifulSoup(res.text, "html.parser")
        text = soup.get_text()

        preview = text[:800]

        line_bot_api.push_message(
            USER_ID,
            TextSendMessage(text="🧪 Threads 測試抓取成功：\n\n" + preview)
        )

        return "crawl ok"

    except Exception as e:
        return f"crawl error: {str(e)}", 500

# ========================
# LINE webhook
# ========================
@app.route("/webhook", methods=["POST"])
def webhook():
    signature = request.headers.get("X-Line-Signature")
    body = request.get_data(as_text=True)

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)

    return "OK"


@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    text = event.message.text

    if "哈囉" in text:
        reply = "🌀 我是陀螺雷達 Bey Radar"
    else:
        reply = f"收到：{text}"

    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text=reply)
    )


# ========================
# 🔔 LINE 推播測試
# ========================
@app.route("/test_push", methods=["GET"])
def test_push():

    try:
        line_bot_api.push_message(
            USER_ID,
            TextSendMessage(text="🛰️ 推播測試成功！")
        )
        return "push sent"

    except Exception as e:
        return f"push error: {str(e)}", 500


# ========================
# 🕷️ Threads 爬蟲測試
# ========================
@app.route("/crawl_test", methods=["GET"])
def crawl_test():

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()

            page.goto("https://www.threads.net/", timeout=60000)

            content = page.content()

            browser.close()

        # 只取前面避免 LINE 爆字數
        preview = content[:800]

        line_bot_api.push_message(
            USER_ID,
            TextSendMessage(text="🕷️ Threads 爬蟲完成：\n\n" + preview)
        )

        return "crawl sent"

    except Exception as e:
        return f"crawl error: {str(e)}", 500


# ========================
# 啟動
# ========================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)

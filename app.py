from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
import os

app = Flask(__name__)

LINE_CHANNEL_SECRET = os.environ.get("LINE_CHANNEL_SECRET")
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# 👉 先暫存 user_id（之後才可以 push）
USER_ID = None


@app.route("/", methods=["GET"])
def home():
    return "Bey Radar is running 🌀"


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
    global USER_ID

    print("========== DEBUG ==========")
    print("TYPE =", event.source.type)
    print("SOURCE =", event.source)
    print("USER_ID =", event.source.user_id)
    print("===========================")

    # 👉 記住 user_id
    USER_ID = event.source.user_id

    text = event.message.text

    if "哈囉" in text:
        reply = "🌀 我是陀螺雷達 Bey Radar"
    else:
        reply = f"收到：{text}"

    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text=reply)
    )


from playwright.sync_api import sync_playwright


@app.route("/test_push", methods=["GET"])
def test_push():
    user_id = "Ud09e90892377bf2b5bef3eada8d22b5e"

    # 👉 LINE 推播測試
    line_bot_api.push_message(
        user_id,
        TextSendMessage(text="🛰️ 推播測試成功！")
    )

    # 👉 Threads 測試抓取
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        page.goto("https://www.threads.net/")

        content = page.content()

        browser.close()

    print("THREADS LENGTH =", len(content))

    return "push sent + crawl done"


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)

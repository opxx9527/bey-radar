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


@app.route("/test_push", methods=["GET"])
def test_push():
    if not USER_ID:
        return "還沒有 user_id（請先在 LINE 傳訊息）", 400

    line_bot_api.push_message(
        USER_ID,
        TextSendMessage(text="🛰️ 陀螺雷達推播測試成功！")
    )

    return "push sent"


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)

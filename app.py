from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
import os

app = Flask(__name__)

LINE_CHANNEL_SECRET = os.environ.get("LINE_CHANNEL_SECRET")
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")

print("SECRET =", LINE_CHANNEL_SECRET)
print("TOKEN =", LINE_CHANNEL_ACCESS_TOKEN)

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# 👉 暫存 user_id（不用手動填）
USER_ID = None


@app.route("/", methods=["GET"])
def home():
    return "Bey Radar is running 🌀"


@app.route("/test_push", methods=["GET"])
def test_push():
    try:
        if not USER_ID:
            return "❌ USER_ID 還沒被設定（請先傳訊息給 bot）", 400

        line_bot_api.push_message(
            USER_ID,
            TextSendMessage(text="🛰️ 陀螺雷達推播測試成功！")
        )

        return "push sent"

    except Exception as e:
        print("ERROR =", str(e))
        return f"error: {str(e)}", 500


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

    # 👉 自動記錄 user_id（重點修正）
    if event.source.type == "user":
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


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)

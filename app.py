from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
import os

app = Flask(__name__)

LINE_CHANNEL_SECRET = os.environ.get("ad156b686fc844ba975cd2f793d8884b")
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get("pBpT8At/37VTQOjOhTy4TxddOCBhIm0fVxZSvV4jicpZnHolqFPefFp5e1Z5Qlcft27nWkHT7VRkPVrzdEaLH7EnndlHqnbux9A5KPvCKOjF8a/kLNjTChvgj1YTVDrcpHt5gvTH7jzq9pWVneaLpwdB04t89/1O/w1cDnyilFU=")

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

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

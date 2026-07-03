from apscheduler.schedulers.background import BackgroundScheduler
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage

import os
import datetime
import feedparser

app = Flask(__name__)

# ===== LINE 設定 =====
LINE_CHANNEL_SECRET = os.environ.get("LINE_CHANNEL_SECRET")
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# ===== 固定測試 USER_ID =====
USER_ID = "Ud09e90892377bf2b5bef3eada8d22b5e"


# =========================
# 🏆 抓比賽新聞（RSS穩定版）
# =========================
def fetch_beyblade_news():
    url = "https://news.google.com/rss/search?q=beyblade+tournament&hl=en-US&gl=US&ceid=US:en"

    feed = feedparser.parse(url)

    news_list = []

    for entry in feed.entries[:5]:
        news_list.append(entry.title)

    if not news_list:
        return "目前沒有比賽新聞"

    return "\n".join(news_list)


# =========================
# 🕒 排程任務
# =========================
def job():
    print("🕒 排程執行：", datetime.datetime.now())

    try:
        news = fetch_beyblade_news()

        line_bot_api.push_message(
            USER_ID,
            TextSendMessage(text="🏆 Beyblade 最新比賽新聞：\n\n" + news)
        )

    except Exception as e:
        print("排程錯誤:", str(e))


# =========================
# 首頁
# =========================
@app.route("/", methods=["GET"])
def home():
    return "Bey Radar is running 🌀"


# =========================
# 測試推播
# =========================
@app.route("/test_push", methods=["GET"])
def test_push():
    try:
        line_bot_api.push_message(
            USER_ID,
            TextSendMessage(text="🛰️ 推播測試成功！")
        )
        return "push sent"
    except Exception as e:
        return f"error: {str(e)}", 500


# =========================
# 手動測試新聞
# =========================
@app.route("/test_news", methods=["GET"])
def test_news():
    return fetch_beyblade_news()


# =========================
# LINE webhook
# =========================
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

    if "新聞" in text:
        reply = fetch_beyblade_news()
    else:
        reply = f"收到：{text}"

    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text=reply)
    )


# =========================
# 🚀 排程（每5分鐘）
# =========================
scheduler = BackgroundScheduler()
scheduler.add_job(job, "interval", minutes=5)
scheduler.start()


# =========================
# 啟動
# =========================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)

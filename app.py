from apscheduler.schedulers.background import BackgroundScheduler
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage

import os
import datetime
import feedparser
import re

app = Flask(__name__)

# ========================
# LINE 設定
# ========================
LINE_CHANNEL_SECRET = os.environ.get("LINE_CHANNEL_SECRET")
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# 固定測試用 USER_ID
USER_ID = "Ud09e90892377bf2b5bef3eada8d22b5e"


# ========================
# 🧠 判斷是否已過期（簡化版）
# ========================
def is_expired(text):
    keywords = ["已截止", "額滿", "結束", "closed", "end"]
    return any(k in text.lower() for k in keywords)


# ========================
# 🏆 台南比賽雷達（核心）
# ========================
def fetch_tainan_events():
    url = "https://news.google.com/rss/search?q=台南+戰鬥陀螺+比賽&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"

    feed = feedparser.parse(url)

    events = []

    for entry in feed.entries[:10]:
        title = entry.title
        link = entry.link

        # 必須包含關鍵字
        if "比賽" not in title and "戰鬥陀螺" not in title:
            continue

        # 過濾已截止
        if is_expired(title):
            continue

        # 嘗試抓基本資訊（簡化版）
        date_match = re.search(r"\d{1,2}月\d{1,2}日|\d{4}", title)
        date = date_match.group() if date_match else "未提供"

        event_text = f"""🏆 {title}
📍 地點：台南（需點擊來源確認）
📅 時間：{date}
💰 費用：未提供
⏰ 報名：請確認是否仍開放

🔗 來源：
{link}
"""

        events.append(event_text)

    if not events:
        return "目前沒有台南可報名比賽"

    return "\n\n-----------------\n\n".join(events)


# ========================
# 🕒 排程推播（每 10 分鐘）
# ========================
def job():
    print("🕒 檢查台南比賽：", datetime.datetime.now())

    try:
        result = fetch_tainan_events()

        line_bot_api.push_message(
            USER_ID,
            TextSendMessage(text="🏆 台南戰鬥陀螺比賽雷達：\n\n" + result)
        )

    except Exception as e:
        print("排程錯誤:", str(e))


scheduler = BackgroundScheduler()
scheduler.add_job(job, "interval", minutes=10)
scheduler.start()


# ========================
# 首頁
# ========================
@app.route("/", methods=["GET"])
def home():
    return "Tainan Beyblade Radar is running 🌀"


# ========================
# 手動測試（台南比賽）
# ========================
@app.route("/test_tainan", methods=["GET"])
def test_tainan():
    return fetch_tainan_events()


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

    if "台南" in text:
        reply = fetch_tainan_events()

    elif "比賽" in text:
        reply = fetch_tainan_events()

    else:
        reply = f"收到：{text}"

    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text=reply)
    )


# ========================
# 測試推播
# ========================
@app.route("/test_push", methods=["GET"])
def test_push():
    try:
        line_bot_api.push_message(
            USER_ID,
            TextSendMessage(text="🛰️ 台南比賽雷達推播測試成功！")
        )
        return "push sent"
    except Exception as e:
        return f"error: {str(e)}", 500


# ========================
# 啟動
# ========================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)

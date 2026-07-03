from flask import Flask, request, abort
import os
import requests
from bs4 import BeautifulSoup
from apscheduler.schedulers.background import BackgroundScheduler

from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage

app = Flask(__name__)

# ======================
# LINE 設定
# ======================
LINE_CHANNEL_SECRET = os.environ.get("LINE_CHANNEL_SECRET")
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# ======================
# 防重複記錄
# ======================
seen_urls = set()


# ======================
# Google 搜尋
# ======================
def google_search(query):
    url = f"https://www.google.com/search?q={query}"
    headers = {"User-Agent": "Mozilla/5.0"}

    res = requests.get(url, headers=headers, timeout=10)
    soup = BeautifulSoup(res.text, "html.parser")

    results = []

    for item in soup.select("div.tF2Cxc"):
        title = item.select_one("h3")
        link = item.select_one("a")

        if title and link:
            results.append({
                "title": title.text,
                "url": link["href"]
            })

    return results[:5]


# ======================
# 過濾台南 + 戰鬥陀螺
# ======================
def is_relevant(text):
    keywords = ["台南", "Tainan", "戰鬥陀螺", "Beyblade", "ベイブレード"]
    return any(k.lower() in text.lower() for k in keywords)


# ======================
# 核心掃描任務
# ======================
def scan():
    global seen_urls

    print("🔍 scanning...")

    queries = [
        "戰鬥陀螺 台南 比賽",
        "Beyblade X Tainan tournament",
        "Beyblade 台南 活動"
    ]

    for q in queries:
        results = google_search(q)

        for r in results:
            title = r["title"]
            url = r["url"]

            if url in seen_urls:
                continue

            if not is_relevant(title):
                continue

            seen_urls.add(url)

            try:
                line_bot_api.push_message(
                    os.environ.get("USER_ID"),
                    TextSendMessage(
                        text=f"🏆 發現可能比賽\n\n{title}\n{url}"
                    )
                )
            except Exception as e:
                print("push error:", e)


# ======================
# LINE webhook
# ======================
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

    # 手動觸發掃描
    if "搜尋 台南" in text:
        scan()
        reply = "🔍 已開始掃描台南比賽"

    elif "列表" in text:
        reply = "目前系統已啟動 V2 雷達"

    else:
        reply = "指令：\n搜尋 台南\n列表"

    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text=reply)
    )


# ======================
# 排程（每10分鐘）
# ======================
scheduler = BackgroundScheduler()
scheduler.add_job(scan, "interval", minutes=10)
scheduler.start()


# ======================
# 首頁
# ======================
@app.route("/", methods=["GET"])
def home():
    return "Bey Radar V2 running 🛰️"


# ======================
# 啟動
# ======================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)

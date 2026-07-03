from flask import Flask, request, abort
import os
import requests
from bs4 import BeautifulSoup

from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage

app = Flask(__name__)

# ======================
# LINE 設定（Render 環境變數）
# ======================
LINE_CHANNEL_SECRET = os.environ.get("LINE_CHANNEL_SECRET")
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)


# ======================
# 首頁
# ======================
@app.route("/", methods=["GET"])
def home():
    return "Bey Radar V1 is running 🌀"


# ======================
# Google 簡單搜尋（不用 API）
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

    # ----------------------
    # 指令1：搜尋台南比賽
    # ----------------------
    if "搜尋 台南" in text:
        queries = [
            "戰鬥陀螺 台南 比賽",
            "Beyblade 台南 tournament",
            "Beyblade X 台南"
        ]

        all_results = []

        for q in queries:
            results = google_search(q)
            all_results.extend(results)

        if not all_results:
            reply = "目前沒有找到台南比賽資訊"
        else:
            reply = "🏆 找到可能比賽：\n\n"

            for r in all_results[:5]:
                reply += f"{r['title']}\n{r['url']}\n\n"

        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=reply)
        )
        return

    # ----------------------
    # 預設回覆
    # ----------------------
    reply = "指令：\n1️⃣ 搜尋 台南"

    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text=reply)
    )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)

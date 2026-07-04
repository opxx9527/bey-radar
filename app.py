from flask import Flask, request, abort
import os
import requests
import sqlite3

from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage

app = Flask(__name__)

# ======================
# 環境變數設定
# ======================
LINE_CHANNEL_SECRET = os.environ.get("LINE_CHANNEL_SECRET")
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")
GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY") # 新增：Google API 金鑰
GOOGLE_CX = os.environ.get("GOOGLE_CX")           # 新增：Google 搜尋引擎 ID

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# ======================
# 初始化 SQLite 資料庫
# ======================
def init_db():
    conn = sqlite3.connect('seen_urls.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS urls (url TEXT PRIMARY KEY)''')
    conn.commit()
    conn.close()

init_db()

# ======================
# Google Custom Search API
# ======================
def google_search_api(query):
    if not GOOGLE_API_KEY or not GOOGLE_CX:
        print("⚠️ 缺少 Google API 變數")
        return []
        
    url = f"https://www.googleapis.com/customsearch/v1?q={query}&key={GOOGLE_API_KEY}&cx={GOOGLE_CX}&num=5"
    
    try:
        res = requests.get(url, timeout=10).json()
        results = []
        for item in res.get("items", []):
            results.append({
                "title": item.get("title"),
                "url": item.get("link")
            })
        return results
    except Exception as e:
        print("Google API 錯誤:", e)
        return []

# ======================
# 過濾台南 + 戰鬥陀螺
# ======================
def is_relevant(text):
    keywords = ["台南", "Tainan", "戰鬥陀螺", "Beyblade", "ベイブレード"]
    return any(k.lower() in text.lower() for k in keywords)

# ======================
# 核心掃描與廣播任務
# ======================
def scan_and_notify():
    print("🔍 scanning via API...")
    conn = sqlite3.connect('seen_urls.db')
    c = conn.cursor()

    queries = [
        "戰鬥陀螺 台南 比賽",
        "Beyblade X Tainan tournament",
        "Beyblade 台南 活動"
    ]
    
    new_tournaments = []

    for q in queries:
        results = google_search_api(q)

        for r in results:
            title = r["title"]
            url = r["url"]

            if not is_relevant(title):
                continue

            # 檢查是否已經在資料庫中
            c.execute("SELECT * FROM urls WHERE url=?", (url,))
            if c.fetchone() is None:
                # 沒看過，存入資料庫並加入推播清單
                c.execute("INSERT INTO urls (url) VALUES (?)", (url,))
                new_tournaments.append(f"🏆 {title}\n{url}")

    conn.commit()
    conn.close()

    # 如果有新比賽，直接廣播給所有加好友的使用者
    if new_tournaments:
        msg = "🔥 發現新比賽情報！\n\n" + "\n\n".join(new_tournaments)
        try:
            line_bot_api.broadcast(TextSendMessage(text=msg))
            print("✅ 廣播成功")
        except Exception as e:
            print("廣播錯誤:", e)
            
    return len(new_tournaments)

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

    if "搜尋 台南" in text:
        count = scan_and_notify()
        reply = f"🔍 掃描完畢！共找到 {count} 筆新賽事（已推播）。"
    elif "列表" in text:
        reply = "目前系統已啟動 V2 雷達 🛰️ (廣播模式)"
    else:
        reply = "指令：\n搜尋 台南\n列表"

    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text=reply)
    )

# ======================
# 外部排程觸發端點
# ======================
@app.route("/cron/scan", methods=["GET"])
def cron_scan():
    count = scan_and_notify()
    return f"Scanned. Found {count} new items."

# ======================
# 首頁
# ======================
@app.route("/", methods=["GET"])
def home():
    return "Bey Radar V2 is alive! 🛰️"

# ======================
# 啟動
# ======================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)

from flask import Flask, request, abort
import os
import requests
import sqlite3
import json
from datetime import datetime
import google.generativeai as genai

from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage

app = Flask(__name__)

LINE_CHANNEL_SECRET = os.environ.get("LINE_CHANNEL_SECRET")
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")
SERPAPI_KEY = os.environ.get("SERPAPI_KEY") 
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY") 

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel('gemini-1.5-flash')

def init_db():
    conn = sqlite3.connect('seen_urls.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS urls (url TEXT PRIMARY KEY)''')
    conn.commit()
    conn.close()

init_db()

def google_search_threads(query):
    if not SERPAPI_KEY:
        return []
    search_query = f"site:threads.net {query}"
    url = f"https://serpapi.com/search.json?q={search_query}&api_key={SERPAPI_KEY}&num=10&hl=zh-tw&gl=tw"
    try:
        res = requests.get(url, timeout=10).json()
        results = []
        for item in res.get("organic_results", []):
            results.append({
                "title": item.get("title", ""),
                "snippet": item.get("snippet", ""), 
                "url": item.get("link", "")
            })
        return results
    except Exception as e:
        return []

def parse_post_with_ai(title, snippet):
    if not GEMINI_API_KEY:
        return None
    current_time = datetime.now().strftime('%Y-%m-%d %H:%M')
    prompt = f"你是一個專門分析戰鬥陀螺比賽資訊的 AI 助手。現在時間是：{current_time}。請閱讀以下 Threads 貼文，標題：{title}，內容：{snippet}。請擷取比賽資訊，並以嚴格的 JSON 格式回傳，不要加入任何 markdown 標籤，只要純 JSON 字串。格式如下：{{\"is_valid_tournament\": true, \"match_time\": \"比賽時間\", \"location\": \"地點\", \"capacity\": \"人數\", \"fee\": \"報名費\", \"deadline\": \"報名截止時間\", \"is_expired\": false}}。注意：只要看起來像是有玩家在揪團打陀螺、辦交流賽或報名，is_valid_tournament 就請給 true。若現在時間超過截止時間，is_expired 請填 true。"
    try:
        response = model.generate_content(prompt)
        text = response.text.strip()
        if text.startswith("```json"):
            text = text[7:-3].strip()
        elif text.startswith("```"):
            text = text[3:-3].strip()
        return json.loads(text)
    except Exception as e:
        return None

def scan_and_notify():
    conn = sqlite3.connect('seen_urls.db')
    c = conn.cursor()

    # 調整為真正專注在「交流、人流、主辦」的綜合關鍵字
    queries = [
        "台南 戰鬥陀螺 比賽",
        "台南 戰鬥陀螺 揪團",
        "台南 戰鬥陀螺 交流賽",
        "台南 戰陀 參賽"
    ]
    
    new_tournaments = []

    for q in queries:
        results = google_search_threads(q)
        for r in results:
            url = r["url"]
            c.execute("SELECT * FROM urls WHERE url=?", (url,))
            if c.fetchone() is not None:
                continue
                
            info = parse_post_with_ai(r["title"], r["snippet"])
            c.execute("INSERT INTO urls (url) VALUES (?)", (url,))
            
            if info:
                if info.get("is_valid_tournament") and not info.get("is_expired"):
                    msg = (
                        f"🏆 【新比賽情報 (Threads)】\n"
                        f"⏱️ 時間: {info.get('match_time')}\n"
                        f"📍 地點: {info.get('location')}\n"
                        f"👥 人數: {info.get('capacity')}\n"
                        f"💰 費用: {info.get('fee')}\n"
                        f"⏳ 截止: {info.get('deadline')}\n"
                        f"🔗 連結: {url}"
                    )
                    new_tournaments.append(msg)

    conn.commit()
    conn.close()

    if new_tournaments:
        msg = "🔥 發現最新 Threads 賽事！\n\n" + "\n\n---\n\n".join(new_tournaments)
        try:
            line_bot_api.broadcast(TextSendMessage(text=msg))
        except Exception as e:
            print(e)
            
    return len(new_tournaments)

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
    user_text = event.message.text
    
    if "除錯" in user_text:
        raw_results = google_search_threads("台南 戰鬥陀螺 比賽")
        if not raw_results:
            reply = "⚠️ 目前 Google 搜尋引擎尚未建立更多台南陀螺比賽的即時索引。"
        else:
            debug_msgs = []
            for idx, r in enumerate(raw_results[:4]):
                debug_msgs.append(f"🔍【監控中 {idx+1}】\n標題: {r['title']}\n網址: {r['url']}")
            reply = "🛠️ 【雷達運作正常，當前監控池前幾筆：】\n\n" + "\n\n---\n\n".join(debug_msgs)
            
    elif "搜尋" in user_text:
        count = scan_and_notify()
        reply = f"🔍 掃描完畢！已將新發現的賽事存入過濾庫。目前新群發：{count} 筆。"
    else:
        reply = "輸入「搜尋」主動手動發起雷達掃描，或輸入「除錯」確認當前雷達看見的視野！"

    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply))

@app.route("/cron/scan", methods=["GET"])
def cron_scan():
    count = scan_and_notify()
    return f"Scanned. Found {count} items."

@app.route("/", methods=["GET"])
def home():
    return "Bey Radar V4.0 (Global Monitor) is online! 🤖"

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)

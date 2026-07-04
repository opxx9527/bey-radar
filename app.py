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

# ======================
# 環境變數設定
# ======================
LINE_CHANNEL_SECRET = os.environ.get("LINE_CHANNEL_SECRET")
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")
SERPAPI_KEY = os.environ.get("SERPAPI_KEY") 
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY") 

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel('gemini-1.5-flash')

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
# SerpApi 搜尋 (加深搜查量到 10 筆)
# ======================
def google_search_threads(query):
    if not SERPAPI_KEY:
        print("⚠️ 缺少 SERPAPI_KEY")
        return []
        
    search_query = f"site:threads.net {query}"
    # num=10 讓搜尋引擎挖深一點，避免被大店家的日常公告擠掉
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
        print("SerpApi 錯誤:", e)
        return []

# ======================
# AI 解析貼文資訊 (Gemini)
# ======================
def parse_post_with_ai(title, snippet):
    if not GEMINI_API_KEY:
        print("⚠️ 缺少 GEMINI_API_KEY")
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
            
        data = json.loads(text)
        return data
    except Exception as e:
        print("AI 解析錯誤:", e)
        return None

# ======================
# 核心掃描與廣播任務
# ======================
def scan_and_notify():
    print("🔍 scanning Threads via SerpApi + Gemini...")
    conn = sqlite3.connect('seen_urls.db')
    c = conn.cursor()

    # 納入最精準的精準關鍵字與標籤特徵
    queries = [
        "台南 澀谷爆刃盃",
        "台南 爆刃盃",
        "#台南戰鬥陀螺",
        "台南 戰鬥陀螺 比賽"
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
            print("✅ 廣播成功")
        except Exception as e:
            print("廣播錯誤:", e)
            
    return len(new_tournaments)

# ======================
# LINE Webhook 路由
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

# ======================
# LINE 訊息處理器 (內建除錯)
# ======================
@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    text = event.message.text
    
    if "除錯" in text:
        # 除錯模式直接對準最精準的詞，抓 10 筆生肉
        raw_results = google_search_threads("台南 澀谷爆刃盃")
        
        if not raw_results:
            # 備用方案：搜尋標籤
            raw_results = google_search_threads("#台南戰鬥陀螺")
            
        if not raw_results:
            reply = "⚠️ 糟糕！SerpApi 連精準關鍵字都搜不到，這代表 Google 還沒把這篇 Threads 收錄到搜尋索引中（Threads 防爬蟲很常導致收錄延遲）。"
        else:
            debug_msgs = []
            for idx, r in enumerate(raw_results[:4]): # 多顯示幾筆
                debug_msgs.append(f"🔍【原始抓取 {idx+1}】\n標題: {r['title']}\n片段: {r['snippet']}\n網址: {r['url']}")
            
            reply = "🛠️ 【精準除錯模式：以下是 Google 挖深的生肉資料】\n\n" + "\n\n---\n\n".join(debug_msgs)
            
    elif "搜尋" in text:
        count = scan_and_notify()
        reply = f"🔍 Threads 掃描完畢！共找到 {count} 筆新賽事。"
    else:
        reply = "輸入「搜尋」尋找賽事，或輸入「除錯」查看原始抓取資料！"

    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply))

# ======================
# 排程與首頁端點
# ======================
@app.route("/cron/scan", methods=["GET"])
def cron_scan():

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

# 設定 Gemini AI
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
# SerpApi 搜尋 (鎖定 Threads)
# ======================
def google_search_threads(query):
    if not SERPAPI_KEY:
        print("⚠️ 缺少 SERPAPI_KEY")
        return []
        
    search_query = f"site:threads.net {query}"
    url = f"https://serpapi.com/search.json?q={search_query}&api_key={SERPAPI_KEY}&num=5&hl=zh-tw&gl=tw"
    
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
    
    # 確保 Prompt 沒有任何多餘大括號與斷行干擾
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

    queries = [
        "台南 戰鬥陀螺", 
        "台南 戰陀", 
        "台南 Beyblade X", 
        "台南 BXB",
        "台南 陀螺 比賽"
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
                        f"⏱️ 時間: {info

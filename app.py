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
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY") 
RAPIDAPI_KEY = os.environ.get("RAPIDAPI_KEY") 

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

KEY_ERR = 'er' + 'ror'
KEY_DBRAW = 'de' + 'bug_' + 'raw'

# ======================
# 🛡️ 萬能端點自動盲測抓取函式
# ======================
def search_threads_via_scraper(query):
    if not RAPIDAPI_KEY:
        return [{KEY_ERR: "缺少 RAPIDAPI_KEY 環境變數，請至 Render 後台設定。"}]
        
    # 嘗試 Threads Scraper 常見的 4 種搜尋網址路徑
    endpoints = [
        "https://threads-scraper.p.rapidapi.com/search/posts",
        "https://threads-scraper.p.rapidapi.com/search-posts",
        "https://threads-scraper.p.rapidapi.com/search_posts",
        "https://threads-scraper.p.rapidapi.com/search"
    ]
    
    querystring = {"query": query, "type": "posts"}
    headers = {
        "X-RapidAPI-Key": RAPIDAPI_KEY,
        "X-RapidAPI-Host": "threads-scraper.p.rapidapi.com"
    }
    
    last_error = ""
    data = None
    success_url = ""

    # 開始輪流測試端點
    for url in endpoints:
        try:
            response = requests.get(url, headers=headers, params=querystring, timeout=8)
            
            if response.status_code in [401, 403]:
                return [{KEY_ERR: f"RapidAPI 認證失敗 ({response.status_code})，請檢查金鑰。"}]
                
            if response.status_code == 200:
                data = response.json()
                # 如果回傳寫著 endpoint不存在，代表這個網址不對，換下一個
                if isinstance(data, dict) and "message" in data and "does not exist" in data["message"]:
                    last_error = data["message"]
                    continue
                
                # 走到這裡代表網址對了且成功拿到資料！
                success_url = url
                break
            else:
                last_error = f"HTTP {response.status_code}"
        except Exception as e:
            last_error = str(e)
            continue

    # 如果所有網址都失敗了
    if not data:
        return [{KEY_ERR: f"嘗試了所有可能的搜尋路徑皆失敗。最後一個錯誤：{last_error}"}]
        
    # 欄位解析邏輯
    results = []
    posts = []
    if isinstance(data, list):
        posts = data
    elif isinstance(data, dict):
        for key in ["data", "results", "posts", "items", "data_list"]:
            if key in data and isinstance(data[key], list):
                posts = data[key]
                break
        if not posts:
            inner_data = data.get("data", {})
            if isinstance(inner_data, dict):
                posts = inner_data.get("results", []) or inner_data.get("posts", [])
    
    if not posts and isinstance(data, dict):
        return [{KEY_DBRAW: json.dumps(data)[:500]}]

    for p in posts[:5]:
        post_text = p.get("text") or p.get("caption", {}).get("text", "") or p.get("snippet", "")
        post_id = p.get("id") or p.get("code") or p.get("post_id")
        
        if post_id and post_text:
            results.append({
                "title": "Threads 即時情報",
                "snippet": post_text,
                "url": f"https://www.threads.net/post/{post_id}"
            })
            
    return results

# ======================
# AI 解析貼文資訊 (Gemini)
# ======================
def parse_post_with_ai(title, snippet):
    if not GEMINI_API_KEY:
        return None
    current_time = datetime.now().strftime('%Y-%m-%d %H:%M')
    prompt = f"你是一個專門分析戰鬥陀螺比賽資訊的 AI 助手。現在時間是：{current_time}。請閱讀以下 Threads 貼文，標題：{title}，內容：{snippet}。請擷取比賽資訊，並以嚴格的 JSON 格式回傳，不要加入任何 markdown 標籤，只要純 JSON 字串。格式如下：{{\"is_valid_tournament\": true, \"match_time\": \"比賽時間\", \"location\": \"地點\", \"capacity\": \"人數\", \"fee\": \"報名費\", \"deadline\": \"報名截止時間\", \"is_expired\": false}}。"
    
    try:
        response = model.generate_content(prompt)
        text = response.text.strip()
        
        tb = '`' + '`' + '`'
        if text.startswith(tb + "json"):
            text = text[len(tb)+4 : -len(tb)].strip()
        elif text.startswith(tb):
            text = text[len(tb) : -len(tb)].strip()
            
        return json.loads(text)
    except Exception as e:
        return None

# ======================
# 核心監控主邏輯
# ======================
def scan_and_notify():
    conn = sqlite3.connect('seen_urls.db')
    c = conn.cursor()
    
    queries = ["台南戰鬥陀螺", "台南陀螺比賽"]
    new_tournaments = []

    for q in queries:
        results = search_threads_via_scraper(q)
        for r in results

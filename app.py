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
    
    prompt = f"""
    你是一個專門分析「戰鬥陀螺比賽」資訊的 AI 助手。
    現在時間是：{current_time}
    
    請閱讀以下 Threads 貼文的搜尋片段，並擷取比賽資訊。
    必須以嚴格的 JSON 格式回傳，不要加入 markdown 標籤(例如

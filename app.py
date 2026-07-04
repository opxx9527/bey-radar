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
                if isinstance(data, dict) and "message" in data and "does not exist" in data["message"]:
                    last_error = data["message"]
                    continue
                
                success_url = url
                break
            else:
                last_error = f"HTTP {response.status_code}"
        except Exception as e:
            last_error = str(e)
            continue

    if not data:
        return [{KEY_ERR: f"嘗試了所有可能的搜尋路徑皆失敗。最後一個錯誤：{last_error}"}]
        
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
        return

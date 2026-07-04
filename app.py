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
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY") 
RAPIDAPI_KEY = os.environ.get("RAPIDAPI_KEY") 

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

# ======================
# 🛡️ 增強型結構相容抓取
# ======================
def search_threads_via_scraper(query):
    if not RAPIDAPI_KEY:
        return []
        
    url = "https://threads-scraper.p.rapidapi.com/search"
    querystring = {"query": query, "type": "posts"}
    
    headers = {
        "X-RapidAPI-Key": RAPIDAPI_KEY,
        "X-RapidAPI-Host": "threads-scraper.p.rapidapi.com"
    }
    
    results = []
    try:
        response = requests.get(url, headers=headers, params=querystring, timeout=12)
        data = response.json()
        
        # 【核心修正】廣泛適應所有可能的 Threads API JSON 回傳層級
        posts = []
        if isinstance(data, list):
            posts = data
        elif isinstance(data, dict):
            # 遍歷尋找可能是陣列的欄位
            for key in ["data", "results", "posts", "items", "data_list"]:
                if key in data and isinstance(data[key], list):
                    posts = data[key]
                    break
            if not posts:
                # 某些 API 會包在更深的 data -> search_results 裡面
                inner_data = data.get("data", {})
                if isinstance(inner_data, dict):
                    posts = inner_data.get("results", []) or inner_data.get("posts", [])
        
        # 如果還是抓不到，把整個 JSON 結構丟進除錯區
        if not posts and isinstance(data, dict):
            return [{"debug_raw": json.dumps(data)[:500]}]

        for p in posts[:5]:
            # 適應不同的文字和 ID 欄位命名
            post_text = p.get("text") or p.get("caption", {}).get("text", "") or p.get("snippet", "")
            post_id = p.get("id") or p.get("code") or p.get("post_id")
            
            if post_id and post_text:
                results.append({
                    "title": "Threads 即時情報",
                    "snippet": post_text,
                    "url": f"https://www.threads.net/post/{post_id}"
                })
    except Exception as e:
        print("解析失敗:", e)
    
    return results

def parse_post_with_ai(title, snippet):
    if not GEMINI_API_KEY:
        return None
    current_time = datetime.now().strftime('%Y-%m-%d %H:%M')
    prompt = f"你是一個專門分析戰鬥陀螺比賽資訊的 AI 助手。現在時間是：{current_time}。請閱讀以下 Threads 貼文，標題：{title}，內容：{snippet}。請擷取比賽資訊，並以嚴格的 JSON 格式回傳，不要加入任何 markdown 標籤，只要純 JSON 字串。格式如下：{{\"is_valid_tournament\": true, \"match_time\": \"比賽時間\", \"location\": \"地點\", \"capacity\": \"人數\", \"fee\": \"報名費\", \"deadline\": \"報名截止時間\", \"is_expired\": false}}。"
    try:
        response = model.generate_content(prompt)
        text = response.text.strip()
        if text.startswith("
http://googleusercontent.com/immersive_entry_chip/0
http://googleusercontent.com/immersive_entry_chip/1

---

### 📥 這次的測試目標：
部署這版後，去 LINE 輸入 **`除錯`**。
* 如果程式自動適應成功，它會直接秀出 Threads 貼文內文。
* 如果結構特殊，它會回答 `⚙️ 【抓到原始結構！】請複製這段字給我：{"xxx": ...}`。

**只要你把那串 JSON 結構複製給我，我一眼就能看出它把資料命名為什麼，我們就可以直接收網宣告成功了！**

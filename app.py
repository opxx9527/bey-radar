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
LINE_CHANNEL_SECRET = os.environ.get("LINE_CHANNEL_SECRET", "")
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "") 
RAPIDAPI_KEY = os.environ.get("RAPIDAPI_KEY", "") 

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

if GEMINI_API_KEY:
    try:
        genai.configure(api_key=GEMINI_API_KEY)
        model = genai.GenerativeModel('gemini-1.5-flash')
    except Exception as e:
        print(f"Gemini 初始化失敗: {e}")
        model = None
else:
    model = None

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
# 🛡️ 精準對齊的 Threads Scraper 連線函式
# ======================
def search_threads_via_scraper(query):
    if not RAPIDAPI_KEY:
        return [{KEY_ERR: "缺少 RAPIDAPI_KEY 環境變數，請至 Render 後台設定。"}]
        
    url = "https://threads-scraper.p.rapidapi.com/api/v1/users/search"
    querystring = {"query": query}
    
    headers = {
        "X-RapidAPI-Key": RAPIDAPI_KEY,
        "X-RapidAPI-Host": "threads-scraper.p.rapidapi.com"
    }
    
    try:
        response = requests.get(url, headers=headers, params=querystring, timeout=8)
        
        if response.status_code in [401, 403]:
            return [{KEY_ERR: f"RapidAPI 認證失敗 ({response.status_code})，請確認金鑰是否過期。"}]
            
        if response.status_code != 200:
            return [{KEY_ERR: f"API 連線失敗，代碼：{response.status_code}"}]
            
        data = response.json()
    except Exception as e:
        return [{KEY_ERR: f"網路連線異常：{str(e)}"}]
        
    results = []
    users = []
    
    if isinstance(data, list):
        users = data
    elif isinstance(data, dict):
        for key in ["data", "results", "users", "items"]:
            if key in data and isinstance(data[key], list):
                users = data[key]
                break
        if not users:
            inner_data = data.get("data", {})
            if isinstance(inner_data, dict):
                users = inner_data.get("users", []) or inner_data.get("results", [])

    if not users and isinstance(data, dict):
        return [{KEY_DBRAW: json.dumps(data)[:500]}]

    for u in users[:5]:
        username = u.get("username") or u.get("user", {}).get("username", "")
        full_name = u.get("full_name") or u.get("user", {}).get("full_name", "Threads 陀螺玩家")
        biography = u.get("biography") or u.get("user", {}).get("biography", "暫無簡介")
        
        if username:
            results.append({
                "title": f"🎯 監控目標：{full_name} (@{username})",
                "snippet": biography,
                "url": f"https://www.threads.net/@{username}"
            })
            
    return results

# ======================
# AI 解析貼文資訊 (Gemini)
# ======================
def parse_post_with_ai(title, snippet):
    if not model:
        return None
    current_time = datetime.now().strftime('%Y-%m-%d %H:%M')
    prompt = f"你是一個專門分析戰鬥陀螺比賽資訊的 AI 助手。現在時間是：{current_time}。請閱讀以下資料，標題：{title}，內容：{snippet}。請判斷這是不是一個戰鬥陀螺比賽或相關社群推廣，並以嚴格的 JSON 格式回傳，不要加入 any markdown 標籤，只要純 JSON 字串。格式如下：{{\"is_valid_tournament\": true, \"match_time\": \"比賽時間或相關說明\", \"location\": \"地點\", \"capacity\": \"人數\", \"fee\": \"費用\", \"deadline\": \"截止時間\", \"is_expired\": false}}。"
    
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
    
    queries = ["戰鬥陀螺", "陀螺比賽"]
    new_tournaments = []

    for q in queries:
        results = search_threads_via_scraper(q)
        for r in results:
            if KEY_DBRAW in r or KEY_ERR in r: 
                continue
            url = r["url"]
            
            c.execute("SELECT * FROM urls WHERE url=?", (url,))
            if c.fetchone() is not None: 
                continue
                
            info = parse_post_with_ai(r["title"], r["snippet"])
            c.execute("INSERT INTO urls (url) VALUES (?)", (url,))
            
            if info and info.get("is_valid_tournament"):
                msg = (
                    f"🎯 【雷達鎖定：潛在賽事主辦方】\n"
                    f"👤 名稱: {r['title']}\n"
                    f"📝 簡介: {r['snippet'][:60]}...\n"
                    f"🔗 帳號連結: {url}"
                )
                new_tournaments.append(msg)
                
    conn.commit()
    conn.close()

    if new_tournaments and LINE_CHANNEL_ACCESS_TOKEN:
        try: 
            line_bot_api.broadcast(TextSendMessage(text="🔥 發現最新 Threads 相關陀螺帳號！\n\n" + "\n\n---\n\n".join(new_tournaments)))
        except Exception as e: 
            pass
            
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
    except Exception as e:
        print(f"Handler 處理內部錯誤: {e}")
        return "Internal Error", 500
    return "OK"

# ======================
# LINE 訊息處理
# ======================
@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_text = event.message.text

    if "除錯" in user_text:
        if not LINE_CHANNEL_ACCESS_TOKEN or not LINE_CHANNEL_SECRET:
            reply = "⚠️ 診斷回報：Render 後台缺少 LINE 的環境變數。"
        else:
            raw_results = search_threads_via_scraper("戰鬥陀螺")
            if raw_results and KEY_ERR in raw_results[0]:
                reply = f"⚠️ 偵測到連線異常：\n{raw_results[0][KEY_ERR]}"
            elif raw_results and KEY_DBRAW in raw_results[0]:
                reply = f"⚙️ 【API 已打通！】回傳結構不符，生肉結構：\n\n{raw_results[0][KEY_DBRAW]}"
            elif not raw_results:
                reply = "🟢 通道與金鑰完全正常！目前未偵測到相符的用戶。"
            else:
                debug_msgs = []
                for idx, r in enumerate(raw_results[:3]):
                    debug_msgs.append(f"🔍【直連成功 {idx+1}】\n帳號: {r['title']}\n簡介: {r['snippet']}")
                reply = "🛠️ 【精準路徑連線成功！】\n\n" + "\n\n---\n\n".join(debug_msgs)
            
    elif "搜尋" in user_text:
        count = scan_and_notify()
        reply = f"🔍 帳號雷達掃描完畢！共追蹤到 {count} 個與戰鬥陀螺相關的活躍標的。"
    else:
        reply = "輸入「搜尋」手動掃描最新帳號，或輸入「除錯」確認當前直連狀態！"

    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply))

@app.route("/cron/scan", methods=["GET"])
def cron_scan():
    count = scan_and_notify()
    return f"Scanned. Found {count} items."

@app.route("/", methods=["GET"])
def home():
    env_status = "OK" if (LINE_CHANNEL_ACCESS_TOKEN and LINE_CHANNEL_SECRET) else "MISSING_ENV"
    return f"Bey Radar V6.7 (Flawless Build) is active! Env: {env_status} 🤖"

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)

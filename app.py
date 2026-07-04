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

# 安全字串定義 (徹底避開 Render 關鍵字截斷機制)
KEY_ERR = 'er' + 'ror'
KEY_DBRAW = 'de' + 'bug_' + 'raw'

# ======================
# 🛡️ threads-scraper 專用抓取函式
# ======================
def search_threads_via_scraper(query):
    if not RAPIDAPI_KEY:
        return [{KEY_ERR: "缺少 RAPIDAPI_KEY 環境變數，請至 Render 後台設定。"}]
        
    url = "https://threads-scraper.p.rapidapi.com/search"
    querystring = {"query": query, "type": "posts"}
    
    headers = {
        "X-RapidAPI-Key": RAPIDAPI_KEY,
        "X-RapidAPI-Host": "threads-scraper.p.rapidapi.com"
    }
    
    results = []
    try:
        response = requests.get(url, headers=headers, params=querystring, timeout=12)
        
        if response.status_code in [401, 403]:
            return [{KEY_ERR: f"RapidAPI 拒絕連線 (HTTP {response.status_code})。請確認您的 RAPIDAPI_KEY 是否填寫正確，且有在該 API 頁面按下 'Subscribe to Test' 激活 Free 計畫。"}]
            
        data = response.json()
        
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
            if "message" in data:
                return [{KEY_ERR: f"API 回傳錯誤訊息: {data['message']}"}]
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
    except Exception as e:
        return [{KEY_ERR: f"網路連線或請求失敗: {str(e)}"}]
    
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
        print("AI 解析錯誤:", e)
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
        for r in results:
            if KEY_DBRAW in r or KEY_ERR in r: 
                continue
            url = r["url"]
            
            c.execute("SELECT * FROM urls WHERE url=?", (url,))
            if c.fetchone() is not None: 
                continue
                
            info = parse_post_with_ai(r["title"], r["snippet"])
            c.execute("INSERT INTO urls (url) VALUES (?)", (url,))
            
            if info and info.get("is_valid_tournament") and not info.get("is_expired"):
                msg = (
                    f"🏆 【即時雷達：新比賽情報】\n"
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
        try: 
            line_bot_api.broadcast(TextSendMessage(text="🔥 發現最新 Threads 賽事！\n\n" + "\n\n---\n\n".join(new_tournaments)))
        except Exception as e: 
            print("廣播失敗:", e)
            
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
# LINE 訊息處理
# ======================
@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_text = event.message.text
    
    if "除錯" in user_text:
        raw_results = search_threads_via_scraper("台南戰鬥陀螺")
        
        if raw_results and KEY_ERR in raw_results[0]:
            reply = f"⚠️ 偵測到連線異常：\n{raw_results[0][KEY_ERR]}"
            
        elif raw_results and KEY_DBRAW in raw_results[0]:
            reply = f"⚙️ 【已連線，但格式不符！】請將這段原始結構複製貼給我：\n\n{raw_results[0][KEY_DBRAW]}"
            
        elif not raw_results:
            reply = "🟢 API 通道連線完全正常！但目前 Threads 上暫時沒有包含「台南戰鬥陀螺」關鍵字的即時個人貼文。"
            
        else:
            debug_msgs = []
            for idx, r in enumerate(raw_results[:3]):
                debug_msgs.append(f"🔍【即時直連成功 {idx+1}】\n內容: {r['snippet']}\n網址: {r['url']}")
            reply = "🛠️ 【相容模式生肉資料】\n\n" + "\n\n---\n\n".join(debug_msgs)
            
    elif "搜尋" in user_text:
        test_run = search_threads_via_scraper("台南")
        if test_run and KEY_ERR in test_run[0]:
            reply = f"⚠️ 搜尋失敗！因為 API 連線目前異常：\n{test_run[0][KEY_ERR]}"
        else:
            count = scan_and_notify()
            reply = f"🔍 掃描完畢！共發現 {count} 筆即時新賽事。"
    else:
        reply = "輸入「搜尋」手動掃描最新貼文，或輸入「除錯」確認當前直連狀態！"

    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply))

# ======================
# 定期排程端點
# ======================
@app.route("/cron/scan", methods=["GET"])
def cron_scan():
    count = scan_and_notify()
    return f"Scanned. Found {count} items."

@app.route("/", methods=["GET"])
def home():
    return "Bey Radar V5.5 (Anti-Truncation Pro) is active! 🤖"

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)

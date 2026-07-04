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
RAPIDAPI_KEY = os.environ.get("RAPIDAPI_KEY") # 請將 RapidAPI 的金鑰填入 Render 的這個變數中

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
# 🛡️ threads-scraper 專用抓取函式
# ======================
def search_threads_via_scraper(query):
    if not RAPIDAPI_KEY:
        print("⚠️ 缺少 RAPIDAPI_KEY，請先至 Render 設定環境變數")
        return []
        
    # 對應你貼的 threads-scraper 的搜尋端點
    url = "https://threads-scraper.p.rapidapi.com/search"
    querystring = {"query": query, "type": "posts"} # 鎖定搜尋貼文
    
    headers = {
        "X-RapidAPI-Key": RAPIDAPI_KEY,
        "X-RapidAPI-Host": "threads-scraper.p.rapidapi.com"
    }
    
    results = []
    try:
        response = requests.get(url, headers=headers, params=querystring, timeout=12)
        data = response.json()
        
        # 解析 threads-scraper 的標準回傳格式
        # 通常包在 'data' 或直接是個清單，這裡做安全相容處理
        posts = data.get("data", []) if isinstance(data, dict) else data
        if not isinstance(posts, list):
            posts = data.get("results", []) or []
            
        for p in posts[:5]: # 每次拿最新 5 筆
            post_text = p.get("text") or p.get("caption", {}).get("text", "") or p.get("description", "")
            post_id = p.get("id") or p.get("code")
            
            if post_id and post_text:
                results.append({
                    "title": "Threads 即時情報",
                    "snippet": post_text,
                    "url": f"https://www.threads.net/post/{post_id}"
                })
    except Exception as e:
        print("threads-scraper 請求或解析失敗:", e)
    
    return results

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

    queries = ["台南戰鬥陀螺", "台南陀螺比賽"]
    new_tournaments = []

    for q in queries:
        results = search_threads_via_scraper(q)
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
        raw_results = search_threads_via_scraper("台南戰鬥陀螺")
        if not raw_results:
            reply = "⚠️ threads-scraper 連線正常，但目前關鍵字沒有匹配到最新的公開個人文，或者 API 欄位需要微調。"
        else:
            debug_msgs = []
            for idx, r in enumerate(raw_results[:4]):
                debug_msgs.append(f"🔍【即時直連成功 {idx+1}】\n內容: {r['snippet']}\n網址: {r['url']}")
            reply = "🛠️ 【threads-scraper 專用生肉模式】\n\n" + "\n\n---\n\n".join(debug_msgs)
            
    elif "搜尋" in user_text:
        count = scan_and_notify()
        reply = f"🔍 掃描完畢！共發現 {count} 筆即時新賽事。"
    else:
        reply = "輸入「搜尋」手動掃描最新貼文，或輸入「除錯」查看 Threads 目前的最前線動態！"

    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply))

@app.route("/cron/scan", methods=["GET"])
def cron_scan():
    count = scan_and_notify()
    return f"Scraper API Scanned. Found {count} items."

@app.route("/", methods=["GET"])
def home():
    return "Bey Radar V5.2 (Threads-Scraper Edition) is active! 🤖"

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)

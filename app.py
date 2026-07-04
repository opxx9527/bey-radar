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
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY") # 新增：Gemini API 金鑰

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# 設定 Gemini AI
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
    # 使用輕量快速的模型
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
        
    # 加上 site:threads.net 強制只搜 Threads
    search_query = f"site:threads.net {query}"
    url = f"https://serpapi.com/search.json?q={search_query}&api_key={SERPAPI_KEY}&num=5&hl=zh-tw&gl=tw"
    
    try:
        res = requests.get(url, timeout=10).json()
        results = []
        for item in res.get("organic_results", []):
            results.append({
                "title": item.get("title", ""),
                "snippet": item.get("snippet", ""), # 抓取貼文預覽文字給 AI 讀
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
    必須以嚴格的 JSON 格式回傳，不要加入 markdown 標籤(例如 ```json)，只要純 JSON 字串。
    
    貼文標題：{title}
    貼文內容：{snippet}
    
    JSON 格式定義：
    {{
      "is_valid_tournament": true/false, (只要貼文看起來像是有玩家在揪團打陀螺、辦私下比賽或交流賽，就請填 true，不要太嚴格)
      "match_time": "比賽時間 (若無則填'未提供')",
      "location": "地點 (若無則填'未提供')",
      "capacity": "人數 (若無則填'未提供')",
      "fee": "報名費 (若無則填'未提供')",
      "deadline": "報名截止時間 (若無則填'未提供')",
      "is_expired": true/false (判斷現在時間是否已經超過報名截止時間？若無法判斷或未提供，請填 false)
    }}
    """
    
    try:
        response = model.generate_content(prompt)
        text = response.text.strip()
        # 預防 AI 雞婆加上 ```json 標籤
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

    # 擴充針對台南玩家的關鍵字
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

            # 檢查是否已經看過
            c.execute("SELECT * FROM urls WHERE url=?", (url,))
            if c.fetchone() is not None:
                continue
                
            # 沒看過，交給 AI 讀取
            info = parse_post_with_ai(r["title"], r["snippet"])
            
            # 標記為已讀，存入資料庫
            c.execute("INSERT INTO urls (url) VALUES (?)", (url,))
            
            if info:
                # 判斷是否為有效比賽，且沒有過期
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
# LINE webhook 與排程端點保持不變 (省略顯示以節省空間，請直接保留你原本的設定)
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

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    text = event.message.text
    if "搜尋" in text:
        count = scan_and_notify()
        reply = f"🔍 Threads 掃描完畢！共找到 {count} 筆新賽事。"
    else:
        reply = "輸入「搜尋」來尋找最新台南陀螺比賽！"
    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply))

@app.route("/cron/scan", methods=["GET"])
def cron_scan():
    count = scan_and_notify()
    return f"Scanned Threads. Found {count} new items."

@app.route("/", methods=["GET"])
def home():
    return "Bey Radar V3 (Threads + AI) is alive! 🤖"

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)

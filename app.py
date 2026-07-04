from flask import Flask, request, abort
import os
import requests
import sqlite3
import json
from datetime import datetime
import google.generativeai as genai

from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, ImageMessage, TextSendMessage

app = Flask(__name__)

# ======================
# 環境變數設定
# ======================
LINE_CHANNEL_SECRET = os.environ.get("LINE_CHANNEL_SECRET", "")
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "") 
GOOGLE_SEARCH_API_KEY = os.environ.get("GOOGLE_SEARCH_API_KEY", "")
GOOGLE_CX = os.environ.get("GOOGLE_CX", "")

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

if GEMINI_API_KEY:
    try:
        genai.configure(api_key=GEMINI_API_KEY)
        model = genai.GenerativeModel('gemini-1.5-flash')
    except Exception:
        model = None
else:
    model = None

def init_db():
    conn = sqlite3.connect('seen_urls.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS urls (url TEXT PRIMARY KEY)''')
    conn.commit()
    conn.close()

init_db()
KEY_ERR = 'er' + 'ror'

# ======================
# Google 官方 API 海巡引擎
# ======================
def google_official_search(query_word):
    if not GOOGLE_SEARCH_API_KEY or not GOOGLE_CX:
        return [{KEY_ERR: "Missing Google Search API Key or CX"}]
        
    url = "https://www.googleapis.com/customsearch/v1"
    params = {
        "key": GOOGLE_SEARCH_API_KEY,
        "cx": GOOGLE_CX,
        "q": query_word,
        "dateRestrict": "w",
        "num": 10
    }
    
    results = []
    try:
        response = requests.get(url, params=params, timeout=10)
        if response.status_code != 200:
            return [{KEY_ERR: f"Google API Error HTTP: {response.status_code}"}]
        data = response.json()
        for item in data.get("items", []):
            link = item.get("link", "")
            snippet = item.get("snippet", "")
            if "threads.net/post/" in link or "threads.net/@" in link:
                results.append({"snippet": snippet, "url": link})
    except Exception as e:
        return [{KEY_ERR: str(e)}]
    return results

# ======================
# AI 審查機制 (Gemini)
# ======================
def parse_post_with_ai(snippet):
    if not model: return None
    current_time = datetime.now().strftime('%Y-%m-%d %H:%M')
    prompt = f"你是一個抓取台南比賽的雷達。現在時間：{current_time}。請審查貼文內容：「{snippet}」。這是不是在台灣「台南」舉辦的戰鬥陀螺比賽/活動/店家賽？不管是官方發的還是普通路人日常碎碎念，只要確認台南有活動就符合！請嚴格以 JSON 回傳（不要 markdown 標籤）。格式：{{\"is_tainan_bey\": true, \"match_time\": \"時間\", \"location\": \"地點\", \"details\": \"活動簡述\"}}。如果不符合，回傳：{{\"is_tainan_bey\": false}}。"
    
    try:
        response = model.generate_content(prompt)
        text = response.text.strip()
        tb = '`' + '`' + '`'
        if text.startswith(tb + "json"): text = text[len(tb)+4 : -len(tb)].strip()
        elif text.startswith(tb): text = text[len(tb) : -len(tb)].strip()
        return json.loads(text)
    except Exception:
        return None

# ======================
# 核心海巡邏輯
# ======================
def run_real_sea_patrol():
    conn = sqlite3.connect('seen_urls.db')
    c = conn.cursor()
    raw_posts = google_official_search("台南 戰鬥陀螺 比賽")
    
    if raw_posts and KEY_ERR in raw_posts[0]:
        return raw_posts[0][KEY_ERR], -1
        
    new_finds = []
    for p in raw_posts:
        url = p["url"]
        c.execute("SELECT * FROM urls WHERE url=?", (url,))
        if c.fetchone() is not None: continue
        c.execute("INSERT INTO urls (url) VALUES (?)", (url,))
        
        info = parse_post_with_ai(p["snippet"])
        if info and info.get("is_tainan_bey"):
            msg = f"[情報通知] 發現賽事線索\n時間: {info.get('match_time')}\n地點: {info.get('location')}\n內容: {info.get('details')}\n連結: {url}"
            new_finds.append(msg)
            
    conn.commit()
    conn.close()

    if new_finds and LINE_CHANNEL_ACCESS_TOKEN:
        try:
            line_bot_api.broadcast(TextSendMessage(text="[海巡雷達廣播] 發現最新台南賽事線索:\n\n" + "\n\n---\n\n".join(new_finds)))
        except Exception:
            pass
    return "Success", len(new_finds)

# ======================
# LINE Webhook 控制區
# ======================
@app.route("/webhook", methods=["POST"])
def webhook():
    signature = request.headers.get("X-Line-Signature")
    body = request.get_data(as_text=True)
    try: handler.handle(body, signature)
    except InvalidSignatureError: abort(400)
    except Exception: return "Internal Error", 500
    return "OK"

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_text = event.message.text

    if "除錯" in user_text:
        if not GOOGLE_SEARCH_API_KEY or not GOOGLE_CX:
            reply = "[診斷錯誤] 缺少環境變數 GOOGLE_SEARCH_API_KEY 或 GOOGLE_CX"
        else:
            test_run = google_official_search("台南")
            if test_run and KEY_ERR in test_run[0]:
                reply = f"[連線失敗] 錯誤原因: {test_run[0][KEY_ERR]}"
            else:
                reply = f"[系統正常] 官方引擎運作中。測試抓取到 {len(test_run)} 條公開資料。"
    elif "搜尋" in user_text or "海巡" in user_text:
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="[雷達啟動] 正在全網海巡普通路人的 Threads 貼文..."))
        status, count = run_real_sea_patrol()
        if count == -1:
            line_bot_api.broadcast(TextSendMessage(text=f"[海巡失敗] 原因: {status}"))
        else:
            line_bot_api.broadcast(TextSendMessage(text=f"[海巡報告] 審查完畢，本次捕獲 {count} 筆台南賽事。"))
        return
    else:
        reply = "請輸入「海巡」啟動全網路人貼文搜捕，或「直接傳送比賽海報照片」讓 AI 解析。"

    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply))

@handler.add(MessageEvent, message=ImageMessage)
def handle_image(event):
    message_id = event.message.id
    line_bot_api.reply_message(event.reply_token, TextSendMessage(text="[收到圖片] 正在分析海報內容，請稍候..."))
    try:
        message_content = line_bot_api.get_message_content(message_id)
        image_bytes = b""
        for chunk in message_content.iter_content(): image_bytes += chunk
            
        current_time = datetime.now().strftime('%Y-%m-%d %H:%M')
        prompt = f"現在時間是：{current_time}。請仔細閱讀這張戰鬥陀螺比賽海報照片，將裡面的繁體中文賽事資訊挖掘出來，並清晰條列回覆：1.主辦方/店名 2.日期與時間 3.精確地點 4.參賽資格與組別 5.費用 6.報名方式 7.備註。如果海報沒寫請寫『未提及』。"
        response = model.generate_content([{"mime_type": "image/jpeg", "data": image_bytes}, prompt])
        line_bot_api.broadcast(TextSendMessage(text=f"[AI 海報現場解析報告]\n\n{response.text.strip()}"))
    except Exception as e:
        line_bot_api.broadcast(TextSendMessage(text=f"[海報解析失敗] 錯誤原因: {str(e)}"))

@app.route("/cron/scan", methods=["GET"])
def cron_scan():
    status, count = run_real_sea_patrol()
    return f"Patrol done. Found {count} items. Status: {status}"

@app.route("/", methods=["GET"])
def home():
    return "Bey Radar V11.3 Clean Version Active"

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)

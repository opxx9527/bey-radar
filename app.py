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

# ✨ 新增：Google 官方搜尋金鑰
GOOGLE_SEARCH_API_KEY = os.environ.get("GOOGLE_SEARCH_API_KEY", "")
GOOGLE_CX = os.environ.get("GOOGLE_CX", "")

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

# ======================
# 🚀 透過 Google 官方 API 進行真·全網貼文海巡
# ======================
def google_official_search(query_word):
    if not GOOGLE_SEARCH_API_KEY or not GOOGLE_CX:
        return [{KEY_ERR: "缺少 GOOGLE_SEARCH_API_KEY 或 GOOGLE_CX 環境變數，請至 Render 後台設定。"}]
        
    # 官方終端點網址
    url = "https://www.googleapis.com/customsearch/v1"
    
    # 參數設定：限制只搜尋 threads.net 內文，且日期限定為最近一週 (dateRestrict='w')
    params = {
        "key": GOOGLE_SEARCH_API_KEY,
        "cx": GOOGLE_CX,
        "q": query_word,
        "dateRestrict": "w",  # 只撈一週內最新路人貼文
        "num": 10
    }
    
    results = []
    try:
        response = requests.get(url, params=params, timeout=10)
        if response.status_code != 200:
            return [{KEY_ERR: f"Google API 報錯，HTTP 代碼: {response.status_code}"}]
            
        data = response.json()
        items = data.get("items", [])
        
        for item in items:
            link = item.get("link", "")
            snippet = item.get("snippet", "")
            
            # 確保撈到的是真正的貼文路徑
            if "threads.net/post/" in link or "threads.net/@" in link:
                results.append({
                    "snippet": snippet,
                    "url": link
                })
    except Exception as e:
        return [{KEY_ERR: f"Google API 連線異常: {str(e)}"}]
        
    return results

# ======================
# AI 嚴格審查機制 (Gemini)
# ======================
def parse_post_with_ai(snippet):
    if not model: return None
    current_time = datetime.now().strftime('%Y-%m-%d %H:%M')
    
    prompt = (
        f"你是一個專門抓取台灣地方比賽的 AI 雷達。現在時間是：{current_time}。\n"
        f"請審查以下這段從 Threads 上撈到的路人日常貼文片段：\n"
        f"「{snippet}」\n\n"
        f"【審查任務】\n"
        f"1. 這是不是一個舉辦在台灣「台南」的戰鬥陀螺比賽、店家賽、俱樂部或玩家聚會？\n"
        f"2. 不管它是官方公告，還是普通路人帳號發的日常碎碎念（例如：帶小孩去台南打陀螺、台南某某店這週有陀螺賽），只要確認台南有活動，就算符合！\n"
        f"3. 如果符合，請以嚴格的 JSON 格式回傳（絕對不要加上 ```json 這樣的 markdown 標籤，只要純字串）。\n"
        f"格式：{{\"is_tainan_bey\": true, \"match_time\": \"活動時間\", \"location\": \"地點\", \"details\": \"活動簡述\"}}\n"
        f"4. 如果內容完全不符合，或根本不是台南的陀螺比賽，請回傳：{{\"is_tainan_bey\": false}}"
    )
    
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
# 核心：海巡主邏輯
# ======================
def run_real_sea_patrol():
    conn = sqlite3.connect('seen_urls.db')
    c = conn.cursor()
    
    # 丟出對普通路人最殺傷力的組合關鍵字
    raw_posts = google_official_search("台南 戰鬥陀螺 比賽")
    
    # 如果觸發錯誤回報
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
            msg = (
                f"🚨 【全網海巡：撈到路人情報！】\n"
                f"⏱️ 估計時間: {info.get('match_time')}\n"
                f"📍 預估地點: {info.get('location')}\n"
                f"📝 情報內容: {info.get('details')}\n"
                f"🔗 貼文直連: {url}"
            )
            new_finds.append(msg)
            
    conn.commit()
    conn.close()

    if new_finds and LINE_CHANNEL_ACCESS_TOKEN:
        try:
            line_bot_api.broadcast(TextSendMessage(text="🌊 【官方 API 貼文海巡】回報！\n經 AI 篩選過濾，發現最新台南賽事線索：\n\n" + "\n\n---\n\n".join(new_finds)))
        except Exception:
            pass
    return "成功", len(new_finds)

# ======================
# LINE Webhook 路由
# ======================
@app.route("/webhook", methods=["POST"])
def webhook():
    signature = request.headers.get("X-Line-Signature")
    body = request.get_data(as_text=True)
    try: handler.handle(body, signature)
    except InvalidSignatureError: abort(400)
    except Exception: return "Internal Error", 500
    return "OK"

# ======================
# 處理 LINE 文字訊息
# ======================
@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_text = event.message.text

    if "除錯" in user_text:
        if not GOOGLE_SEARCH_API_KEY or not GOOGLE_CX:
            reply = "⚠️ 診斷回報：缺少 Google 官方 API 金鑰，請至 Render 後台設定 GOOGLE_SEARCH_API_KEY 與 GOOGLE_CX！"
        else:
            test_run = google_official_search("台南")
            if test_run and KEY_ERR in test_run[0]:
                reply = f"⚠️ Google API 連線失敗：\n{test_run[0][KEY_ERR]}"
            else:
                reply = f"🟢 官方海巡引擎完全正常！目前已成功對接 Google 數據庫，隨時可進行無阻擋全網海巡。已預載 {len(test_run)} 條潛在 Threads 目標。"
                
    elif "搜尋" in user_text or "海巡" in user_text:
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="🛸 正在透過 Google 官方引擎全網搜捕普通路人的 Threads 貼文，請稍候..."))
        status, count = run_real_sea_patrol()
        if count == -1:
            line_bot_api.broadcast(TextSendMessage(text=f"❌ 海巡失敗，原因：\n{status}"))
        else:
            line_bot_api.broadcast(TextSendMessage(text=f"📊 海巡報告：官方通道審查完畢，本次共捕獲 {count} 筆台南賽事情報！"))
        return
    else:
        reply = "輸入「海巡」啟動官方全網貼文搜捕，或「直接傳送比賽海報照片」讓 AI 現場解析！"

    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply))

# ======================
# 處理 LINE 圖片訊息（保留海報現場分析功能）
# ======================
@handler.add(MessageEvent, message=ImageMessage)
def handle_image(event):
    message_id = event.message.id
    line_bot_api.reply_message(event.reply_token, TextSendMessage(text="📸 收到海報圖片！正在啟動 Gemini 現場解讀，請稍候..."))
    try:
        message_content = line_bot_api.get_message_content(message_id)
        image_bytes = b""
        for chunk in message_content.iter_content(): image_bytes += chunk
            
        current_time = datetime.now().strftime('%Y-%m-%d %H:%M')
        prompt = (
            f"現在時間是：{current_time}。請仔細閱讀這張戰鬥陀螺比賽海報的照片，"
            f"將照片中所有的繁體中文賽事資訊全部辨識並挖掘出來。"
            f"請用清晰、整齊的條列式繁體中文回覆我以下資訊：\n"
            f"1. 比賽主辦方/店名：\n"
            f"2. 比賽日期與時間：\n"
            f"3. 比賽精確地點：\n"
            f"4. 參賽資格/年齡/組別限制：\n"
            f"5. 報名費用：\n"
            f"6. 報名截止時間或方式：\n"
            f"7. 備註：\n\n"
            f"請直接依序條列，如果照片中完全沒有提到某項，請寫『海報未提及』。"
        )
        response = model.generate_content([{"mime_type": "image/jpeg", "data": image_bytes}, prompt])
        line_bot_api.broadcast(TextSendMessage(text=f"🎯 【AI 海報現場解析報告】\n\n{response.text.strip()}"))
    except Exception as e:
        line_bot_api.broadcast(TextSendMessage(text=f"❌ 海報解析失敗：{str(e)}"))

@app.route("/cron/scan", methods=["GET"])
def cron_scan():
    status, count = run_real_sea_patrol()
    return f"Patrol done. Found {count} items. Status: {status}"

@app.route("/", methods=["GET"])
def home():
    return "Bey Radar V11.0 (Official API Driven) is active! 🚀"

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
